"""Stake same-game multis — only scraped pre-built combo markets.

Stake does not expose arbitrary leg combinations via our scraper. Real SGMs are
markets whose names contain "&" with a single combined price from Stake.
We never multiply single-line odds to fake an SGM price.
"""

from __future__ import annotations

import math
from typing import Any

def estimate_stake_combo_probability(
    combo: dict,
    pool: list | None = None,
    home: str = "",
    away: str = "",
) -> float:
    """Conservative model probability for a verified Stake SGM."""
    from bet_placer.engine.bet_portfolio import _pool_match_for_pick
    from bet_placer.engine.card_coherence import decompose_stake_combo

    odds = float(combo.get("odds") or 0)
    if odds <= 1.0:
        return 0.0

    implied = 1.0 / odds
    parts = decompose_stake_combo(combo, home, away)
    if not parts:
        return max(0.01, min(implied * 0.85, 0.12))

    leg_probs: list[float] = []
    for part in parts:
        opt = _pool_match_for_pick(pool or [], part, home, away)
        if opt:
            leg_probs.append(float(getattr(opt, "our_probability", 0) or 0))
        else:
            leg_probs.append(0.20)

    if not leg_probs:
        return max(0.01, min(implied * 0.85, 0.12))

    product = math.prod(leg_probs)
    n = len(leg_probs)
    # Correlated legs — product overstates independence; cap by weakest leg and book implied.
    correlated = product * (0.92 ** max(0, n - 1))
    correlated = min(correlated, min(leg_probs) * 0.98)
    return max(0.01, min(correlated, implied * 0.90, 0.50))


def _payout_closeness(return_inr: float, target_inr: float) -> float:
    """Higher when payout is near target (not a huge overshoot)."""
    if target_inr <= 0:
        return 0.0
    ratio = return_inr / target_inr
    if ratio < 0.95:
        return ratio / 0.95
    if ratio <= 1.20:
        return 1.0 - abs(ratio - 1.0) / 0.20
    return max(0.0, 1.0 - (ratio - 1.20) / 1.5)


def _sgm_sweetness(odds: float, peak: float = 4.5) -> float:
    """Higher near peak — Stake-style 3-leg SGMs cluster around 3–5x."""
    if odds <= 1.0:
        return -9.0
    return -abs(math.log(odds) - math.log(peak))


def search_stake_combos(
    combos: list[dict],
    budget_inr: float,
    target_inr: float,
    *,
    min_prob: float = 0.0,
    max_odds: float | None = None,
    min_odds: float = 0.0,
    sweet_spot: tuple[float, float] | None = None,
    pool: list | None = None,
    home: str = "",
    away: str = "",
) -> list[dict]:
    """Build hit-target plans from verified Stake combo markets only."""
    if not combos or budget_inr <= 0 or target_inr <= budget_inr:
        return []

    out: list[dict] = []
    for c in combos:
        from bet_placer.engine.card_coherence import stake_combo_is_garbage
        if stake_combo_is_garbage(c, home, away):
            continue
        odds = float(c.get("odds") or 0)
        if odds <= 1.0 or odds < min_odds or (max_odds is not None and odds > max_odds):
            continue
        stake = _min_stake_for_return(odds, target_inr)
        if stake <= 0 or stake > budget_inr:
            continue
        ret = round(stake * odds)
        if ret < target_inr:
            continue
        hit_prob = estimate_stake_combo_probability(c, pool, home, away)
        if hit_prob < min_prob:
            continue
        hit_pct = round(hit_prob * 100, 1)
        from bet_placer.markets.labels import format_combo_label
        raw_lbl = c.get("label") or c.get("stake_market")
        leg = {
            "market": "stake_combo",
            "label": format_combo_label(raw_lbl, odds, home, away, stake_market=c.get("stake_market")),
            "selection": c.get("selection"),
            "line": c.get("line"),
            "odds": odds,
            "our_probability": hit_prob,
            "our_probability_pct": hit_pct,
            "source": "stake",
            "odds_source": "stake",
            "live_odds": True,
            "verified_stake": True,
            "stake_market": c.get("stake_market"),
            "role": "stake_combo",
        }
        out.append({
            "plan_type": "stake_combo",
            "ticket_type": "stake_sgm",
            "verified_stake": True,
            "stake_market": c.get("stake_market"),
            "label": format_combo_label(raw_lbl, odds, home, away, stake_market=c.get("stake_market")),
            "selection": c.get("selection"),
            "line": c.get("line"),
            "odds": odds,
            "stake_inr": stake,
            "return_inr": ret,
            "profit_inr": ret - stake,
            "hit_probability": hit_prob,
            "hit_probability_pct": hit_pct,
            "combined_probability": hit_prob,
            "combined_probability_pct": hit_pct,
            "legs": [leg],
            "source": "stake",
            "_payout_closeness": _payout_closeness(ret, target_inr),
        })

    out.sort(
        key=lambda p: (
            p.get("hit_probability", 0) >= 0.20,
            _sgm_sweetness(float(p.get("combined_odds") or p.get("odds") or 0)),
            p.get("hit_probability", 0),
            p.get("_payout_closeness", 0),
            -abs(p["return_inr"] - target_inr),
        ),
        reverse=True,
    )
    for p in out:
        p.pop("_payout_closeness", None)
    return out


