"""Append-only log of model training, grading, and weight updates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_MAX_EVENTS = 120

# Internal bookkeeping — never show these in Admin (user-facing activity).
_HIDDEN_KINDS = frozenset({
    "paper_craft",
    "paper_book",
    "gem_craft",
})


def log_activity(kind: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
    """Record one model action (persisted in params)."""
    # Paper-craft / board-book spam is not operator-facing.
    if str(kind or "") in _HIDDEN_KINDS:
        return
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
    from bet_placer.ml.params import load_params, save_params

    params = load_params()
    raw = list(params.get("activity_log") or [])
    cleaned = [e for e in raw if str((e or {}).get("kind") or "") not in _HIDDEN_KINDS]
    # Drop stale paper_craft rows so Admin stops showing 0-settled spam.
    if len(cleaned) != len(raw):
        params["activity_log"] = cleaned[-_MAX_EVENTS:]
        try:
            save_params(params)
        except Exception:
            pass
    return list(reversed(cleaned[-limit:]))
