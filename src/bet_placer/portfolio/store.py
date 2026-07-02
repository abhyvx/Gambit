from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from bet_placer.config import get_settings
from bet_placer.data.stake_browser import browser_status, warmup

_LOCK = Lock()
_CONSENT_VERSION = "2026-07-02"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path() -> Path:
    settings = get_settings()
    if settings.portfolio_store_path:
        return Path(settings.portfolio_store_path).expanduser()
    return Path.home() / ".bet_placer" / "portfolio_state.json"


def _default_state() -> dict[str, Any]:
    return {
        "privacy": {
            "portfolio_enabled": False,
            "visibility": "private",
            "risk_acknowledged": False,
            "learning_opt_in": False,
            "consent_version": _CONSENT_VERSION,
            "consent_accepted_at": None,
        },
        "connection": {
            "mode": "browser_session",
            "status": "disconnected",
            "connected": False,
            "last_connected_at": None,
            "last_sync_at": None,
            "last_sync_status": "never",
            "last_sync_message": "Portfolio sync is off until you enable it.",
        },
        "portfolio": {
            "bet_count": 0,
            "settled_count": 0,
            "open_count": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "total_staked": 0.0,
            "total_return": 0.0,
            "roi_pct": 0.0,
            "last_imported_at": None,
            "bets": [],
        },
    }


def _load_state() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()
    state = _default_state()
    for key in ("privacy", "connection", "portfolio"):
        if isinstance(data.get(key), dict):
            state[key].update(data[key])
    return state


def _save_state(state: dict[str, Any]) -> dict[str, Any]:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state


def _merged_status(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state)
    browser = browser_status()
    out["connection"]["browser"] = browser
    if browser.get("ready"):
        out["connection"]["status"] = "connected"
        out["connection"]["connected"] = True
    elif browser.get("warming"):
        out["connection"]["status"] = "connecting"
        out["connection"]["connected"] = False
    return out


def get_portfolio_state() -> dict[str, Any]:
    with _LOCK:
        return _merged_status(_load_state())


def update_privacy_settings(*, portfolio_enabled: bool, risk_acknowledged: bool, learning_opt_in: bool) -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        state["privacy"].update(
            {
                "portfolio_enabled": bool(portfolio_enabled),
                "risk_acknowledged": bool(risk_acknowledged),
                "learning_opt_in": bool(learning_opt_in),
                "consent_version": _CONSENT_VERSION,
                "consent_accepted_at": _utc_now() if risk_acknowledged else state["privacy"].get("consent_accepted_at"),
            }
        )
        if not portfolio_enabled:
            state["connection"]["last_sync_message"] = "Portfolio sync is disabled. Existing imported data stays private until you delete it."
        return _merged_status(_save_state(state))


def connect_browser_session(timeout: int = 180) -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        ok = warmup(timeout=timeout)
        browser = browser_status()
        if ok or browser.get("ready"):
            state["connection"].update(
                {
                    "status": "connected",
                    "connected": True,
                    "last_connected_at": _utc_now(),
                    "last_sync_message": "Stake browser session is ready. Log into Stake in that browser if needed, then open Portfolio to refresh.",
                }
            )
        else:
            state["connection"].update(
                {
                    "status": "connecting",
                    "connected": False,
                    "last_sync_message": (
                        "Stake browser opened, but the session is not ready yet. "
                        "Complete Cloudflare/login in the browser window, then retry."
                    ),
                }
            )
        return _merged_status(_save_state(state))


def disconnect_browser_session() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        state["connection"].update(
            {
                "status": "disconnected",
                "connected": False,
                "last_sync_message": "Disconnected from Stake. Imported portfolio data remains saved privately until you delete it.",
            }
        )
        return _merged_status(_save_state(state))


def refresh_portfolio_snapshot() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        if not state["privacy"].get("portfolio_enabled"):
            raise ValueError("Enable private portfolio sync before refreshing.")
        if not state["privacy"].get("risk_acknowledged"):
            raise ValueError("Accept the privacy warning before refreshing.")

        browser = browser_status()
        if not browser.get("ready"):
            state["connection"].update(
                {
                    "status": "disconnected",
                    "connected": False,
                    "last_sync_at": _utc_now(),
                    "last_sync_status": "needs_reconnect",
                    "last_sync_message": "Stake session is not active. Reconnect the browser session, then refresh again.",
                }
            )
            return _merged_status(_save_state(state))

        state["connection"].update(
            {
                "status": "connected",
                "connected": True,
                "last_sync_at": _utc_now(),
                "last_sync_status": "session_ready",
                "last_sync_message": (
                    "Browser session refreshed successfully. Private portfolio storage is ready; "
                    "account-history import is the next step to wire into this session."
                ),
            }
        )
        return _merged_status(_save_state(state))