def build_tickets_from_plan(plan: dict, home: str, away: str) -> list[dict]:
    """Group plan legs into Stake tickets — verified SGM vs separate singles."""
    from bet_placer.engine.bet_portfolio import format_inr

    ptype = plan.get("plan_type")
    legs = plan.get("legs") or []

    if ptype == "combo":
        stake = plan.get("total_stake_inr") or plan.get("stake_inr") or 0
        n = len(legs)
        return [{
            "ticket_type": "estimated_parlay",
            "ticket_label": f"Estimated {n}-leg parlay",
            "stake_inr": stake,
            "potential_return_inr": plan.get("target_return_inr"),
            "combined_odds": plan.get("combined_odds"),
            "legs": legs,
            "placement_note": (
                f"Add all {n} legs to the same Stake bet slip as a same-game multi. "
                "Payout is estimated from scraped singles until Stake verifies the combo."
            ),
            "combinable": True,
            "verified_stake": False,
        }]

    if ptype == "stake_combo":
        stake = plan.get("stake_inr") or plan.get("total_stake_inr") or 0
        market = plan.get("stake_market") or plan.get("label")
        return [{
            "ticket_type": "stake_sgm",
            "ticket_label": "Stake combo (verified)",
            "stake_inr": stake,
            "potential_return_inr": plan.get("target_return_inr"),
            "combined_odds": plan.get("combined_odds") or plan.get("odds"),
            "legs": legs,
            "placement_note": (
                f"Find this under Stake Combos: “{market}”. "
                "Price is scraped from Stake — not estimated."
            ),
            "combinable": True,
            "verified_stake": True,
            "stake_market": market,
        }]

    if ptype == "match_card":
        tickets = []
        for i, leg in enumerate(legs, 1):
            if leg.get("stake_inr", 0) <= 0:
                continue
            ret = leg.get("return_inr") or round((leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
            role = leg.get("role", "route")
            is_combo = role == "stake_combo"
            hits = leg.get("hits_target")
            note = (
                "Separate bet on Stake — if this wins alone, you hit your target."
                if hits else
                "Separate bet on Stake — extra angle; target route is another ticket."
            )
            tickets.append({
                "ticket_type": "stake_sgm" if is_combo else "single",
                "ticket_label": f"Ticket {i}",
                "stake_inr": leg.get("stake_inr"),
                "potential_return_inr": ret,
                "combined_odds": leg.get("odds") if is_combo else None,
                "legs": [leg],
                "placement_note": note,
                "combinable": is_combo,
                "verified_stake": bool(leg.get("live_odds") or leg.get("odds_source") == "stake"),
                "stake_market": leg.get("stake_market") if is_combo else None,
            })
        return tickets

    if ptype == "coverage":
        tickets = []
        for i, leg in enumerate(legs, 1):
            if leg.get("stake_inr", 0) <= 0:
                continue
            ret = leg.get("return_inr") or round((leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
            hits = leg.get("hits_target")
            tickets.append({
                "ticket_type": "single",
                "ticket_label": f"Ticket {i}",
                "stake_inr": leg.get("stake_inr"),
                "potential_return_inr": ret,
                "legs": [leg],
                "placement_note": (
                    "Separate single on Stake — if this wins, you hit your target."
                    if hits else
                    "Separate single on Stake — probable leg; another ticket carries the target."
                ),
                "combinable": False,
                "verified_stake": bool(leg.get("live_odds") or leg.get("odds_source") == "stake"),
            })
        return tickets

    staked = [l for l in legs if l.get("stake_inr", 0) > 0]
    if ptype == "single" and len(staked) == 1:
        leg = staked[0]
        return [{
            "ticket_type": "single",
            "ticket_label": "Single bet",
            "stake_inr": leg.get("stake_inr"),
            "potential_return_inr": plan.get("target_return_inr"),
            "legs": [leg],
            "placement_note": "One single bet on Stake.",
            "combinable": False,
            "verified_stake": bool(leg.get("live_odds") or leg.get("odds_source") == "stake"),
        }]

    tickets = []
    for i, leg in enumerate(staked, 1):
        ret = leg.get("return_inr") or round((leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
        tickets.append({
            "ticket_type": "single",
            "ticket_label": f"Single {i}" if len(staked) > 1 else "Single bet",
            "stake_inr": leg.get("stake_inr"),
            "potential_return_inr": ret,
            "legs": [leg],
            "placement_note": "Place separately on Stake.",
            "combinable": False,
            "verified_stake": bool(leg.get("live_odds") or leg.get("odds_source") == "stake"),
        })
    if ptype == "split" and tickets:
        tickets[-1]["placement_note"] = (
            f"Place {len(tickets)} separate singles — all must win to collect "
            f"{format_inr(plan.get('target_return_inr', 0))} combined."
        )
    return tickets


def build_tickets_from_plans(plans: list[dict]) -> list[dict]:
    """Flatten planner output into UI ticket rows."""
    tickets: list[dict] = []
    for plan in plans:
        ptype = plan.get("plan_type", "")
        if ptype == "stake_combo":
            tickets.append({
                "type": "stake_sgm",
                "verified": True,
                "stake_market": plan.get("stake_market"),
                "label": plan.get("label"),
                "stake_inr": plan.get("stake_inr"),
                "odds": plan.get("odds"),
                "return_inr": plan.get("return_inr"),
                "profit_inr": plan.get("profit_inr"),
                "legs": plan.get("legs", []),
            })
        elif ptype in ("single", "coverage", "split"):
            for leg in plan.get("legs", []):
                tickets.append({
                    "type": "single",
                    "verified": leg.get("source") == "stake",
                    "label": leg.get("label") or leg.get("selection"),
                    "stake_inr": leg.get("stake_inr"),
                    "odds": leg.get("odds"),
                    "return_inr": leg.get("return_inr"),
                    "profit_inr": leg.get("return_inr", 0) - leg.get("stake_inr", 0),
                    "legs": [leg],
                })
    return tickets


def _min_stake_for_return(odds: float, target_inr: float) -> float:
    if odds <= 1.0 or target_inr <= 0:
        return 0.0
    raw = target_inr / odds
    return _round_stake_inr(raw)


def _round_stake_inr(amount: float) -> float:
    """Match Stake INR stake steps (nearest ₹10, min ₹10)."""
    if amount <= 0:
        return 0.0
    stepped = max(10.0, round(amount / 10.0) * 10.0)
    return stepped


def can_stake_same_game_multi(*_args: Any, **_kwargs: Any) -> bool:
    """Deprecated heuristic — always False. Use scraped stake_combos instead."""
    return False
