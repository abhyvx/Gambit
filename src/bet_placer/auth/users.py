"""Lightweight Gambit user accounts (email + password). No OAuth deps."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from threading import Lock
from typing import Any

from bet_placer.config import data_path
from bet_placer.persistence.db import (
    db_enabled,
    delete_portfolio_state,
    load_portfolio_state,
    load_sessions_dict,
    load_users_dict,
    save_sessions_dict,
    save_users_dict,
)

_LOCK = Lock()
_USERS = data_path("users.json")
_SESSIONS = data_path("sessions.json")
_PBKDF_ITERS = 120_000


def _load(path: Path) -> dict[str, Any]:
    if db_enabled():
        if path == _USERS:
            return load_users_dict()
        if path == _SESSIONS:
            return load_sessions_dict()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    if db_enabled():
        if path == _USERS:
            save_users_dict(data)
            return
        if path == _SESSIONS:
            save_sessions_dict(data)
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF_ITERS,
    ).hex()
    return salt, digest


def _check_password(password: str, salt: str, digest: str) -> bool:
    _, got = _hash_password(password, salt)
    return hmac.compare_digest(got, digest)


def signup(*, email: str, password: str, name: str | None = None) -> dict[str, Any]:
    email = (email or "").strip().lower()
    password = password or ""
    if "@" not in email or len(email) < 5:
        raise ValueError("Enter a valid email.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    with _LOCK:
        users = _load(_USERS)
        if email in users:
            raise ValueError("That email already has an account. Sign in instead.")
        uid = secrets.token_hex(8)
        salt, digest = _hash_password(password)
        users[email] = {
            "id": uid,
            "email": email,
            "name": (name or email.split("@")[0]).strip()[:64],
            "salt": salt,
            "password": digest,
            "created_at": time.time(),
        }
        _save(_USERS, users)
        token = _issue_session(uid, email)
        try:
            from bet_placer.auth.persist import schedule_users_persist
            schedule_users_persist()
        except Exception:
            pass
        return {"token": token, "user": public_user(users[email])}


def login(*, email: str, password: str) -> dict[str, Any]:
    email = (email or "").strip().lower()
    with _LOCK:
        users = _load(_USERS)
        row = users.get(email)
        if not row or not _check_password(password, row.get("salt") or "", row.get("password") or ""):
            raise ValueError("Email or password is wrong.")
        token = _issue_session(row["id"], email)
        return {"token": token, "user": public_user(row)}


def _issue_session(uid: str, email: str) -> str:
    sessions = _load(_SESSIONS)
    token = secrets.token_urlsafe(32)
    sessions[token] = {"user_id": uid, "email": email, "created_at": time.time()}
    # ponytail: drop sessions older than 90d — fine for student app scale
    cutoff = time.time() - 90 * 86400
    sessions = {k: v for k, v in sessions.items() if float(v.get("created_at") or 0) >= cutoff}
    sessions[token] = {"user_id": uid, "email": email, "created_at": time.time()}
    _save(_SESSIONS, sessions)
    return token


def logout(token: str | None) -> None:
    if not token:
        return
    with _LOCK:
        sessions = _load(_SESSIONS)
        sessions.pop(token, None)
        _save(_SESSIONS, sessions)


def user_from_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _LOCK:
        sessions = _load(_SESSIONS)
        sess = sessions.get(token)
        if not sess:
            return None
        email = sess.get("email")
        users = _load(_USERS)
        row = users.get(email) if email else None
        if not row:
            return None
        return public_user(row)


def delete_account(token: str | None) -> None:
    """Remove user row, sessions, and portfolio file."""
    user = user_from_token(token)
    if not user:
        raise ValueError("Not signed in.")
    email = user.get("email")
    uid = user.get("id")
    with _LOCK:
        users = _load(_USERS)
        users.pop(email, None)
        _save(_USERS, users)
        sessions = _load(_SESSIONS)
        sessions = {k: v for k, v in sessions.items() if v.get("email") != email and v.get("user_id") != uid}
        _save(_SESSIONS, sessions)
    if uid:
        if db_enabled():
            delete_portfolio_state(uid)
        else:
            path = data_path("portfolios", f"{uid}.json")
            try:
                if path.is_file():
                    path.unlink()
            except Exception:
                pass
    try:
        from bet_placer.auth.persist import schedule_users_persist
        schedule_users_persist()
    except Exception:
        pass


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "name": row.get("name"),
    }


def is_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    from bet_placer.config import get_settings

    settings = get_settings()
    emails = {
        e.strip().lower()
        for e in (settings.gambit_admin_emails or "").split(",")
        if e.strip()
    }
    return bool(emails) and (user.get("email") or "").strip().lower() in emails


def list_accounts_for_admin() -> list[dict[str, Any]]:
    """Safe account roster: no passwords, no Stake tokens."""
    with _LOCK:
        users = _load(_USERS)
        sessions = _load(_SESSIONS)
    sess_by_uid: dict[str, int] = {}
    for s in sessions.values():
        uid = s.get("user_id")
        if uid:
            sess_by_uid[uid] = sess_by_uid.get(uid, 0) + 1
    out = []
    for email, row in sorted(users.items(), key=lambda kv: kv[0]):
        uid = row.get("id")
        has_token = False
        bet_count = 0
        sync_status = None
        sync_message = None
        if db_enabled():
            port = load_portfolio_state(uid) or {}
            secrets = port.get("secrets") or {}
            has_token = bool(secrets.get("stake_api_token"))
            bets = ((port.get("portfolio") or {}).get("bets") or [])
            bet_count = len(bets) if isinstance(bets, list) else 0
            conn = port.get("connection") or {}
            sync_status = conn.get("last_sync_status")
            sync_message = conn.get("last_sync_message")
        else:
            port_path = data_path("portfolios", f"{uid}.json")
            if port_path.is_file():
                try:
                    port = json.loads(port_path.read_text(encoding="utf-8"))
                    secrets = port.get("secrets") or {}
                    has_token = bool(secrets.get("stake_api_token"))
                    bets = ((port.get("portfolio") or {}).get("bets") or [])
                    bet_count = len(bets) if isinstance(bets, list) else 0
                    conn = port.get("connection") or {}
                    sync_status = conn.get("last_sync_status")
                    sync_message = conn.get("last_sync_message")
                except Exception:
                    pass
        out.append(
            {
                "id": uid,
                "email": email,
                "name": row.get("name"),
                "created_at": row.get("created_at"),
                "sessions": sess_by_uid.get(uid, 0),
                "has_stake_token": has_token,
                "bet_count": bet_count,
                "last_sync_status": sync_status,
                "last_sync_message": (str(sync_message)[:160] if sync_message else None),
            }
        )
    return out


def revoke_user_sessions(user_id: str) -> int:
    with _LOCK:
        sessions = _load(_SESSIONS)
        before = len(sessions)
        sessions = {k: v for k, v in sessions.items() if v.get("user_id") != user_id}
        _save(_SESSIONS, sessions)
        return before - len(sessions)
