"""Short technical ticket lines — probability, role, stake math. No narrative fluff."""

from __future__ import annotations

from bet_placer.engine.bet_portfolio import leg_net_if_solo_win, target_profit_inr
from bet_placer.markets.labels import format_ticket_label


def _pct(leg: dict) -> str:
    p = leg.get("our_probability_pct")
    if p is None and leg.get("our_probability") is not None:
        p = round(float(leg["our_probability"]) * 100, 1)
    return f"{p}%" if p is not None else "n/a"


def _route_is_partial(leg: dict, all_legs: list[dict], profit_goal: float) -> bool:
    if leg.get("partial_profit_route"):
        return True
    if leg.get("hits_target"):
        return False
    net = leg_net_if_solo_win(leg, all_legs)
    return profit_goal > 0 and net < profit_goal * 0.95


def explain_leg(
    leg: dict,
    *,
    home: str,
    away: str,
    budget: float,
    target_cashout: float,
    all_legs: list[dict],
    ctx: dict | None = None,
) -> str:
    del ctx  # unused — no fan/narrative bits on tickets
    role = leg.get("role") or ""
    label = format_ticket_label(leg, home, away, with_odds=False)
    pct = _pct(leg)
    odds = leg.get("odds")
    odds_s = f" @ {float(odds):.2f}" if odds else ""
    profit_goal = target_profit_inr(budget, target_cashout)
    net = leg_net_if_solo_win(leg, all_legs)
    mkt = leg.get("market") or ""

    if role in ("target_lotto", "stake_combo", "route"):
        partial = _route_is_partial(leg, all_legs, profit_goal)
        tag = "partial" if partial else "hits_target" if leg.get("hits_target") else "route"
        return (
            f"{label}{odds_s} · p={pct} · {mkt or 'route'} · {tag} · "
            f"solo net ₹{int(round(net)):,}"
        )

    if role == "anchor":
        return f"{label}{odds_s} · p={pct} · insurance · solo covers stake"
    if role == "support":
        return f"{label}{odds_s} · p={pct} · support · {mkt}"
    if role in ("swing", "main"):
        return f"{label}{odds_s} · p={pct} · main · {mkt}"
    if role in ("lottery", "lottery2"):
        return f"{label}{odds_s} · p={pct} · longshot · small stake"
    return f"{label}{odds_s} · p={pct}" + (f" · {mkt}" if mkt else "")


def explain_plan_card(
    legs: list[dict],
    *,
    home: str,
    away: str,
    budget: float,
    target: float,
    ctx: dict | None = None,
) -> str:
    del home, away, ctx
    n = len(legs)
    profit = target_profit_inr(budget, target)
    routes = [
        l for l in legs
        if (l.get("role") or "") in ("target_lotto", "stake_combo", "route")
        or l.get("hits_target")
    ]
    parts = [f"{n} tickets · budget ₹{int(budget):,} · profit goal ₹{int(round(profit)):,}"]
    if routes:
        route = routes[0]
        rp = route.get("our_probability_pct") or round(float(route.get("our_probability") or 0) * 100, 1)
        net = leg_net_if_solo_win(route, legs)
        parts.append(f"primary route p={rp}% solo net ₹{int(round(net)):,}")
    return " · ".join(parts)
