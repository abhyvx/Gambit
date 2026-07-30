"""Optional cloud browser for Stake (Browserbase or raw CDP).

Render/datacenter IPs cannot open stake.com. A remote browser with residential
proxies keeps a real Chrome tab alive so odds scrape 24/7 and portfolio login
can happen via a live-view link — no local Chrome required when configured.

Env (no SDK dependency — plain HTTPS):
  BROWSERBASE_API_KEY
  STAKE_CDP_URL            (optional raw ws:// / wss:// override)
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from bet_placer.config import data_path, get_settings

logger = logging.getLogger(__name__)

_BB_API = "https://api.browserbase.com/v1"
_CONTEXT_PATH = data_path("browserbase_context.json")


def remote_browser_configured() -> bool:
    s = get_settings()
    return bool((s.stake_cdp_url or "").strip() or (s.browserbase_api_key or "").strip())


def _bb_headers() -> dict[str, str]:
    key = (get_settings().browserbase_api_key or "").strip()
    return {"X-BB-API-Key": key, "Content-Type": "application/json"}


def _http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_bb_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Browserbase {method} {url} → {exc.code}: {body}") from exc


def ensure_browserbase_context_id() -> str | None:
    """Persistent Browserbase context so Stake login/CF cookies survive sessions."""
    s = get_settings()
    if not (s.browserbase_api_key or "").strip():
        return None
    try:
        if _CONTEXT_PATH.is_file():
            raw = json.loads(_CONTEXT_PATH.read_text(encoding="utf-8"))
            cid = str(raw.get("id") or "").strip()
            if cid:
                return cid
    except Exception:
        pass

    created = _http_json("POST", f"{_BB_API}/contexts", {})
    cid = str(created.get("id") or "").strip()
    if not cid:
        raise RuntimeError("Browserbase context create returned no id")
    _CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONTEXT_PATH.write_text(json.dumps({"id": cid}, indent=2), encoding="utf-8")
    logger.info("Created Browserbase context %s", cid)
    return cid


def create_remote_session(*, timeout_s: int = 7200, keep_alive: bool = True) -> dict[str, Any]:
    """Open a cloud Chrome session. Returns connect_url + optional login_url."""
    s = get_settings()
    cdp = (s.stake_cdp_url or "").strip()
    if cdp:
        return {
            "connect_url": cdp,
            "session_id": None,
            "login_url": None,
            "provider": "cdp",
        }

    key = (s.browserbase_api_key or "").strip()
    if not key:
        raise RuntimeError("Set BROWSERBASE_API_KEY or STAKE_CDP_URL for cloud Stake browser")

    payload: dict[str, Any] = {
        "keepAlive": bool(keep_alive),
        "timeout": max(60, min(int(timeout_s), 21600)),
        "proxies": True,
        "browserSettings": {
            "solveCaptchas": True,
            "blockAds": True,
        },
    }
    ctx = ensure_browserbase_context_id()
    if ctx:
        payload["browserSettings"]["context"] = {"id": ctx, "persist": True}

    session = _http_json("POST", f"{_BB_API}/sessions", payload)
    sid = str(session.get("id") or "").strip()
    connect = str(session.get("connectUrl") or "").strip()
    if not connect:
        raise RuntimeError("Browserbase session missing connectUrl")

    login_url = None
    if sid:
        try:
            debug = _http_json("GET", f"{_BB_API}/sessions/{sid}/debug")
            login_url = (
                debug.get("debuggerFullscreenUrl")
                or debug.get("debuggerUrl")
                or None
            )
        except Exception as exc:
            logger.warning("Browserbase debug URL fetch failed: %s", exc)

    return {
        "connect_url": connect,
        "session_id": sid or None,
        "login_url": login_url,
        "provider": "browserbase",
        "context_id": ctx,
    }


def session_login_url(session_id: str) -> str | None:
    if not session_id:
        return None
    try:
        debug = _http_json("GET", f"{_BB_API}/sessions/{session_id}/debug")
        pages = debug.get("pages") or []
        if pages:
            return pages[-1].get("debuggerFullscreenUrl") or pages[-1].get("debuggerUrl")
        return debug.get("debuggerFullscreenUrl") or debug.get("debuggerUrl")
    except Exception as exc:
        logger.debug("session_login_url failed: %s", exc)
        return None
