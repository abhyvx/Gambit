"""Persist Gambit accounts across Render redeploys via GitHub Releases.

Render free disk is wiped every deploy. Same pattern as stake_overlay_cache:
bundle users + per-user portfolios → model-latest → bootstrap on boot.
Sessions are not restored (users sign in again; accounts and journals survive).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from bet_placer.config import data_path
from bet_placer.persistence.db import db_enabled, load_portfolio_state, load_users_dict

logger = logging.getLogger(__name__)

BUNDLE_NAME = "gambit_users_bundle.json"
_PUSH_LOCK = threading.Lock()
_LAST_PUSH = 0.0


def bundle_path() -> Path:
    return data_path(BUNDLE_NAME)


def export_users_bundle() -> dict[str, Any]:
    if db_enabled():
        users = load_users_dict()
        portfolios = {}
        for row in users.values():
            if not isinstance(row, dict):
                continue
            uid = str(row.get("id") or "").strip()
            if not uid:
                continue
            state = load_portfolio_state(uid)
            if isinstance(state, dict) and state:
                portfolios[uid] = state
        return {
            "version": 1,
            "exported_at": time.time(),
            "users": users,
            "portfolios": portfolios,
        }
    users_path = data_path("users.json")
    users = {}
    if users_path.is_file():
        try:
            users = json.loads(users_path.read_text(encoding="utf-8"))
        except Exception:
            users = {}
    if not isinstance(users, dict):
        users = {}
    portfolios: dict[str, Any] = {}
    port_dir = data_path("portfolios")
    if port_dir.is_dir():
        for p in port_dir.glob("*.json"):
            try:
                portfolios[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    # Also pull by user id in case glob missed a just-written file
    for row in users.values():
        if not isinstance(row, dict):
            continue
        uid = str(row.get("id") or "").strip()
        if not uid or uid in portfolios:
            continue
        path = data_path("portfolios", f"{uid}.json")
        if path.is_file():
            try:
                portfolios[uid] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {
        "version": 1,
        "exported_at": time.time(),
        "users": users,
        "portfolios": portfolios,
    }


def write_users_bundle() -> Path:
    blob = export_users_bundle()
    path = bundle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2, sort_keys=True), encoding="utf-8")
    return path


def restore_users_bundle(*, force: bool = False) -> dict[str, Any]:
    """Load bundle from disk into users.json + portfolios/. Skip if users already present unless force."""
    path = bundle_path()
    if not path.is_file():
        return {"ok": False, "reason": "missing"}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    users = blob.get("users") if isinstance(blob, dict) else None
    if not isinstance(users, dict) or not users:
        return {"ok": False, "reason": "empty"}
    users_path = data_path("users.json")
    if users_path.is_file() and not force:
        try:
            existing = json.loads(users_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing:
                # Merge: keep local newer emails, fill gaps from bundle
                merged = dict(users)
                merged.update(existing)
                users = merged
        except Exception:
            pass
    users_path.parent.mkdir(parents=True, exist_ok=True)
    users_path.write_text(json.dumps(users, indent=2, sort_keys=True), encoding="utf-8")
    port_dir = data_path("portfolios")
    port_dir.mkdir(parents=True, exist_ok=True)
    restored = 0
    for uid, state in (blob.get("portfolios") or {}).items():
        if not isinstance(state, dict):
            continue
        dest = port_dir / f"{uid}.json"
        if dest.is_file() and not force:
            continue
        dest.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        restored += 1
    return {"ok": True, "users": len(users), "portfolios": restored}


def _upload_release(path: Path) -> None:
    if not path.is_file():
        return
    if os.getenv("STAKE_UPLOAD_RELEASE", "").strip().lower() not in ("1", "true", "yes"):
        # Allow cloud token path without STAKE_UPLOAD_RELEASE
        if not (os.getenv("GAMBIT_GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")):
            return
    repo = os.getenv("GAMBIT_REPO", "abhyvx/Gambit")
    tag = os.getenv("GAMBIT_MODEL_TAG", "model-latest")
    env = os.environ.copy()
    tok = (os.getenv("GAMBIT_GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if tok:
        env["GH_TOKEN"] = tok
    try:
        subprocess.run(
            ["gh", "release", "upload", tag, str(path), "--repo", repo, "--clobber"],
            check=True,
            timeout=120,
            env=env,
        )
        logger.info("uploaded %s → %s@%s", path.name, repo, tag)
    except Exception as exc:
        logger.warning("users bundle upload skipped: %s", exc)


def schedule_users_persist() -> None:
    """Debounced write + optional GitHub upload after account/portfolio changes."""
    def _run() -> None:
        global _LAST_PUSH
        with _PUSH_LOCK:
            now = time.time()
            if now - _LAST_PUSH < 20:
                path = write_users_bundle()
                return
            _LAST_PUSH = now
            path = write_users_bundle()
            _upload_release(path)

    threading.Thread(target=_run, daemon=True).start()
