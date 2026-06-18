"""Learned model parameters + probability calibration (lightweight, no heavy deps).

This is the *memory* of the model. The tracker fits these from real results;
the prediction path reads them every time so the model keeps improving as more
World Cup games finish.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PARAMS_PATH = Path.home() / ".bet_placer" / "model_params.json"

DEFAULT_PARAMS: dict = {
    "version": 0,
    # Platt scaling per market group: p_cal = sigmoid(a * logit(p) + b)
    "calibration": {
        "result": {"a": 1.0, "b": 0.0},
        "totals": {"a": 1.0, "b": 0.0},
        "btts": {"a": 1.0, "b": 0.0},
        "_global": {"a": 1.0, "b": 0.0},
    },
    "goals_scale": 1.0,     # multiplies expected total goals
    "home_edge_adj": 0.0,   # added to home goal-supremacy
    "trained_on": 0,        # number of finished matches used
    "updated_at": None,
    # Learned from the full history of international football (ml/historical.py)
    "elo": {},              # canonical team name -> Elo rating
    "goal_model": {},       # {sup_a, sup_b, tot_a, tot_b} mapping Elo edge -> goals
}

_cache: dict | None = None


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_params(force: bool = False) -> dict:
    global _cache
    if _cache is not None and not force:
        return _cache
    p = DEFAULT_PARAMS
    try:
        if PARAMS_PATH.exists():
            p = _merge(DEFAULT_PARAMS, json.loads(PARAMS_PATH.read_text()))
    except Exception:
        p = DEFAULT_PARAMS
    _cache = p
    return p


def save_params(params: dict) -> None:
    global _cache
    PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARAMS_PATH.write_text(json.dumps(params, indent=2))
    _cache = params


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


def calibrate_prob(p: float | None, market: str | None) -> float | None:
    """Apply the learned calibration for this market group."""
    if p is None:
        return None
    if p <= 0 or p >= 1:
        return p
    params = load_params()
    cal = params.get("calibration", {})
    grp = market_group(market)
    coef = cal.get(grp) or cal.get("_global") or {"a": 1.0, "b": 0.0}
    a = coef.get("a", 1.0)
    b = coef.get("b", 0.0)
    if a == 1.0 and b == 0.0:
        return p
    return _sigmoid(a * _logit(p) + b)
