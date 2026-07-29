"""SQLite memory for craft training progress — epochs, equity, sport stats.

ponytail: stdlib sqlite3 only. Overall progress for the Model page, not ticket dumps.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".bet_placer" / "craft.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS epochs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            games INTEGER,
            bets INTEGER,
            accuracy REAL,
            roi REAL,
            pnl REAL,
            bankroll REAL,
            threshold REAL,
            nn_loss REAL,
            by_sport TEXT,
            by_market TEXT,
            detail TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            epoch INTEGER,
            bankroll REAL,
            roi REAL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    con.commit()
    return con


def set_meta(key: str, value: Any) -> None:
    con = connect()
    con.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )
    con.commit()
    con.close()


def get_meta(key: str, default=None):
    con = connect()
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    con.close()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default


def log_epoch(row: dict[str, Any]) -> None:
    con = connect()
    con.execute(
        """
        INSERT INTO epochs(
            at, epoch, games, bets, accuracy, roi, pnl, bankroll,
            threshold, nn_loss, by_sport, by_market, detail
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _now(),
            int(row.get("epoch") or 0),
            int(row.get("games") or 0),
            int(row.get("bets") or 0),
            row.get("accuracy"),
            row.get("roi"),
            row.get("pnl"),
            row.get("bankroll"),
            row.get("threshold"),
            row.get("nn_loss"),
            json.dumps(row.get("by_sport") or {}),
            json.dumps(row.get("by_market") or {}),
            json.dumps(row.get("detail") or {}),
        ),
    )
    con.execute(
        "INSERT INTO equity(at, epoch, bankroll, roi) VALUES (?,?,?,?)",
        (_now(), int(row.get("epoch") or 0), row.get("bankroll"), row.get("roi")),
    )
    con.commit()
    con.close()
    # Every 10 epochs, freeze a comparison block (not live tick noise)
    if int(row.get("epoch") or 0) % 10 == 0:
        try:
            archive_block()
        except Exception:
            pass


def archive_block(block_size: int = 10) -> dict[str, Any]:
    """Freeze last N epochs as a named block for Model chart comparison."""
    snap = progress_snapshot(limit_epochs=block_size)
    epochs = snap.get("epochs") or []
    if len(epochs) < 3:
        return {}
    rois = [float(e["roi"]) for e in epochs if e.get("roi") is not None]
    accs = [float(e["accuracy"]) for e in epochs if e.get("accuracy") is not None]
    by_sport: dict[str, dict] = {}
    for sp in ("soccer", "basketball", "cricket"):
        ns = hits = pnl = stake = 0.0
        for e in epochs:
            row = (e.get("by_sport") or {}).get(sp) or {}
            n = int(row.get("n") or 0)
            if not n:
                continue
            ns += n
            hr = row.get("hit_rate")
            if hr is not None:
                hits += float(hr) * n
            pnl += float(row.get("pnl") or 0)
            stake += float(row.get("stake") or 0) or (n * 150.0)
        by_sport[sp] = {
            "n": int(ns),
            "hit_rate": round(hits / ns, 4) if ns else None,
            "roi": round(pnl / stake, 4) if stake else None,
        }
    block = {
        "at": _now(),
        "epochs": len(epochs),
        "mean_roi": round(sum(rois) / len(rois), 4) if rois else None,
        "mean_acc": round(sum(accs) / len(accs), 4) if accs else None,
        "roi_trend": rois,
        "accuracy_trend": accs,
        "by_sport": by_sport,
        "label": f"block·{len(epochs)}ep·roi{rois[-1] if rois else '?'}",
    }
    prev = get_meta("craft_block") or {}
    if prev:
        set_meta("craft_block_prev", prev)
    set_meta("craft_block", block)
    # Append to short history of blocks
    hist = list(get_meta("craft_blocks") or [])
    hist.append({k: block[k] for k in ("at", "epochs", "mean_roi", "mean_acc", "label")})
    set_meta("craft_blocks", hist[-24:])
    return block


def progress_snapshot(limit_epochs: int = 80) -> dict[str, Any]:
    """Overall craft progress for the Model page — aggregates only."""
    con = connect()
    epochs = [
        dict(r)
        for r in con.execute(
            "SELECT * FROM epochs ORDER BY id DESC LIMIT ?", (limit_epochs,)
        ).fetchall()
    ]
    equity = [
        dict(r)
        for r in con.execute(
            "SELECT at, epoch, bankroll, roi FROM equity ORDER BY id ASC"
        ).fetchall()
    ]
    status = get_meta("train_status") or {}
    best = get_meta("best_roi") or {}
    # Hide sentinel / invalid bests from UI (-1 init or sub-floor accuracy)
    if best.get("roi") is not None:
        try:
            br = float(best.get("roi"))
            ba = float(best.get("accuracy") or 0)
            if br < -0.5 or ba < 0.60:
                best = {}
        except (TypeError, ValueError):
            best = {}
    block = get_meta("craft_block") or {}
    block_prev = get_meta("craft_block_prev") or {}
    blocks = get_meta("craft_blocks") or []
    con.close()

    epochs = list(reversed(epochs))
    for e in epochs:
        for k in ("by_sport", "by_market", "detail"):
            if isinstance(e.get(k), str):
                try:
                    e[k] = json.loads(e[k])
                except Exception:
                    e[k] = {}

    rois = [float(e["roi"]) for e in epochs if e.get("roi") is not None]
    accs = [float(e["accuracy"]) for e in epochs if e.get("accuracy") is not None]
    latest = epochs[-1] if epochs else {}
    return {
        "source": "boards+paired_closes",
        "epochs": epochs,
        "equity_curve": equity[-120:],
        "n_epochs": len(epochs),
        "latest": {
            "epoch": latest.get("epoch"),
            "roi": latest.get("roi"),
            "accuracy": latest.get("accuracy"),
            "bets": latest.get("bets"),
            "games": latest.get("games"),
            "pnl": latest.get("pnl"),
            "bankroll": latest.get("bankroll"),
            "threshold": latest.get("threshold"),
            "by_sport": latest.get("by_sport") or {},
            "by_market": latest.get("by_market") or {},
            "by_selection": (latest.get("detail") or {}).get("by_selection") or {},
        },
        "best": best,
        "train_status": status,
        "roi_trend": rois,
        "accuracy_trend": accs,
        "block": block,
        "block_prev": block_prev,
        "blocks": blocks,
        "target_roi": 0.25,
        "target_accuracy": 0.60,
        "hit_target": bool(
            best.get("roi") is not None
            and float(best.get("roi") or 0) >= 0.25
            and float(best.get("accuracy") or 0) >= 0.60
            and int(best.get("bets") or 0) >= 10_000
        ),
        "holdout": get_meta("craft_holdout_v2") or {},
        "champion": best if best.get("holdout") else (get_meta("craft_champion") or {}),
    }
