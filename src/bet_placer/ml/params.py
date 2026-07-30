"""Learned model parameters + probability calibration (lightweight, no heavy deps).

This is the *memory* of the model. The tracker fits these from real results;
the prediction path reads them every time so the model keeps improving as more
games finish.

Critical for cloud: Render boots the API *before* ``bootstrap_model.sh``
finishes downloading ``model_params.json``. If we cache an empty Elo table at
first request, every match forever looks like 1.45/1.20 home priors. We always
seed from ``bundled_strength.json`` (ships in the image) and re-load when the
on-disk params file appears or changes.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from bet_placer.config import data_path

logger = logging.getLogger(__name__)

PARAMS_PATH = data_path("model_params.json")
BUNDLED_STRENGTH_PATH = Path(__file__).with_name("bundled_strength.json")

DEFAULT_PARAMS: dict = {
    "version": 0,
    # Platt scaling per market group: p_cal = sigmoid(a * logit(p) + b)
    "calibration": {
        "result": {"a": 1.0, "b": 0.0},
        "totals": {"a": 1.0, "b": 0.0},
        "btts": {"a": 1.0, "b": 0.0},
        "draw": {"a": 1.0, "b": 0.0},
        "_global": {"a": 1.0, "b": 0.0},
    },
    "goals_scale": 1.0,     # multiplies expected total goals
    "home_edge_adj": 0.0,   # added to home goal-supremacy
    "trained_on": 0,        # number of finished matches used
    "updated_at": None,
    # Learned from the full history of international football (ml/historical.py)
    "elo": {},              # canonical team name -> Elo rating
    "goal_model": {},       # {sup_a, sup_b, tot_a, tot_b} mapping Elo edge -> goals
    "ad_model": {},         # {att, def, mu, ha, w_elo} attack/defence ensemble
}

_cache: dict | None = None
_cache_mtime: float | None = None
_cache_bundled: bool = False


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _merge_elo_tables(base: dict, over: dict) -> dict:
    """Union of Elo tables — keep the stronger rating on key collision."""
    out = dict(base or {})
    for k, v in (over or {}).items():
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if k not in out:
            out[k] = fv
            continue
        try:
            if fv > float(out[k]):
                out[k] = fv
        except (TypeError, ValueError):
            out[k] = fv
    return out


def _load_bundled_strength() -> dict:
    try:
        if BUNDLED_STRENGTH_PATH.exists():
            return json.loads(BUNDLED_STRENGTH_PATH.read_text())
    except Exception:
        logger.warning("bundled_strength.json unreadable", exc_info=True)
    return {}


def _disk_mtime() -> float | None:
    try:
        if PARAMS_PATH.exists():
            return float(PARAMS_PATH.stat().st_mtime)
    except Exception:
        return None
    return None


def _elo_count(params: dict | None) -> int:
    if not isinstance(params, dict):
        return 0
    n = len(params.get("elo") or {})
    for tbl in (params.get("elo_by_sport") or {}).values():
        if isinstance(tbl, dict):
            n += len(tbl)
    return n


def load_params(force: bool = False) -> dict:
    """Load params with bundled Elo floor + disk overlay.

    Re-reads when ``model_params.json`` appears/changes after bootstrap, so the
    first pre-bootstrap request cannot permanently pin an empty Elo cache.
    """
    global _cache, _cache_mtime, _cache_bundled

    mtime = _disk_mtime()
    if (
        not force
        and _cache is not None
        and _cache_mtime == mtime
        and (_elo_count(_cache) > 0 or mtime is None)
    ):
        return _cache

    p = dict(DEFAULT_PARAMS)
    bundled = _load_bundled_strength()
    if bundled:
        p = _merge(p, bundled)
        # Elo tables: explicit max-merge so empty disk `{}` cannot wipe the seed
        if isinstance(bundled.get("elo"), dict):
            p["elo"] = _merge_elo_tables({}, bundled["elo"])
        if isinstance(bundled.get("elo_by_sport"), dict):
            merged_sport: dict = {}
            for sport, tbl in bundled["elo_by_sport"].items():
                if isinstance(tbl, dict):
                    merged_sport[sport] = _merge_elo_tables({}, tbl)
            p["elo_by_sport"] = merged_sport

    try:
        if PARAMS_PATH.exists():
            disk = json.loads(PARAMS_PATH.read_text())
            disk_elo = disk.get("elo") if isinstance(disk, dict) else None
            disk_by = disk.get("elo_by_sport") if isinstance(disk, dict) else None
            p = _merge(p, disk if isinstance(disk, dict) else {})
            if isinstance(disk_elo, dict) and disk_elo:
                p["elo"] = _merge_elo_tables(p.get("elo") or {}, disk_elo)
            if isinstance(disk_by, dict) and disk_by:
                sports = dict(p.get("elo_by_sport") or {})
                for sport, tbl in disk_by.items():
                    if isinstance(tbl, dict) and tbl:
                        sports[sport] = _merge_elo_tables(sports.get(sport) or {}, tbl)
                p["elo_by_sport"] = sports
    except Exception:
        logger.warning("model_params.json unreadable; using bundled strength", exc_info=True)

    if _elo_count(p) == 0:
        logger.warning("load_params: Elo tables empty after bundled+disk merge")
    elif not _cache_bundled and bundled:
        logger.info(
            "load_params: strength ready (elo=%d, goal_model=%s, disk=%s)",
            len(p.get("elo") or {}),
            bool(p.get("goal_model")),
            PARAMS_PATH.exists(),
        )

    _cache = p
    _cache_mtime = mtime
    _cache_bundled = bool(bundled)
    return p


def save_params(params: dict) -> None:
    global _cache, _cache_mtime
    PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARAMS_PATH.write_text(json.dumps(params, indent=2))
    _cache = params
    _cache_mtime = _disk_mtime()


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def market_group(market: str | None) -> str:
    """Map any market (our enum value OR a raw Stake market name) to a group."""
    m = (market or "").lower()
    if "corner" in m or "card" in m or "booking" in m:
        return "_global"
    if "both teams" in m or m == "btts":
        return "btts"
    if any(k in m for k in ("total", "over", "under", "goal", "exact")):
        return "totals"
    if any(k in m for k in ("handicap", "1x2", "winner", "result", "double chance",
                            "draw no bet", "moneyline")):
        return "result"
    return "_global"


def calibrate_prob(p: float | None, market: str | None, selection: str | None = None) -> float | None:
    """Apply the learned calibration for this market group."""
    if p is None:
        return None
    if p <= 0 or p >= 1:
        return p
    params = load_params()
    cal = params.get("calibration", {})
    grp = market_group(market)
    sel = (selection or "").lower()
    if sel == "draw" or grp == "result" and sel == "draw":
        coef = cal.get("draw") or cal.get("result") or cal.get("_global") or {"a": 1.0, "b": 0.0}
    else:
        coef = cal.get(grp) or cal.get("_global") or {"a": 1.0, "b": 0.0}
    a = coef.get("a", 1.0)
    b = coef.get("b", 0.0)
    if a == 1.0 and b == 0.0:
        return p
    return _sigmoid(a * _logit(p) + b)
