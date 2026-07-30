from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, MetaData, String, Table, Text, create_engine, delete, select

from bet_placer.config import data_path, get_settings

_META = MetaData()

USERS = Table(
    "users",
    _META,
    Column("email", String, primary_key=True),
    Column("id", String, nullable=False),
    Column("name", String, nullable=False),
    Column("salt", String, nullable=False),
    Column("password", String, nullable=False),
    Column("created_at", String, nullable=False),
)

SESSIONS = Table(
    "sessions",
    _META,
    Column("token", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("email", String, nullable=False),
    Column("created_at", String, nullable=False),
)

PORTFOLIOS = Table(
    "portfolio_states",
    _META,
    Column("user_id", String, primary_key=True),
    Column("state_json", JSON, nullable=False),
)

BLOBS = Table(
    "state_blobs",
    _META,
    Column("key", String, primary_key=True),
    Column("value_json", JSON, nullable=False),
)


def db_enabled() -> bool:
    return bool((get_settings().database_url or "").strip())


def _normalize_database_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        return ""
    if url.startswith("sqlite+"):
        return url
    if url.startswith("sqlite://"):
        return url
    if url.startswith("libsql://"):
        return f"sqlite+{url}?secure=true"
    if url.startswith("https://") or url.startswith("http://"):
        return f"sqlite+libsql://{url.split('://', 1)[1]}?secure=true"
    return url


def _connect_args() -> dict[str, Any]:
    settings = get_settings()
    raw = (settings.database_url or "").strip()
    if raw.startswith(("libsql://", "https://", "http://")) and (settings.turso_auth_token or "").strip():
        return {"auth_token": settings.turso_auth_token.strip()}
    return {}


@lru_cache(maxsize=1)
def engine():
    url = _normalize_database_url(get_settings().database_url)
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(url, connect_args=_connect_args(), future=True, pool_pre_ping=True)


def init_db() -> None:
    if not db_enabled():
        return
    _META.create_all(engine())


def _portfolio_key(user_id: str | None) -> str:
    return (user_id or "__global__").strip() or "__global__"


def load_users_dict() -> dict[str, Any]:
    if not db_enabled():
        return {}
    with engine().begin() as conn:
        rows = conn.execute(select(USERS)).mappings().all()
    return {
        str(row["email"]): {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "salt": row["salt"],
            "password": row["password"],
            "created_at": row["created_at"],
        }
        for row in rows
    }


def save_users_dict(data: dict[str, Any]) -> None:
    if not db_enabled():
        return
    with engine().begin() as conn:
        conn.execute(delete(USERS))
        for email, row in (data or {}).items():
            if not isinstance(row, dict):
                continue
            conn.execute(
                USERS.insert().values(
                    email=email,
                    id=str(row.get("id") or ""),
                    name=str(row.get("name") or ""),
                    salt=str(row.get("salt") or ""),
                    password=str(row.get("password") or ""),
                    created_at=str(row.get("created_at") or ""),
                )
            )


def load_sessions_dict() -> dict[str, Any]:
    if not db_enabled():
        return {}
    with engine().begin() as conn:
        rows = conn.execute(select(SESSIONS)).mappings().all()
    return {
        str(row["token"]): {
            "user_id": row["user_id"],
            "email": row["email"],
            "created_at": row["created_at"],
        }
        for row in rows
    }


def save_sessions_dict(data: dict[str, Any]) -> None:
    if not db_enabled():
        return
    with engine().begin() as conn:
        conn.execute(delete(SESSIONS))
        for token, row in (data or {}).items():
            if not isinstance(row, dict):
                continue
            conn.execute(
                SESSIONS.insert().values(
                    token=token,
                    user_id=str(row.get("user_id") or ""),
                    email=str(row.get("email") or ""),
                    created_at=str(row.get("created_at") or ""),
                )
            )


def load_portfolio_state(user_id: str | None) -> dict[str, Any] | None:
    if not db_enabled():
        return None
    key = _portfolio_key(user_id)
    with engine().begin() as conn:
        row = conn.execute(select(PORTFOLIOS.c.state_json).where(PORTFOLIOS.c.user_id == key)).scalar_one_or_none()
    return dict(row) if isinstance(row, dict) else None


def save_portfolio_state(user_id: str | None, state: dict[str, Any]) -> None:
    if not db_enabled():
        return
    key = _portfolio_key(user_id)
    payload = json.loads(json.dumps(state))
    with engine().begin() as conn:
        conn.execute(delete(PORTFOLIOS).where(PORTFOLIOS.c.user_id == key))
        conn.execute(PORTFOLIOS.insert().values(user_id=key, state_json=payload))


def delete_portfolio_state(user_id: str | None) -> None:
    if not db_enabled():
        return
    with engine().begin() as conn:
        conn.execute(delete(PORTFOLIOS).where(PORTFOLIOS.c.user_id == _portfolio_key(user_id)))


def load_blob(key: str, default=None):
    if not db_enabled():
        return default
    with engine().begin() as conn:
        row = conn.execute(select(BLOBS.c.value_json).where(BLOBS.c.key == key)).scalar_one_or_none()
    return row if row is not None else default


def save_blob(key: str, value: Any) -> None:
    if not db_enabled():
        return
    payload = json.loads(json.dumps(value))
    with engine().begin() as conn:
        conn.execute(delete(BLOBS).where(BLOBS.c.key == key))
        conn.execute(BLOBS.insert().values(key=key, value_json=payload))


def import_legacy_files_if_empty() -> dict[str, Any]:
    if not db_enabled():
        return {"ok": False, "reason": "db_disabled"}
    init_db()
    with engine().begin() as conn:
        has_users = conn.execute(select(USERS.c.email)).first() is not None
        has_portfolios = conn.execute(select(PORTFOLIOS.c.user_id)).first() is not None
    if has_users or has_portfolios:
        return {"ok": True, "imported": False}

    users_path = data_path("users.json")
    sessions_path = data_path("sessions.json")
    portfolios_dir = data_path("portfolios")
    stake_sync_jobs = data_path("stake_sync_jobs.json")
    relay_heartbeat = data_path("relay_heartbeat.json")
    portfolio_state = data_path("portfolio_state.json")

    def _read_json(path: Path, default):
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    users = _read_json(users_path, {})
    sessions = _read_json(sessions_path, {})
    save_users_dict(users)
    save_sessions_dict(sessions)
    if portfolios_dir.is_dir():
        for p in portfolios_dir.glob("*.json"):
            try:
                state = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            save_portfolio_state(p.stem, state)
    global_state = _read_json(portfolio_state, None)
    if isinstance(global_state, dict):
        save_portfolio_state(None, global_state)
    for key, path in (
        ("stake_sync_jobs", stake_sync_jobs),
        ("relay_heartbeat", relay_heartbeat),
    ):
        value = _read_json(path, None)
        if value is not None:
            save_blob(key, value)
    return {"ok": True, "imported": True, "users": len(users), "sessions": len(sessions)}
