"""Append-only log of model training, grading, and weight updates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_MAX_EVENTS = 120


def log_activity(kind: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
    """Record one model action (persisted in params)."""
    from bet_placer.ml.params import load_params, save_params

    params = load_params()
    log: list[dict] = list(params.get("activity_log") or [])
    log.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "message": message,
        "detail": detail or {},
    })
    params["activity_log"] = log[-_MAX_EVENTS:]
    save_params(params)


def get_activity_log(limit: int = 40) -> list[dict]:
    from bet_placer.ml.params import load_params

    log = load_params().get("activity_log") or []
    return list(reversed(log[-limit:]))
