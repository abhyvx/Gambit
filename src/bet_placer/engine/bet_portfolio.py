"""Build 4 bet plans from all Stake-placeable markets.

User-facing tabs:
  - Loss-minimizing
  - One best bet
  - Value-for-money (risk worth taking)
  - Parlays

We still compute and return `bet_slips` for the UI slip-picker, but the
`strategies` dict is the source of truth for these 4 tabs.
"""

from __future__ import annotations

import math
from itertools import combinations

from bet_placer.engine.game_profile import is_generic_trap, profile_match
from bet_placer.engine.plain_language import payout_text

TARGET_MIN_STAKE = 20


def _ceil_stake_inr(need: float) -> float:
    """₹5 steps above platform min  -  avoids wasting deploy on ₹10 round-up."""
    return max(TARGET_MIN_STAKE, math.ceil(float(need) / 5) * 5)


def target_profit_inr(budget: float, target_cashout: float) -> float:
    """User goal is net profit (e.g. ₹700), not gross cashout (₹1000)."""
    return max(0.0, float(target_cashout) - float(budget))


def min_stake_for_profit(odds: float, profit: float, other_stakes: float = 0) -> float:
    """Stake so this ticket nets `profit` if it wins alone on a spread card."""
    o = max(float(odds or 0), 1.02)
    need = (float(profit) + float(other_stakes)) / (o - 1.0)
    return _ceil_stake_inr(need)


def leg_net_if_solo_win(leg: dict, legs: list[dict]) -> float:
    """Net INR if only this ticket wins (others lose their stakes)."""
    total = sum(float(l.get("stake_inr") or 0) for l in legs)
    st = float(leg.get("stake_inr") or 0)
    od = float(leg.get("odds") or 1)
    return st * od - total


def size_independent_route_stakes(
    odds_list: list[float],
    budget: float,
    profit: float,
    *,
    max_deploy_pct: float = 0.88,
) -> list[float] | None:
    """Stakes for separate singles  -  each leg nets `profit` if it alone wins."""
    if not odds_list:
        return None
    cap = budget * max_deploy_pct
    stakes = [float(TARGET_MIN_STAKE)] * len(odds_list)
    for _ in range(48):
        total = sum(stakes)
        if total > cap + 0.01:
            return None
        stable = True
        for i, raw_odds in enumerate(odds_list):
            other = total - stakes[i]
            need = min_stake_for_profit(float(raw_odds or 1), profit, other)
            if abs(need - stakes[i]) > 0.01:
                stable = False
            stakes[i] = need
        if stable:
            return stakes if sum(stakes) <= cap + 0.01 else None
    return stakes if sum(stakes) <= cap + 0.01 else None


def min_stake_break_even_solo(odds: float, other_stakes: float) -> float:
    """Min stake so net >= 0 if only this ticket wins (others lose)."""
    o = max(float(odds or 0), 1.02)
    need = float(other_stakes) / (o - 1.0)
    return _ceil_stake_inr(need)


def estimate_balanced_spread_stakes(
    anchor_odds: float,
    route_odds: float,
    target_profit: float,
) -> tuple[float, float] | None:
    """Anchor break-even + route sized for profit  -  same math as calibrate_spread_stakes."""
    a_odds = max(float(anchor_odds or 0), 1.02)
    r_odds = max(float(route_odds or 0), 1.02)
    anchor_stake = min_stake_break_even_solo(a_odds, 0)
    route_need = min_stake_for_profit(r_odds, target_profit, anchor_stake)
    anchor_stake = min_stake_break_even_solo(a_odds, route_need)
    route_need = min_stake_for_profit(r_odds, target_profit, anchor_stake)
    return anchor_stake, route_need


def fit_spread_stakes_to_budget(
    anchor_odds: float,
    route_odds: float,
    budget: float,
    target_profit: float,
    *,
    min_profit_pct: float = 0.85,
    allow_partial: bool = True,
) -> tuple[float, float] | None:
    """Scale anchor + route stakes to fit deploy cap while keeping max profit."""
    max_deploy = budget * 0.80
    est = estimate_balanced_spread_stakes(anchor_odds, route_odds, target_profit)
    if not est:
        return None
    anchor_stake, route_stake = est
    total = anchor_stake + route_stake
    if total > max_deploy and total > 0:
        scale = max_deploy / total
        anchor_stake = _ceil_stake_inr(anchor_stake * scale)
        route_stake = _ceil_stake_inr(route_stake * scale)
        if anchor_stake + route_stake > max_deploy:
            route_stake = max(TARGET_MIN_STAKE, max_deploy - anchor_stake)
            anchor_stake = max(TARGET_MIN_STAKE, max_deploy - route_stake)
    if anchor_stake + route_stake > max_deploy + 0.01:
        return None
    trial = [
        {"stake_inr": anchor_stake, "odds": anchor_odds, "role": "anchor"},
        {"stake_inr": route_stake, "odds": route_odds, "role": "target_lotto"},
    ]
    net = leg_net_if_solo_win(trial[1], trial)
    floor = target_profit * min_profit_pct
    if net < floor:
        route_stake = max(TARGET_MIN_STAKE, max_deploy - anchor_stake)
        trial[1]["stake_inr"] = route_stake
        net = leg_net_if_solo_win(trial[1], trial)
    if net < floor and allow_partial:
        soft = target_profit * 0.35
        if net >= soft:
            return anchor_stake, route_stake
        return None
    if net < floor * 0.70:
        return None
    return anchor_stake, route_stake


def max_tickets_for_budget(budget: float) -> int:
    """How many ₹20+ tickets fit in deploy budget (cap 20)."""
    deploy = budget * 0.85
    return min(20, max(1, int(deploy / TARGET_MIN_STAKE)))


def risk_budget_profile(budget: float, target_cashout: float, pool_size: int = 30) -> dict:
    """Riskier routes only when target is high and the market pool is thin."""
    mult = float(target_cashout) / max(float(budget), 1)
    thin_pool = pool_size < 18
    if mult < 2.5:
        return {
            "max_route_pct": 0.08,
            "min_route_prob": 0.14 if thin_pool else 0.16,
            "max_tickets": max_tickets_for_budget(budget),
            "allow_extra_sgm": False,
        }
    if mult < 4.0:
        return {
            "max_route_pct": 0.10,
            "min_route_prob": 0.09 if thin_pool else 0.10,
            "max_tickets": max_tickets_for_budget(budget),
            "allow_extra_sgm": True,
        }
    return {
        "max_route_pct": 0.18 if thin_pool else 0.15,
        "min_route_prob": 0.08,
        "max_tickets": max_tickets_for_budget(budget),
        "allow_extra_sgm": True,
    }


_INSURANCE_ROLES = frozenset({"anchor", "support", "main", "swing"})
_ROUTE_ROLES = frozenset({"target_lotto", "stake_combo", "route", "lottery", "lottery2"})


def _path_hits_profit_target(plan: dict, target_cashout: float | None = None) -> bool:
    """At least one swing ticket nets the profit goal if it wins alone."""
    legs = plan.get("legs") or []
    if not legs:
        return False
    tgt_cashout = float(
        target_cashout or plan.get("target_cashout_inr") or plan.get("target_return_inr") or 0
    )
    budget = float(
        plan.get("budget_inr")
        or (plan.get("reserve_inr") or 0) + (plan.get("total_stake_inr") or 0)
        or 300
    )
    profit = target_profit_inr(budget, tgt_cashout) if tgt_cashout > budget else plan.get("target_profit_inr")
    if not profit or profit <= 0:
        return False
    floor = float(profit) * 0.95
    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not routes:
        routes = [l for l in legs if l.get("hits_target")]
    return any(leg_net_if_solo_win(l, legs) >= floor for l in routes)


def calibrate_spread_stakes(
    legs: list[dict],
    budget: float,
    target_profit: float,
    *,
    target_cashout: float | None = None,
    pool_size: int = 30,
) -> list[dict]:
    """Balanced: anchor breaks even, swing sized to hit profit target if it wins."""
    if not legs:
        return legs
    max_deploy = budget * 0.80
    floor = target_profit * 0.95

    insurance = [l for l in legs if (l.get("role") or "") in _INSURANCE_ROLES]
    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not routes:
        return legs

    route = routes[0]
    anchor = next((l for l in insurance if l.get("role") == "anchor"), insurance[0] if insurance else None)
    support = [l for l in insurance if (l.get("role") or "") != "anchor"]

    odds_r = float(route.get("odds") or 1)
    if anchor:
        a_odds = float(anchor.get("odds") or 1)
        route_need = min_stake_for_profit(odds_r, target_profit, 0)
        anchor_stake = min_stake_break_even_solo(a_odds, route_need)
        route_need = min_stake_for_profit(odds_r, target_profit, anchor_stake)
        anchor_stake = min_stake_break_even_solo(a_odds, route_need)
        route_need = min_stake_for_profit(odds_r, target_profit, anchor_stake)
    else:
        anchor_stake = 0
        route_need = min_stake_for_profit(odds_r, target_profit, 0)

    if anchor_stake + route_need > max_deploy:
        if anchor:
            fitted = fit_spread_stakes_to_budget(
                float(anchor.get("odds") or 1), odds_r, budget, target_profit,
            )
            if fitted:
                anchor_stake, route_need = fitted
            else:
                partial = fit_spread_stakes_to_budget(
                    float(anchor.get("odds") or 1), odds_r, budget, target_profit,
                    min_profit_pct=0.35, allow_partial=True,
                )
                if partial:
                    anchor_stake, route_need = partial
                else:
                    anchor_stake = min(
                        min_stake_break_even_solo(float(anchor.get("odds") or 1), 0),
                        max(TARGET_MIN_STAKE, max_deploy * 0.35),
                    )
                    route_need = max(TARGET_MIN_STAKE, max_deploy - anchor_stake)
        elif route_need > max_deploy:
            route_need = max(TARGET_MIN_STAKE, max_deploy)
        if anchor_stake + route_need > max_deploy:
            route_need = max(TARGET_MIN_STAKE, max_deploy - anchor_stake)

    route["stake_inr"] = route_need
    if anchor:
        anchor["stake_inr"] = anchor_stake

    # Grow medium insurance from spare deploy  -  route stake rises with support, so iterate.
    for leg in support:
        leg["stake_inr"] = TARGET_MIN_STAKE
    for _ in range(48):
        support_stake = sum(float(l.get("stake_inr") or 0) for l in support)
        other = anchor_stake + support_stake
        route_need = min_stake_for_profit(odds_r, target_profit, other)
        route["stake_inr"] = route_need
        total = other + route_need
        if total > max_deploy + 0.01:
            break
        spare = max_deploy - total
        if spare < 5 or not support:
            break
        med = max(support, key=lambda l: float(l.get("our_probability") or 0))
        med["stake_inr"] = float(med.get("stake_inr") or 0) + 5

    support_stake = sum(float(l.get("stake_inr") or 0) for l in support)
    if anchor:
        a_odds = float(anchor.get("odds") or 1)
        for _ in range(24):
            other = route_need + support_stake
            need_anchor = min_stake_break_even_solo(a_odds, other)
            if need_anchor + other <= max_deploy + 0.01:
                anchor_stake = need_anchor
                break
            if route_need > TARGET_MIN_STAKE + 5:
                route_need = max(TARGET_MIN_STAKE, route_need - 10)
                route["stake_inr"] = route_need
                continue
            anchor_stake = max(TARGET_MIN_STAKE, max_deploy - other)
            break
        anchor["stake_inr"] = anchor_stake

    out = []
    if anchor:
        out.append(anchor)
    out.extend(l for l in support if float(l.get("stake_inr") or 0) >= TARGET_MIN_STAKE)
    out.append(route)

    for leg in out:
        st = float(leg.get("stake_inr") or 0)
        od = float(leg.get("odds") or 1)
        ret = round(st * od, 0)
        leg["return_inr"] = ret
        role = leg.get("role") or ""
        net = leg_net_if_solo_win(leg, out)
        if role in _ROUTE_ROLES:
            leg["partial_profit_route"] = net < floor
            leg["hits_target"] = net >= floor
            leg["payout_text"] = f"₹{int(st):,} → ₹{int(ret):,} if wins (+₹{int(round(net)):,} profit)"
        elif role in _INSURANCE_ROLES and net >= -5:
            leg["payout_text"] = f"₹{int(st):,} → ₹{int(ret):,} if wins (covers stake)"
        else:
            leg["payout_text"] = f"₹{int(st):,} → ₹{int(ret):,} if wins"

    return out


def annotate_leg_profit_flags(legs: list[dict], target_profit: float) -> None:
    """Mark profit route vs break-even insurance."""
    from bet_placer.markets.labels import format_solo_outcome_label

    floor = target_profit * 0.95
    for leg in legs:
        net = leg_net_if_solo_win(leg, legs)
        leg["profit_if_solo_inr"] = round(net, 0)
        role = leg.get("role") or ""
        is_insurance = role in _INSURANCE_ROLES
        is_route = role in _ROUTE_ROLES
        leg["breaks_even"] = (role == "anchor" or is_insurance) and net >= -5
        leg["hits_target"] = is_route and net >= floor
        leg["solo_outcome_label"] = format_solo_outcome_label(
            net,
            hits_target=leg.get("hits_target"),
            breaks_even=leg.get("breaks_even"),
        )


def polish_slip_legs(slip: dict, home: str, away: str, ctx: dict | None = None) -> dict:
    """Rebuild vague leg labels and attach solo-outcome text."""
    from bet_placer.engine.leg_explain import explain_leg, explain_plan_card
    from bet_placer.engine.match_card import path_label_from_legs
    from bet_placer.markets.labels import (
        format_combo_parts,
        format_solo_outcome_label,
        format_ticket_label,
    )

    legs = slip.get("legs") or []
    if not legs:
        return slip
    out = {**slip}
    human = ctx or slip.get("human_context") or {}
    budget = float(
        slip.get("budget_inr")
        or human.get("budget_inr")
        or (slip.get("total_stake_inr") or 0) + (slip.get("reserve_inr") or 0)
        or 300
    )
    target = float(slip.get("target_cashout_inr") or slip.get("target_return_inr") or human.get("target_cashout_inr") or 0)
    polished: list[dict] = []
    for leg in legs:
        pl = dict(leg)
        if pl.get("market") == "stake_combo" or pl.get("role") in ("stake_combo", "target_lotto"):
            try:
                from bet_placer.engine.card_coherence import decompose_stake_combo
                structured = decompose_stake_combo(pl, home, away)
                if len(structured) >= 2:
                    pl["combo_legs"] = structured
            except Exception:
                pass
            parts = format_combo_parts(pl, home, away)
            if parts:
                pl["combo_parts"] = parts
        pl["label"] = format_ticket_label(pl, home, away)
        net = leg_net_if_solo_win(pl, legs)
        pl["profit_if_solo_inr"] = round(net, 0)
        pl["solo_outcome_label"] = format_solo_outcome_label(
            net,
            hits_target=pl.get("hits_target"),
            breaks_even=pl.get("breaks_even"),
        )
        polished.append(pl)
    for pl in polished:
        pl["reason"] = explain_leg(
            pl,
            home=home,
            away=away,
            budget=budget,
            target_cashout=target,
            all_legs=polished,
            ctx=human,
        )
    out["legs"] = polished
    leg_names = [l["label"] for l in polished if l.get("label")]
    out["path_legs"] = leg_names
    pl = (out.get("path_label") or "").strip()
    if leg_names and (not pl or pl.startswith("") or "tickets ·" in pl):
        rebuilt = path_label_from_legs(polished)
        if rebuilt:
            out["path_label"] = rebuilt
    if out.get("plan_type") == "stake_combo" and polished:
        combo_lbl = polished[0].get("label", "")
        if combo_lbl:
            out["path_label"] = f"Stake SGM · {combo_lbl.split(' @ ')[0]}"
    if target > 0 and polished:
        profit_goal = target_profit_inr(budget, target)
        annotate_leg_profit_flags(polished, profit_goal)
        out["why"] = explain_plan_card(polished, home=home, away=away, budget=budget, target=target, ctx=human)
        out["pick_reason"] = out["why"]
    return out

# ── Intuitive win-chance tiers (we never treat 50% as “good enough to bet”) ──
COMFORTABLE_WIN = 0.56       # minimum “I’d consider this”  -  clearly better than a coin flip
CONFIDENT_WIN = 0.62         # loss-min tab  -  genuinely safer side
STRONG_WIN = 0.68            # very high confidence label

# ── Loss-min tab: preserve capital first (NOT profit-max) ──
LOSS_MIN_LEG_MIN_PROB = CONFIDENT_WIN       # 62%+ per leg in a spread
LOSS_MIN_SINGLE_MIN_PROB = STRONG_WIN         # singles only at 68%+ confidence
LOSS_MIN_SPREAD_MAX_RISK_PCT = 0.28           # deploy ≤28% across spread legs
LOSS_MIN_SPREAD_MIN_RESERVE_PCT = 0.72        # keep ≥72% untouched
LOSS_MIN_SINGLE_MAX_STAKE_PCT = 0.18          # confident single: tiny stake
LOSS_MIN_SINGLE_MIN_RESERVE_PCT = 0.82        # keep ≥82% if we dare use a single
LOSS_MIN_MIN_EV = -0.01                       # tiny -EV ok if it protects bankroll

SINGLE_MIN_PROB = 0.54          # one best bet: still solid, but don't hide every prop/angle
SINGLE_MIN_EV = 0.0
SINGLE_ALIGN_MIN_PROB = 0.62    # only force-align singles to a situational pick if it's this confident

VALUE_MIN_PROB = 0.55               # every market: majority chance before "value"
VALUE_MIN_EV = 0.02

PARLAY_MIN_LEG = 0.52
PARLAY_MIN_COMBINED = 0.12
PARLAY_MAX_LEGS = 4
MAX_OPTIONS_PER_TAB = 12
MAX_CURATED_ALTS = 10
MAX_MATCH_CARD_PATHS = 18
MAX_STAKE_SGM_PER_SLIP = 8

ALL_MARKETS = frozenset({
    "match_winner", "double_chance", "draw_no_bet",
    "over_under_goals", "btts", "asian_handicap",
    "corners", "cards", "player_goal",
    "half_time", "exact_score", "team_prop", "team_first_goal",
})
CORE_MARKETS = frozenset({
    "match_winner", "double_chance", "draw_no_bet",
    "over_under_goals", "btts", "asian_handicap",
    "corners", "cards", "half_time", "team_first_goal",
})


def build_portfolios(
    options: list,
    budget_inr: float,
    home: str,
    away: str,
    live_h2h_odds: bool = True,
    match=None,
    probabilities=None,
    human_context: dict | None = None,
) -> dict:
    profile = profile_match(match, probabilities or [], human_context or {}) if match else {
        "style": "balanced", "narrative": "", "min_bet_probability": LOSS_MIN_LEG_MIN_PROB,
    }

    from bet_placer.engine.stake_odds import (
        hydrate_stake_context,
        reprice_options_from_overlay,
        stake_lines_usable,
    )
    ctx = hydrate_stake_context(human_context or {}, home, away)
    overlay = ctx.get("stake_overlay")

    board_stake = ctx.get("_board_source") == "stake" and bool(ctx.get("_flat_board"))
    stake_only = stake_lines_usable(overlay, ctx)
    if overlay and stake_only:
        reprice_options_from_overlay(options, overlay, home, away)

    if not ctx.get("betting_style"):
        try:
            from bet_placer.portfolio.store import get_portfolio_profile
            prof = get_portfolio_profile() or {}
            ctx = {
                **ctx,
                "betting_style": {
                    "prefers_spread_singles": prof.get("prefers_spread_singles", True),
                    "avoid_parlays": prof.get("avoid_parlays", False),
                    "avg_bets_per_fixture": prof.get("avg_bets_per_fixture", 4),
                    "avg_stake_value": prof.get("avg_stake_value"),
                    "summary": prof.get("summary"),
                },
            }
        except Exception:
            pass
    ctx = {**ctx, "_all_options": options}
    target_cashout = float(ctx.get("target_cashout_inr") or max(budget_inr * 2.5, budget_inr + 500))
    target_profit = target_profit_inr(budget_inr, target_cashout)
    ctx = {**ctx, "target_cashout_inr": target_cashout, "target_profit_inr": target_profit}

    # Main match cards choose structure per match — ignore Settings goal/risk/structure.
    comfort = float(COMFORTABLE_WIN)
    comfort = max(0.50, min(0.68, comfort))
    ctx = {**(ctx or {}), "betting_style": None}

    pool = (
        _stake_pool(options, overlay, stake_only, home, away, ctx=ctx)
        if stake_only else
        _model_pool(options, home, away, ctx=ctx)
    )
    # Stake catalog empty/partial (1X2 only, props closed) → still recommend from model.
    # Placeability: UI/slip should only add lines Stake lists; probs stay model-learned.
    if not pool and stake_only:
        pool = _model_pool(options, home, away, ctx=ctx)
        stake_only = False
        ctx = {**ctx, "_stake_markets_pending": True}
    if not pool:
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = "No markets clear our filters for this game."
        empty["skip_recommended"] = True
        return _portfolio_result(empty, [], profile, stake_only, live_h2h_odds, skip_recommended=True, home=home, away=away)

    strategy_plans = {
        "match_card": _build_match_card_alternatives(
            pool, budget_inr, profile, home, away, stake_only, human_context=ctx,
            match=match, probabilities=probabilities,
        ),
        "min_loss": _build_min_loss_alternatives(
            pool, budget_inr, profile, home, away, stake_only, human_context=ctx,
        ),
    }
    used = _used_keys_from_plans(strategy_plans)

    strategy_plans["singles_focus"] = _build_single_alternatives(
        pool, budget_inr, profile, home, away, stake_only, exclude_keys=used,
        human_context=ctx,
    )
    used |= _used_keys_from_plans({"s": strategy_plans["singles_focus"]})

    strategy_plans["value"] = _build_value_alternatives(
        pool, budget_inr, profile, home, away, stake_only, exclude_keys=used,
    )
    used |= _used_keys_from_plans({"s": strategy_plans["value"]})

    strategy_plans["smart_parlay"] = _build_parlay_alternatives(
        pool, budget_inr, profile, stake_only,
        exclude_keys=set(),
        overlay=overlay,
        home=home,
        away=away,
        human_context=ctx,
    )

    for tab in list(strategy_plans.keys()):
        strategy_plans[tab] = [
            polish_slip_legs(s, home, away, ctx) for s in (strategy_plans.get(tab) or [])
        ]

    strategy_plans = _diversify_tab_plans(strategy_plans, home, away)

    from bet_placer.engine.card_coherence import filter_plans_by_thesis, plan_fights_match_thesis, plans_contradict

    thesis = ctx.get("match_thesis") or {}
    anchor = _pick_thesis_anchor(strategy_plans, ctx, home, away, profile)
    if anchor:
        ctx = {**ctx, "_thesis_anchor": anchor}
    for tab in list(strategy_plans.keys()):
        original = strategy_plans.get(tab) or []
        filtered = filter_plans_by_thesis(original, anchor, thesis, home, away)
        if not filtered and thesis:
            filtered = filter_plans_by_thesis(original, None, thesis, home, away)
        if filtered:
            # Never soft-restore plans that fight the match lean (e.g. Draw vs home)
            clean = [
                p for p in filtered
                if not plan_fights_match_thesis(p, thesis, home, away)
            ]
            strategy_plans[tab] = clean if clean else (
                [anchor] if anchor and tab == "match_card" else []
            )
        elif anchor and tab == "match_card":
            strategy_plans[tab] = [anchor]
        elif original:
            from bet_placer.engine.card_coherence import path_is_coherent
            coherent = [
                p for p in original
                if path_is_coherent(p.get("legs") or [], home, away)
                and (not anchor or not plans_contradict(anchor, p, home, away))
            ]
            strategy_plans[tab] = coherent[:MAX_OPTIONS_PER_TAB] if coherent else original[:1]

    caution, caution_reason = _assess_match_caution(strategy_plans)
    curated = _curate_picks(strategy_plans, home=home, away=away, ctx=ctx)
    primary = curated.get("primary")
    if primary:
        for tab in list(strategy_plans.keys()):
            strategy_plans[tab] = [
                p for p in (strategy_plans.get(tab) or [])
                if p is primary or not plans_contradict(primary, p, home, away)
            ]

    if _should_skip_match(strategy_plans, comfort=comfort) and not curated.get("primary"):
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = caution_reason or (
            "We checked spreads, singles, and parlays  -  nothing clears our bar. "
            "Keep your full budget for this game."
        )
        empty["skip_recommended"] = True
        return _portfolio_result(
            empty, [], profile, stake_only, live_h2h_odds,
            skip_recommended=True, skip_reason=empty["why"],
            strategies=strategy_plans, curated_picks=curated,
            home=home, away=away,
        )

    bet_slips = [
        plans[0]
        for key in ("match_card", "min_loss", "singles_focus", "value", "smart_parlay")
        for plans in [strategy_plans.get(key, [])]
        if plans
    ]

    have_non_parlay = any(
        strategy_plans.get(k) for k in ("match_card", "min_loss", "singles_focus", "value")
    )
    if not have_non_parlay:
        # Still surface combo / model lean rather than hard SKIP
        if strategy_plans.get("smart_parlay"):
            bet_slips = list(strategy_plans["smart_parlay"][:1])
        else:
            empty = _empty("skip", "Skip this match", budget_inr, profile)
            empty["why"] = "No singles or coverage clear our filters for this game."
            empty["skip_recommended"] = True
            return _portfolio_result(
                empty, [], profile, stake_only, live_h2h_odds,
                skip_recommended=True, skip_reason=empty["why"],
                strategies=strategy_plans, curated_picks=curated,
                home=home, away=away,
            )

    bet_slips = [s for s in bet_slips if _slip_ev(s) >= -8]
    if not bet_slips:
        # Keep best available plan even if EV is soft  -  don't blank the board.
        for key in ("match_card", "min_loss", "singles_focus", "value", "smart_parlay"):
            for p in strategy_plans.get(key) or []:
                if p.get("legs"):
                    bet_slips = [p]
                    break
            if bet_slips:
                break
    if not bet_slips:
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = "No priced markets cleared filters for this game."
        empty["skip_recommended"] = True
        return _portfolio_result(
            empty, [], profile, stake_only, live_h2h_odds,
            skip_recommended=True, skip_reason=empty["why"],
            strategies=strategy_plans, curated_picks=curated,
            home=home, away=away,
        )

    recommended = curated.get("primary") or _pick_recommended_slip(bet_slips, budget_inr, profile)
    if recommended.get("id") == "skip" or recommended.get("tab_id") == "skip":
        return _portfolio_result(
            recommended,
            [],
            profile,
            stake_only,
            live_h2h_odds,
            strategies=strategy_plans,
            skip_recommended=True,
            skip_reason=recommended.get("why") or caution_reason,
            home=home, away=away,
        )
    rec_likely = _likely_profit(recommended)
    if rec_likely < 0:
        caution = True
        caution_reason = (
            caution_reason
            or "Our top pick still loses on the most common outcome  -  skip or pick a different tab."
        )
    return _portfolio_result(
        recommended,
        bet_slips,
        profile,
        stake_only,
        live_h2h_odds,
        strategies=strategy_plans,
        skip_recommended=caution,
        skip_reason=caution_reason,
        curated_picks=curated,
        home=home, away=away,
    )


def _portfolio_result(recommended, bet_slips, profile, stake_only, live_h2h_odds, strategies=None, skip_recommended=False, skip_reason=None, curated_picks=None, home: str = "", away: str = ""):
    rec = recommended if isinstance(recommended, dict) and recommended.get("legs") else (bet_slips[0] if bet_slips else recommended)
    rec_id = rec.get("tab_id") or rec.get("id", "min_loss")
    using_model_only = not stake_only
    effective_rec_id = rec_id
    has_plan = bool(bet_slips) or (isinstance(recommended, dict) and bool(recommended.get("legs")))
    # Hard SKIP only when the recommended plan is literally "skip" and nothing else to show
    effective_skip = (rec_id == "skip" and not has_plan) or (
        bool(skip_recommended) and rec_id == "skip" and not has_plan
    )
    if using_model_only and effective_rec_id == "skip" and has_plan:
        effective_rec_id = "match_card"
        effective_skip = False
    if using_model_only and effective_rec_id == "skip":
        effective_rec_id = "match_card"
    strat = strategies or {
        "match_card": [rec] if rec.get("legs") else [],
        "min_loss": [rec] if rec.get("legs") else [],
        "singles_focus": [],
        "value": [],
        "smart_parlay": [],
    }
    # Legacy single-object views (first option per tab)
    legacy = {
        key: (_first_plan(strat, key) or _empty(key, key, 0, profile))
        for key in ("match_card", "min_loss", "singles_focus", "value", "smart_parlay")
    }
    skip_reason = skip_reason or (
        (recommended.get("why") if isinstance(recommended, dict) else None)
        if effective_skip else None
    ) or (
        "Nothing here wins on the typical outcome  -  skip this match or try Hit target for a swing path."
        if effective_skip else None
    )
    return {
        "recommended_strategy": effective_rec_id if effective_rec_id in ("match_card", "min_loss", "safe", "singles_focus", "value", "smart_parlay", "skip") else "singles_focus",
        "recommended_slip_id": rec.get("option_id") or rec.get("id"),
        "skip_recommended": effective_skip,
        "skip_reason": None if using_model_only else skip_reason,
        "game_profile": profile,
        "stake_only": stake_only,
        "bet_slips": bet_slips,
        "alternative_slips": [s for s in bet_slips if s.get("option_id") != rec.get("option_id")],
        "strategies": {
            **legacy,
            **strat,
            "hedged": legacy.get("min_loss", rec),
            "safe_only": legacy.get("singles_focus", rec),
            "parlay_only": legacy.get("smart_parlay", _empty("smart_parlay", "Parlay", 0, profile)),
        },
        "strategy_plans": strat,
        "curated_picks": curated_picks or _curate_picks(strat, home=home, away=away),
        "portfolio_engine": "match_card_v1",
        "odds_note": (
            "Each slip uses only markets Stake lists for this game, at Stake's real prices."
            if stake_only else
            "Model odds only  -  open the Odds tab to connect Stake and verify every pick before betting."
        ),
        "live_h2h_odds": live_h2h_odds,
    }


def _first_plan(strategies: dict, key: str) -> dict | None:
    raw = strategies.get(key)
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw if raw and raw.get("legs") else None


def _annotate_slip(slip: dict, tab_id: str, option_index: int, *, recommended: bool = False) -> dict:
    legs = slip.get("legs") or []
    is_stake_sgm = (
        slip.get("slip_type") == "stake_sgm"
        or slip.get("verified_stake")
        or slip.get("plan_type") == "stake_combo"
    )
    is_parlay = slip.get("id") == "parlay" or (is_stake_sgm and tab_id == "smart_parlay")
    n = len(legs)
    if is_stake_sgm and (tab_id == "smart_parlay" or slip.get("plan_type") == "stake_combo"):
        slip_type, slip_type_label = "stake_sgm", "Stake combo · verified"
    elif is_parlay:
        slip_type, slip_type_label = "parlay", "Stake combo · verified"
    elif slip.get("plan_type") == "single" or (slip.get("slip_type") == "single" and n <= 1):
        slip_type, slip_type_label = "single", "Single bet · 1 pick"
    elif slip.get("plan_type") == "coverage":
        slip_type, slip_type_label = "spread_card", f"Coverage · {n} routes"
    elif tab_id == "match_card" or slip.get("slip_type") == "spread_card":
        combos_n = sum(1 for l in legs if l.get("role") == "stake_combo" or l.get("market") == "stake_combo")
        singles_n = n - combos_n
        slip_type = "spread_card"
        if combos_n and singles_n:
            slip_type_label = f"Match card · {singles_n} singles + {combos_n} combo"
        elif combos_n == 1 and singles_n == 0:
            slip_type, slip_type_label = "stake_sgm", "Stake combo · verified"
        else:
            slip_type_label = f"Match card · {n} separate singles"
    elif tab_id == "min_loss":
        slip_type, slip_type_label = "spread", f"Spread · {n} safe bets"
    elif n <= 1:
        slip_type, slip_type_label = "single", "Single bet · 1 pick"
    else:
        slip_type, slip_type_label = "multi", f"Multi-leg · {n} bets"

    out = {**slip}
    out["tab_id"] = tab_id
    out["option_index"] = option_index
    out["option_id"] = f"{tab_id}_{option_index}"
    out["id"] = tab_id
    out["slip_type"] = slip_type
    out["slip_type_label"] = slip_type_label
    out["leg_count"] = n
    out["is_recommended_option"] = recommended and option_index == 1
    out["option_label"] = (
        f"Option {option_index} · {slip.get('path_label') or 'Recommended'}"
        if recommended and option_index == 1
        else f"Option {option_index} · {slip.get('path_label') or 'Alternative path'}"
    )
    leg_names = [l.get("label", "") for l in legs if l.get("label")]
    out["path_legs"] = leg_names
    pl = (slip.get("path_label") or "").strip()
    # option_summary only when path_label is a short thesis name, not the full ticket list
    if leg_names and pl and "tickets ·" not in pl and not pl.startswith(""):
        out["option_summary"] = ", ".join(leg_names[:3]) + (
            f" +{len(leg_names) - 3} more" if len(leg_names) > 3 else ""
        )
    else:
        out["option_summary"] = ""
    if not pl and leg_names:
        from bet_placer.engine.match_card import path_label_from_legs
        out["path_label"] = path_label_from_legs(legs)
    if legs:
        hp = slip.get("hit_probability")
        if hp and slip.get("plan_type") in ("stake_combo", "single", "coverage"):
            out["win_probability_pct"] = round(float(hp) * 100, 1)
        else:
            out["win_probability_pct"] = round(_best_win_prob(out) * 100, 1)
        out["confidence_label"] = _confidence_label(out["win_probability_pct"] / 100.0)
    return out


def _likely_profit(slip: dict) -> float:
    sc = slip.get("scenarios") or {}
    return float((sc.get("likely_case") or {}).get("profit_inr", -999))


def _slip_budget(slip: dict) -> float:
    stake = float(slip.get("total_stake_inr") or 0)
    reserve = float(slip.get("reserve_inr") or 0)
    total = stake + reserve
    return total if total > 0 else max(stake, reserve, 1.0)


def _comfortable_typical(slip: dict, max_loss_pct: float = 0.40) -> bool:
    """Typical outcome should not lose more than max_loss_pct of match budget."""
    return _likely_profit(slip) >= -max_loss_pct * _slip_budget(slip)


def _plan_is_spread_style(plan: dict) -> bool:
    """True for 3+ separate tickets  -  the user's actual betting style."""
    legs = plan.get("legs") or []
    ptype = plan.get("plan_type") or ""
    if ptype == "single" or len(legs) < 3:
        return False
    if ptype == "match_card":
        return True
    if ptype == "coverage" and plan.get("placement_mode") == "separate_singles":
        return len(legs) >= 3
    return len(legs) >= 3


def _plan_from_spread_slip(slip: dict, target: float) -> dict | None:
    """Convert build_match_card_slip output into a target planner plan."""
    from bet_placer.engine.match_card import path_label_from_legs

    legs = slip.get("legs") or []
    if len(legs) < 2:
        return None
    singles = [l for l in legs if l.get("role") != "stake_combo"]
    combos = [l for l in legs if l.get("role") == "stake_combo"]
    label = f"Match card · {len(singles)} separate singles"
    if combos:
        label += f" + {len(combos)} Stake combo"
    path_label = slip.get("path_label") or path_label_from_legs(legs) or label
    return {
        "plan_type": "match_card",
        "plan_type_label": label,
        "name": slip.get("name") or " Your match card",
        "description": slip.get("description") or "",
        "why": slip.get("why") or "",
        "path_headline": path_label,
        "path_label": path_label,
        "path_thesis": slip.get("path_thesis"),
        "legs": legs,
        "total_stake_inr": slip.get("total_stake_inr"),
        "reserve_inr": slip.get("reserve_inr"),
        "target_return_inr": target,
        "target_cashout_inr": target,
        "target_profit_inr": slip.get("target_profit_inr") or round(target - (slip.get("total_stake_inr") or 0) - (slip.get("reserve_inr") or 0), 0),
        "hit_probability": float(slip.get("hit_probability") or 0),
        "hit_probability_pct": round(float(slip.get("hit_probability") or 0) * 100, 1),
        "scenarios": slip.get("scenarios") or {},
        "placement_mode": "separate_singles",
        "expected_value_inr": (slip.get("scenarios") or {}).get("expected_value_inr", 0),
    }


def _stern_primary_eligible(slip: dict) -> bool:
    """Top rec bar  -  safer paths only, not swing/lotto-heavy cards."""
    if not _target_rec_eligible(slip):
        return False
    legs = slip.get("legs") or []
    hp = float(slip.get("hit_probability") or 0)
    likely = _likely_profit(slip)
    budget = max(_slip_budget(slip), 1)
    anchor_probs = [
        float(l.get("our_probability") or 0)
        for l in legs
        if l.get("role") in ("anchor", "support", "main", "swing")
    ]
    best_anchor = max(anchor_probs, default=0)
    best_leg = max((float(l.get("our_probability") or 0) for l in legs), default=0)
    lotto_n = sum(
        1 for l in legs
        if l.get("role") in ("target_lotto", "lottery", "lottery2", "big_lotto")
    )
    wl = (slip.get("worth_label") or "").lower()

    if hp < 0.16 and best_leg < 0.54:
        return False
    if likely < -0.35 * budget:
        return False
    if lotto_n >= 2 and hp < 0.22:
        return False
    if "swing path" in wl and hp < 0.22:
        return False
    if best_anchor < 0.48 and hp < 0.18:
        return False
    return True


def _profit_route_quality(p: dict) -> int:
    """Prefer likely profit routes  -  never raw payout."""
    legs = p.get("legs") or []
    route = next(
        (
            l for l in legs
            if (l.get("role") or "") in _ROUTE_ROLES or l.get("hits_target")
        ),
        None,
    )
    if not route:
        return 0
    prob = float(route.get("our_probability") or 0)
    if prob >= 0.14:
        return 4
    if prob >= 0.11:
        return 2
    if prob >= 0.08:
        return 0
    return -3


def _core_market_score(slip: dict) -> int:
    """Prefer 1X2 / ML / DNB / OU / BTTS / AH  -  demote cards/corners props as top rec."""
    core = {
        "match_winner", "double_chance", "draw_no_bet", "over_under_goals",
        "btts", "asian_handicap", "h2h", "moneyline",
    }
    niche = {"cards", "corners", "player_goal", "team_first_goal", "half_time", "situation"}
    legs = slip.get("legs") or []
    if not legs:
        return 0
    c = sum(1 for l in legs if str(l.get("market") or "").lower() in core)
    n = sum(1 for l in legs if str(l.get("market") or "").lower() in niche)
    return c * 3 - n * 4


def _stern_rec_rank(p: dict) -> tuple:
    """Higher = safer / better top rec."""
    hp = float(p.get("hit_probability") or 0)
    likely = _likely_profit(p)
    budget = max(_slip_budget(p), 1)
    tab = p.get("tab_id") or p.get("id") or ""
    legs = p.get("legs") or []
    anchor_p = max(
        (float(l.get("our_probability") or 0) for l in legs if l.get("role") in ("anchor", "support", "main", "swing")),
        default=0,
    )
    lotto_n = sum(1 for l in legs if l.get("role") in ("target_lotto", "lottery", "lottery2", "big_lotto"))
    tgt = p.get("target_cashout_inr") or p.get("target_return_inr")
    n_legs = len(legs)
    spread_bonus = 0
    return (
        _core_market_score(p),
        spread_bonus,
        _profit_route_quality(p),
        anchor_p,
        hp,
        1 if _path_hits_profit_target(p, tgt) else 0,
        1 if _card_has_target_route(p, tgt) else 0,
        1 if _stern_primary_eligible(p) else 0,
        1 if tab == "min_loss" else 0,
        1 if tab == "singles_focus" else 0,
        1 if anchor_p >= CONFIDENT_WIN else 0,
        hp,
        likely / budget,
        -lotto_n,
    )


def _target_rec_eligible(slip: dict) -> bool:
    """Target paths for Recs  -  balanced spread with a route to the cashout goal."""
    tab = slip.get("tab_id") or slip.get("id") or ""
    if tab != "match_card":
        return False
    legs = slip.get("legs") or []
    if not legs:
        return False
    target = slip.get("target_cashout_inr") or slip.get("target_return_inr")
    if len(legs) == 1 and _path_hits_profit_target(slip, target):
        leg = legs[0]
        if leg.get("market") == "player_goal":
            return False
        if float(leg.get("our_probability") or 0) < 0.08:
            return False
        return leg.get("market") == "stake_combo" or (leg.get("role") or "") in _ROUTE_ROLES
    if len(legs) < 2:
        return False
    if not (_path_hits_profit_target(slip, target) or _card_has_partial_route(slip, target)):
        return False
    if len(legs) == 1:
        return False
    insurance = [l for l in legs if (l.get("role") or "") in _INSURANCE_ROLES]
    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not (insurance and routes):
        return False
    route = routes[0]
    if route.get("market") == "player_goal":
        return False
    if float(route.get("our_probability") or 0) < 0.10:
        return False
    return True


def _primary_rec_candidate(slip: dict) -> bool:
    """Everyday singles/spreads  -  typical outcome must not bleed too much of the budget."""
    tab = slip.get("tab_id") or slip.get("id") or ""
    if tab == "match_card":
        return _target_rec_eligible(slip)
    return _comfortable_typical(slip)


def _is_realistic_slip(slip: dict) -> bool:
    """Drop paths that aren't worth showing  -  relaxed for target-sized plans."""
    legs = slip.get("legs") or []
    if not legs:
        return False
    tab = slip.get("tab_id") or slip.get("id") or ""
    if tab == "match_card":
        target = slip.get("target_cashout_inr") or slip.get("target_return_inr")
        if _path_hits_profit_target(slip, target):
            return True
        if len(legs) < 2:
            return False
        return _card_has_balanced_spread(slip)
    if slip.get("worth_taking") and slip.get("target_cashout_inr"):
        if _likely_profit(slip) < -40:
            return False
        return True
    if _likely_profit(slip) < -15:
        return False
    core_probs = [
        float(l.get("our_probability") or 0)
        for l in legs
        if l.get("role") in ("anchor", "support", "main", "swing")
    ]
    if len(legs) > 1 and core_probs and max(core_probs) < 0.50:
        return False
    if len(legs) > 1 and tab != "match_card" and not any(float(l.get("our_probability") or 0) >= 0.52 for l in legs):
        return False
    lottery_n = sum(
        1 for l in legs
        if l.get("role") in ("lottery", "lottery2", "big_lotto", "target_lotto")
    )
    if lottery_n > 2 and tab == "match_card":
        return False
    if tab == "smart_parlay":
        p = slip.get("combined_probability") or _best_win_prob(slip)
        if p < PARLAY_MIN_COMBINED:
            return False
    return True


def _pick_reason_text(slip: dict) -> str:
    tab = slip.get("tab_id") or slip.get("id") or ""
    likely = _likely_profit(slip)
    win_pct = round(_best_win_prob(slip) * 100)
    if tab == "singles_focus":
        leg = (slip.get("legs") or [{}])[0]
        pct = leg.get("our_probability_pct") or win_pct
        return f"Clearest single, about {pct}% to win. Typical result {format_inr(likely)}."
    if tab == "match_card":
        from bet_placer.engine.leg_explain import explain_plan_card

        legs = slip.get("legs") or []
        target = float(slip.get("target_cashout_inr") or slip.get("target_return_inr") or 0)
        if legs and target > 0:
            return explain_plan_card(
                legs,
                home=slip.get("home_team") or "",
                away=slip.get("away_team") or "",
                budget=_slip_budget(slip),
                target=target,
                ctx=slip.get("human_context") or {},
            )
        headline = slip.get("path_label") or slip.get("path_headline") or slip.get("name") or ""
        wl = slip.get("worth_label") or ""
        n = len(legs)
        hits = any(l.get("hits_target") for l in legs)
        tier = wl.split(" · ")[0] if wl else ""
        if n >= 3:
            base = f"{n} separate tickets, budget spread across the card"
            if hits and target:
                base += f", sized toward {format_inr(target)}"
            if tier and headline:
                return f"{tier}: {headline}"
            return base
        if headline and tier:
            return f"{tier}: {headline}"
        if wl:
            return wl.replace("—", ",").replace(" - ", ",").replace("~", "")
        if hits and target:
            return f"Sized for {format_inr(target)} if one ticket wins alone"
        return f"Target spread, about {win_pct}% any line helps. Typical {format_inr(likely)}."
    if tab == "min_loss":
        reserve = slip.get("reserve_inr") or 0
        return f"Preserve bankroll, {format_inr(reserve)} kept. Safer legs only."
    if tab == "smart_parlay":
        return f"Verified Stake combo, about {win_pct}% combined win chance"
    if tab == "value":
        return f"Higher payout angle, +EV swing, about {win_pct}% win chance"
    return (slip.get("why") or "")[:160]


def _annotate_curated(slip: dict | None, label: str, *, recommended: bool = False) -> dict | None:
    if not slip or not slip.get("legs"):
        return None
    tab = slip.get("tab_id") or slip.get("id") or ""
    type_labels = {
        "match_card": "Target combo",
        "singles_focus": "Single bet",
        "min_loss": "Safe spread",
        "value": "Value play",
        "smart_parlay": "Stake combo",
    }
    out = {
        **slip,
        "pick_label": label,
        "pick_type": type_labels.get(tab, "Bet plan"),
        "pick_reason": _pick_reason_text(slip),
        "is_recommended_option": recommended,
    }
    # Prefer the match-shape note when we chose this approach deliberately
    if recommended and slip.get("rec_shape_note"):
        out["pick_reason"] = slip["rec_shape_note"]
        out["worth_label"] = slip.get("worth_label") or slip["rec_shape_note"]
    return out


def _plans_contradict(primary: dict, alt: dict, home: str, away: str) -> bool:
    """Curated alt must not fight the primary thesis unless explicitly a hedge."""
    if alt.get("is_hedge"):
        return False
    from bet_placer.engine.card_coherence import plans_contradict
    return plans_contradict(primary, alt, home, away)


def _pick_thesis_anchor(
    strategy_plans: dict,
    ctx: dict,
    home: str,
    away: str,
    profile: dict,
) -> dict | None:
    """Best thesis-aligned plan  -  drives what every tab is allowed to show."""
    from bet_placer.engine.card_coherence import path_is_coherent, plan_aligns_match_thesis

    thesis = ctx.get("match_thesis") or {}
    best: dict | None = None
    best_score = -1e9
    for tab in ("match_card", "smart_parlay", "singles_focus", "min_loss", "value"):
        for p in strategy_plans.get(tab) or []:
            if not _is_realistic_slip(p):
                continue
            legs = p.get("legs") or []
            if not legs or not path_is_coherent(legs, home, away):
                continue
            if thesis and not plan_aligns_match_thesis(p, thesis, home, away, slack=True):
                continue
            score = 0.0
            score += 50
            score += _profit_route_quality(p) * 8
            score += _best_win_prob(p) * 25
            score += float(p.get("worth_score") or 0) * 0.5
            if _path_hits_profit_target(p, p.get("target_cashout_inr")):
                score += 20
            labels = {
                (x.get("label") or "").lower()
                for x in (ctx.get("unified_picks") or []) + (ctx.get("easy_money_picks") or [])
            }
            for leg in legs:
                if (leg.get("label") or "").lower() in labels:
                    score += 12
            read = ctx.get("analyst_read") or {}
            for angle in (read.get("angles") or [])[:5]:
                al = (angle.get("selection") or "").lower()
                for leg in legs:
                    if al and al in (leg.get("label") or "").lower():
                        score += 10
            if score > best_score:
                best_score = score
                best = p
    return best


def _match_rec_shape(ctx: dict | None, thesis: dict | None) -> str:
    """Decide the best Recs approach for THIS fixture — not a global template.

    Returns one of: single | spread | sgm | caution
    Policy (user): prefer a high-confidence single when it fits; otherwise pick
    whatever the match actually supports (spread / SGM / caution).
    """
    ctx = ctx or {}
    thesis = thesis or {}
    profile = ctx.get("game_profile") or {}
    conf = (thesis.get("confidence") or {}) if isinstance(thesis.get("confidence"), dict) else {}
    tier = str(conf.get("tier") or "").lower()
    fav_pct = float(thesis.get("favorite_pct") or 0) / 100.0
    draw_scenario = bool(thesis.get("draw_scenario"))
    result_dir = thesis.get("result_dir")
    rating_gap = abs(float(profile.get("rating_gap") or 0))

    # Clear favourite on quality + model — single is the right default
    if result_dir and (fav_pct >= CONFIDENT_WIN or (fav_pct >= COMFORTABLE_WIN and rating_gap >= 12)):
        return "single"
    if result_dir and fav_pct >= STRONG_WIN:
        return "single"
    if tier in ("lock", "strong") and result_dir:
        return "single"
    if result_dir and fav_pct >= COMFORTABLE_WIN:
        return "single"

    # Tight / draw-live: don't force a match-winner single
    if draw_scenario or tier in ("coinflip", "coin-flip", "coin_flip"):
        return "spread"

    # Thin board / no lean — caution (only show something with real conviction)
    if not result_dir and rating_gap < 6 and fav_pct < COMFORTABLE_WIN:
        return "caution"
    if not result_dir and fav_pct < COMFORTABLE_WIN:
        return "spread"

    return "spread"


def _curate_picks(strategy_plans: dict, *, home: str = "", away: str = "", ctx: dict | None = None) -> dict:
    """Primary = match-discretion pick. Prefer high-p singles when suited; else spread/SGM."""
    from bet_placer.engine.card_coherence import plan_aligns_match_thesis, plan_fights_match_thesis

    ctx = ctx or {}
    thesis = ctx.get("match_thesis") or {}
    shape = _match_rec_shape(ctx, thesis)

    def _candidates(tab: str, pred=None) -> list[dict]:
        out = []
        for p in strategy_plans.get(tab) or []:
            if not _is_realistic_slip(p):
                continue
            if pred and not pred(p):
                continue
            if thesis and not plan_aligns_match_thesis(p, thesis, home, away, slack=True):
                continue
            if thesis and plan_fights_match_thesis(p, thesis, home, away):
                continue
            out.append(p)
        return out

    def _sort_tab(tab: str, cands: list[dict]) -> list[dict]:
        if tab == "singles_focus":
            # Conviction first, then EV — user wants high-confidence singles when suited
            cands.sort(
                key=lambda s: (_best_win_prob(s), _likely_profit(s), _weighted_slip_score(s)),
                reverse=True,
            )
        elif tab == "min_loss":
            cands.sort(key=lambda s: (_likely_profit(s), *_loss_preservation_score(s)), reverse=True)
        elif tab == "match_card":
            cands.sort(key=_stern_rec_rank, reverse=True)
        else:
            cands.sort(key=lambda s: (_best_win_prob(s), _likely_profit(s), _weighted_slip_score(s)), reverse=True)
        return cands

    # Shape → ordered approaches for THIS match (not a fixed global template)
    if shape == "single":
        pick_order = [
            ("singles_focus", lambda p: p.get("_unified_aligned") and _best_win_prob(p) >= CONFIDENT_WIN),
            ("singles_focus", lambda p: _best_win_prob(p) >= STRONG_WIN),
            ("singles_focus", lambda p: _best_win_prob(p) >= CONFIDENT_WIN),
            ("singles_focus", lambda p: _comfortable_typical(p) and _best_win_prob(p) >= COMFORTABLE_WIN),
            # If no single clears the bar for this fixture, fall through
            ("min_loss", lambda p: _qualifies_loss_min(p) and _comfortable_typical(p)),
            ("smart_parlay", lambda p: _best_win_prob(p) >= COMFORTABLE_WIN * 0.85),
            ("value", lambda p: _best_win_prob(p) >= COMFORTABLE_WIN),
            ("singles_focus", None),
            ("min_loss", None),
            ("smart_parlay", None),
        ]
    elif shape == "sgm":
        pick_order = [
            ("smart_parlay", lambda p: _best_win_prob(p) >= COMFORTABLE_WIN * 0.85),
            ("singles_focus", lambda p: _best_win_prob(p) >= CONFIDENT_WIN),
            ("min_loss", lambda p: _qualifies_loss_min(p) and _comfortable_typical(p)),
            ("smart_parlay", None),
            ("singles_focus", lambda p: _best_win_prob(p) >= COMFORTABLE_WIN),
            ("value", None),
        ]
    elif shape == "caution":
        pick_order = [
            ("min_loss", lambda p: _qualifies_loss_min(p) and _comfortable_typical(p)),
            ("singles_focus", lambda p: _best_win_prob(p) >= STRONG_WIN),  # only a real lock
            ("smart_parlay", lambda p: _best_win_prob(p) >= CONFIDENT_WIN * 0.9),
            ("min_loss", lambda p: _qualifies_loss_min(p)),
            ("value", lambda p: _best_win_prob(p) >= CONFIDENT_WIN),
            ("singles_focus", lambda p: _best_win_prob(p) >= CONFIDENT_WIN),
        ]
    else:  # spread — draw-live / tight games
        pick_order = [
            ("min_loss", lambda p: _qualifies_loss_min(p) and _comfortable_typical(p)),
            # Totals / BTTS singles can still be right; avoid forcing match-winner
            ("singles_focus", lambda p: _best_win_prob(p) >= CONFIDENT_WIN and not _is_match_winner_only(p)),
            ("singles_focus", lambda p: _best_win_prob(p) >= STRONG_WIN),
            ("smart_parlay", lambda p: _best_win_prob(p) >= COMFORTABLE_WIN * 0.85),
            ("min_loss", lambda p: _qualifies_loss_min(p)),
            ("value", lambda p: _best_win_prob(p) >= COMFORTABLE_WIN),
            ("singles_focus", lambda p: _best_win_prob(p) >= CONFIDENT_WIN),
            ("smart_parlay", None),
        ]

    # Always keep Target paths as last-resort only
    pick_order = list(pick_order) + [
        ("match_card", lambda p: _stern_primary_eligible(p)),
        ("match_card", lambda p: _target_rec_eligible(p)),
    ]

    primary: dict | None = None
    for tab, pred in pick_order:
        cands = _sort_tab(tab, _candidates(tab, pred))
        if cands:
            primary = cands[0]
            break

    if not primary:
        for tab in ("singles_focus", "min_loss", "smart_parlay", "value", "match_card"):
            for p in strategy_plans.get(tab) or []:
                if p.get("legs") and not (thesis and plan_fights_match_thesis(p, thesis, home, away)):
                    primary = p
                    break
            if primary:
                break

    if primary:
        primary = {
            **primary,
            "rec_shape": shape,
            "rec_shape_note": {
                "single": "Clear lean — best high-confidence single for this match",
                "spread": "Tight / draw-live — capital-preservation spread suits better than a forced winner",
                "sgm": "Same-game combo is the better fit for this board",
                "caution": "Thin edge — only show a pick if conviction is genuinely high",
            }.get(shape, "Match-discretion pick"),
        }

    alternatives: list[dict] = []
    if primary:
        primary_sig = _slip_signature(primary)
        primary_legs = _leg_set_signature(primary)
        alt_pool: list[dict] = []
        alt_pool.extend(_candidates("singles_focus", lambda p: _best_win_prob(p) >= 0.52))
        alt_pool.extend(_candidates("min_loss", lambda p: _qualifies_loss_min(p)))
        alt_pool.extend(_candidates("smart_parlay"))
        alt_pool.extend(_candidates("value"))
        alt_pool.extend(_candidates("match_card")[:2])
        alt_pool.sort(
            key=lambda p: (
                0 if (p.get("tab_id") or p.get("id")) == "match_card" else 1,
                _best_win_prob(p),
                p.get("worth_score", 0),
                _likely_profit(p),
            ),
            reverse=True,
        )
        seen_alts: set[tuple] = set()
        bucket_counts: dict[str, int] = {}
        bucket_quota = {"sgm": 2, "single": 2, "compact": 2, "spread": 1, "full": 0}

        def _alt_rank(p: dict) -> tuple:
            bucket = _plan_leg_bucket(p)
            n = len(p.get("legs") or [])
            return (
                1 if bucket_counts.get(bucket, 0) < bucket_quota.get(bucket, 1) else 0,
                0 if (p.get("tab_id") or p.get("id")) == "match_card" else 1,
                _best_win_prob(p),
                -abs(n - 2),
            )

        for p in sorted(alt_pool, key=_alt_rank, reverse=True):
            if len(alternatives) >= MAX_CURATED_ALTS:
                break
            if _slip_signature(p) == primary_sig:
                continue
            leg_sig = _leg_set_signature(p)
            if leg_sig and leg_sig in seen_alts:
                continue
            if leg_sig and leg_sig == primary_legs:
                continue
            if home and away and _plans_contradict(primary, p, home, away):
                continue
            bucket = _plan_leg_bucket(p)
            if bucket_counts.get(bucket, 0) >= bucket_quota.get(bucket, 2):
                continue
            seen_alts.add(leg_sig)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            alternatives.append(p)

    def _curated_label(slip: dict | None, default: str) -> str:
        if not slip:
            return default
        tab = slip.get("tab_id") or slip.get("id") or ""
        if tab == "singles_focus":
            legs = slip.get("legs") or []
            if legs:
                return (legs[0].get("label") or default).split(" @ ")[0]
            return default
        if tab == "min_loss":
            return slip.get("path_label") or "Loss-min spread"
        if tab == "smart_parlay" or slip.get("path_thesis") == "sgm" or slip.get("plan_type") == "stake_combo":
            pl = (slip.get("path_label") or "").strip()
            return pl or "Stake SGM"
        if tab == "value":
            return "Value play"
        if tab != "match_card":
            return default
        pl = (slip.get("path_label") or "").strip()
        if slip.get("path_thesis") == "sgm" or slip.get("plan_type") == "stake_combo":
            return pl or "Stake SGM"
        if pl and "tickets ·" not in pl and not pl.startswith(""):
            short = pl.split("·")[0].strip()
            if short and not short.endswith(" singles"):
                return short
        legs = slip.get("path_legs") or [l.get("label") for l in (slip.get("legs") or []) if l.get("label")]
        if legs:
            preview = ", ".join(
                (l.split(" @ ")[0] if " @ " in l else l)[:32] for l in legs[:2]
            )
            if len(legs) > 2:
                preview += f" +{len(legs) - 2}"
            return preview or default
        return default

    return {
        "primary": _annotate_curated(primary, _curated_label(primary, "Our pick"), recommended=True) if primary else None,
        "alternatives": [
            _annotate_curated(a, _curated_label(a, "Also consider")) for a in alternatives if a
        ],
        "rec_shape": shape,
    }


def _is_match_winner_only(slip: dict) -> bool:
    legs = slip.get("legs") or []
    if not legs:
        return False
    return all(str(l.get("market") or "") in ("match_winner", "h2h", "moneyline") for l in legs)


def _should_skip_match(strategy_plans: dict, *, comfort: float = COMFORTABLE_WIN) -> bool:
    """Skip only when every tab is empty or clearly worthless  -  not when data is thin."""
    if any(
        p.get("worth_taking") and (p.get("hit_probability") or 0) >= 0.12
        for p in strategy_plans.get("match_card") or []
    ):
        return False
    core = ("min_loss", "singles_focus", "value", "smart_parlay", "match_card")
    all_plans = [p for tab in core for p in strategy_plans.get(tab, []) if (p.get("legs") or [])]
    if not all_plans:
        return True
    # Any coherent plan with a real chance → surface it; don't mass-SKIP for missing Stake.
    soft = max(0.40, comfort - 0.10)
    good = [
        p for p in all_plans
        if (
            (_best_win_prob(p) >= soft and _slip_ev(p) >= -4)
            or (_best_win_prob(p) >= 0.48 and _likely_profit(p) >= -budget_leak_ok(p))
            or (len(p.get("legs") or []) >= 2 and _best_win_prob(p) >= 0.42)
        )
    ]
    return len(good) == 0


def budget_leak_ok(p: dict) -> float:
    """Allow small expected loss on the typical outcome before calling skip."""
    return max(12.0, float(p.get("budget_inr") or 200) * 0.08)


def _assess_match_caution(strategy_plans: dict) -> tuple[bool, str | None]:
    """Honest flags  -  thin edges get a caution, not a blank board."""
    min_loss = strategy_plans.get("min_loss") or []
    singles = strategy_plans.get("singles_focus") or []
    value = strategy_plans.get("value") or []
    card = strategy_plans.get("match_card") or []

    if card or min_loss or singles or value:
        core = [p for tab in ("match_card", "min_loss", "singles_focus", "value") for p in strategy_plans.get(tab, [])]
        if core and max(_best_win_prob(p) for p in core) < 0.48 and max(_slip_ev(p) for p in core) < 0:
            return True, "Edges are soft  -  size down or use Hit target for a swing."
        return False, None

    if not min_loss and not singles and not value:
        return True, "No safe spread and no singles  -  Combos tab may still have a path."
    return False, None


def _skip_caution(strategy_plans: dict) -> bool:
    """Deprecated alias."""
    caution, _ = _assess_match_caution(strategy_plans)
    return caution


def _plan_market_families(plan: dict) -> frozenset:
    fams = set()
    for leg in plan.get("legs") or []:
        m = str(leg.get("market") or "")
        if m in ("match_winner", "double_chance", "draw_no_bet"):
            fams.add("result")
        elif m in ("over_under_goals",):
            fams.add("totals")
        elif m in ("btts",):
            fams.add("btts")
        elif m in ("asian_handicap", "handicap"):
            fams.add("handicap")
        elif m in ("stake_combo",) or leg.get("role") in ("stake_combo", "parlay_leg"):
            fams.add("combo")
        else:
            fams.add(m or "other")
    return frozenset(fams)


def _diversify_tab_plans(strategy_plans: dict, home: str, away: str) -> dict:
    """Keep tabs from showing the same result-line dressed up four ways."""
    order = ("match_card", "min_loss", "singles_focus", "value", "smart_parlay")
    claimed: set[frozenset] = set()
    claimed_sigs: set[tuple] = set()
    out: dict = {}
    for tab in order:
        plans = list(strategy_plans.get(tab) or [])
        kept = []
        for p in plans:
            sig = _slip_signature(p)
            fams = _plan_market_families(p)
            # Combos tab must be multi-leg / SGM  -  drop lone singles
            if tab == "smart_parlay":
                n = len([l for l in (p.get("legs") or []) if l.get("label") or l.get("market")])
                if n < 2 and "combo" not in fams:
                    continue
            # Prefer plans whose family set isn't already claimed by an earlier tab
            if sig and sig in claimed_sigs:
                continue
            if fams and fams in claimed and tab != "match_card":
                continue
            kept.append(p)
            if sig:
                claimed_sigs.add(sig)
            if fams:
                claimed.add(fams)
            if len(kept) >= MAX_OPTIONS_PER_TAB:
                break
        # If filter emptied a tab, keep the first original so UI isn't blank
        out[tab] = kept or plans[:1]
    for tab, plans in strategy_plans.items():
        if tab not in out:
            out[tab] = plans
    return out


def _dedupe_slips(slips: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for s in slips:
        key = _slip_signature(s)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _enumerate_singles(
    pool, budget, profile, home, away, stake_only, tab_id, name, why,
    min_prob, min_ev, reserve_pct, prefer_core, *,
    require_likely_positive: bool = False,
    require_positive_ev: bool = False,
    min_win_prob: float = COMFORTABLE_WIN,
    max_n: int = MAX_OPTIONS_PER_TAB,
    initial_exclude: set | None = None,
) -> list[dict]:
    exclude: set = set(initial_exclude or [])
    alts: list[dict] = []
    for _ in range(max_n * 2):
        if len(alts) >= max_n:
            break
        slip = _build_single_slip(
            tab_id, name, why, pool, budget, profile, home, away, stake_only, exclude,
            min_prob=min_prob, min_ev=min_ev, reserve_pct=reserve_pct, prefer_core=prefer_core,
        )
        if not slip.get("legs"):
            break
        keys = _leg_keys(slip)
        if _slip_signature(slip) in {_slip_signature(a) for a in alts}:
            exclude |= keys
            continue
        if require_likely_positive and _likely_profit(slip) < 0:
            exclude |= keys
            continue
        if _best_win_prob(slip) < min_win_prob:
            exclude |= keys
            continue
        if require_positive_ev and _slip_ev(slip) < 0:
            exclude |= keys
            continue
        alts.append(slip)
        exclude |= keys
    return alts


def _confidence_label(p: float) -> str:
    if p >= STRONG_WIN:
        return "very confident"
    if p >= CONFIDENT_WIN:
        return "confident"
    if p >= COMFORTABLE_WIN:
        return "decent edge"
    return "too risky"


def _single_likely_scenario(p: float, stake: float, win_profit: float, lose_profit: float) -> tuple[float, str]:
    """Most-likely case for a single  -  never use 50% as the comfort bar."""
    if p >= CONFIDENT_WIN:
        return win_profit, f"Most likely: wins (~{p:.0%} chance)  -  {_confidence_label(p)}."
    if p >= COMFORTABLE_WIN:
        return win_profit, (
            f"Likely wins (~{p:.0%}), but {1 - p:.0%} of the time you still lose {format_inr(stake)}."
        )
    return lose_profit, (
        f"Most likely: loses (~{1 - p:.0%} miss rate). "
        f"Below our {COMFORTABLE_WIN:.0%} minimum  -  not worth your money."
    )


def _best_win_prob(slip: dict) -> float:
    ptype = slip.get("plan_type") or slip.get("slip_type")
    if ptype in ("stake_combo", "stake_sgm"):
        for key in ("hit_probability", "combined_probability"):
            hp = slip.get(key)
            if hp:
                return float(hp)
    legs = slip.get("legs") or []
    if not legs:
        return float(slip.get("hit_probability") or 0)
    leg_probs = [float(l.get("our_probability") or 0) for l in legs]
    if leg_probs and any(leg_probs):
        return max(leg_probs)
    return float(slip.get("hit_probability") or 0)


def _prob_all_legs_lose(legs: list[dict]) -> float:
    if not legs:
        return 1.0
    return math.prod(1 - l.get("our_probability", 0) for l in legs)


def _combo_contradicts(picks: tuple, home: str = "", away: str = "") -> bool:
    """Drop combos that fight each other on the same match."""
    from bet_placer.engine.card_coherence import spread_contradicts

    if spread_contradicts(picks, home, away):
        return True
    return False


def _used_keys_from_plans(plans: dict) -> set:
    keys: set = set()
    for tab_plans in plans.values():
        for slip in tab_plans if isinstance(tab_plans, list) else []:
            keys |= _leg_keys(slip)
    return keys
    if not legs:
        return 1.0
    return math.prod(1 - l.get("our_probability", 0) for l in legs)


def _loss_preservation_score(slip: dict) -> tuple:
    """Higher = better for loss-min (reserve, bounded worst case, spread > single)."""
    budget = slip.get("total_stake_inr", 0) + slip.get("reserve_inr", 0)
    reserve_pct = slip["reserve_inr"] / budget if budget else 0
    worst = float((slip.get("scenarios") or {}).get("worst_case", {}).get("profit_inr", -999))
    p_all_lose = _prob_all_legs_lose(slip.get("legs") or [])
    n = len(slip.get("legs") or [])
    spread_bonus = 0.08 if n >= 2 else 0.0
    return (reserve_pct + spread_bonus, worst, -p_all_lose, -slip.get("total_stake_inr", 0))


def _qualifies_loss_min(slip: dict) -> bool:
    """Capital preservation: spread only (2–3 legs), never a lone single."""
    legs = slip.get("legs") or []
    if len(legs) not in (2, 3):
        return False
    budget = slip.get("total_stake_inr", 0) + slip.get("reserve_inr", 0)
    if budget <= 0:
        return False
    reserve_pct = slip["reserve_inr"] / budget
    risk_pct = slip["total_stake_inr"] / budget

    for leg in legs:
        if leg.get("market") not in CORE_MARKETS:
            return False
        if leg.get("our_probability", 0) < LOSS_MIN_LEG_MIN_PROB:
            return False

    if len(legs) in (2, 3):
        if risk_pct > LOSS_MIN_SPREAD_MAX_RISK_PCT + 0.03:
            return False
        if reserve_pct < LOSS_MIN_SPREAD_MIN_RESERVE_PCT - 0.03:
            return False
    else:
        return False

    if _slip_ev(slip) < LOSS_MIN_MIN_EV * budget:
        return False
    return True


def _scenarios_loss_min_spread(legs: list[dict], reserve: float) -> dict:
    """Scenarios framed around not losing your whole budget."""
    total = sum(l["stake_inr"] for l in legs)
    probs = [l["our_probability"] for l in legs]
    profits = [l["stake_inr"] * (l["odds"] - 1) for l in legs]
    p_all_lose = _prob_all_legs_lose(legs)
    p_at_least_one = 1 - p_all_lose
    p_all_win = math.prod(probs)
    ev = sum(
        p * s * (o - 1) - (1 - p) * s
        for l in legs for p, s, o in [(l["our_probability"], l["stake_inr"], l["odds"])]
    )
    return {
        "worst_case": {
            "label": "All miss",
            "profit_inr": round(-total, 0),
            "description": (
                f"Every bet loses (~{p_all_lose:.0%})  -  down {format_inr(total)}, "
                f"but you still keep {format_inr(reserve)} unbet."
            ),
        },
        "likely_case": {
            "label": "Most likely",
            "profit_inr": round(ev, 0),
            "description": (
                f"~{p_at_least_one:.0%} chance at least one wins  -  "
                f"your {format_inr(reserve)} reserve is safe either way."
            ),
        },
        "best_case": {
            "label": "All win",
            "profit_inr": round(sum(profits), 0),
            "description": f"All {len(legs)} hit (~{p_all_win:.0%}). Profit {format_inr(sum(profits))}.",
        },
        "expected_value_inr": round(ev, 0),
    }


def _build_loss_min_spread(
    picks: tuple,
    budget: float,
    profile: dict,
    stake_only: bool,
    home: str = "",
    away: str = "",
) -> dict:
    n = len(picks)
    reserve = _round(budget * LOSS_MIN_SPREAD_MIN_RESERVE_PCT)
    max_deploy = _round(budget * LOSS_MIN_SPREAD_MAX_RISK_PCT)
    stake_each = _round(max_deploy / n)
    total = stake_each * n
    if total > max_deploy:
        stake_each = _round(max_deploy / n)
        total = stake_each * n
    reserve = budget - total
    roles = ["main", "support", "extra"]
    legs = [
        _leg(opt, stake_each, roles[min(i, 2)], _reason(opt, profile, "Safe leg"), home, away)
        for i, opt in enumerate(picks)
    ]
    labels = ", ".join(p.label for p in picks)
    sc = _scenarios_loss_min_spread(legs, reserve)
    min_p = min(p.our_probability for p in picks)
    return {
        "id": "min_loss",
        "name": " Loss-minimizing",
        "description": f"{n} small bets · {labels}",
        "why": (
            f"Spread {format_inr(total)} across {n} likely picks ({min_p:.0%}+ each). "
            f"Keep {format_inr(reserve)} ({reserve / budget:.0%} of budget) untouched  -  "
            f"one miss doesn't wipe you out."
        ),
        "risk": "low",
        "loss_min_style": "spread",
        "legs": legs,
        "total_stake_inr": total,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": sc.get("expected_value_inr", 0),
        "win_probability_pct": round((1 - _prob_all_legs_lose(legs)) * 100, 1),
    }


def _enumerate_loss_min_options(
    pool, budget, profile, home, away, stake_only,
    human_context=None,
) -> list[dict]:
    """Loss-min: spread-only (2–3 small stakes). No singles  -  those live on One best bet."""
    ctx = human_context or {}
    unified_lead = None
    unified = ctx.get("unified_picks") or []
    if unified:
        unified_lead = _pool_match_for_pick(pool, unified[0], home, away)

    cands = _candidates(
        pool, profile, home, away, CORE_MARKETS,
        LOSS_MIN_LEG_MIN_PROB, LOSS_MIN_MIN_EV, set(),
        prefer_core=True, sort_by="probability",
    )[:12]
    if unified_lead and unified_lead not in cands:
        cands = [unified_lead] + cands
    alts: list[dict] = []

    for n_legs in (2, 3):
        for combo in combinations(cands, n_legs):
            if len({c.market for c in combo}) < n_legs:
                continue
            if _combo_contradicts(combo, home, away):
                continue
            slip = _build_loss_min_spread(combo, budget, profile, stake_only, home, away)
            if not _qualifies_loss_min(slip):
                continue
            from bet_placer.engine.card_coherence import path_is_coherent
            if not path_is_coherent(slip.get("legs") or [], home, away):
                continue
            if unified_lead and unified_lead in combo:
                slip["_unified_aligned"] = True
            alts.append(slip)

    alts = _dedupe_slips(alts)
    # Prefer spreads that include the unified thesis pick, then game character.
    alts.sort(
        key=lambda s: (
            bool(s.get("_unified_aligned")),
            _slip_profile_bonus(s, profile),
            _loss_preservation_score(s),
        ),
        reverse=True,
    )
    return alts[:MAX_OPTIONS_PER_TAB]


def _pool_match_for_pick(pool: list, pick: dict, home: str = "", away: str = ""):
    """Map a unified/smart-pick dict back to a pool MarketOption."""
    if not pick or not pool:
        return None
    market = pick.get("market")
    selection = (pick.get("selection") or "").lower()
    line = pick.get("line")
    label = (pick.get("label") or "").lower()

    for opt in pool:
        if market and opt.market != market:
            continue
        if selection and str(opt.selection).lower() != selection:
            continue
        if line is not None and opt.line is not None and abs(float(opt.line) - float(line)) > 0.01:
            continue
        if market or selection:
            return opt

    if label.endswith(" to win"):
        team = label.replace(" to win", "").strip()
        for opt in pool:
            if opt.market == "match_winner" and team and team in opt.label.lower():
                return opt

    if label.startswith("draw or "):
        team = label.replace("draw or ", "").strip()
        for opt in pool:
            if opt.market == "double_chance" and team in opt.label.lower():
                return opt

    if label:
        for opt in pool:
            ol = opt.label.lower()
            if label == ol or label in ol or ol in label:
                return opt
    return None


def _target_plan_to_slip(plan: dict, target: float, home: str, away: str) -> dict | None:
    """Convert a target-planner plan into a match_card slip."""
    legs = [dict(l) for l in (plan.get("legs") or [])]
    if not legs:
        return None
    from bet_placer.engine.card_coherence import path_is_coherent

    ptype = plan.get("plan_type") or "match_card"
    if ptype in ("match_card", "coverage") and not path_is_coherent(legs, home, away):
        return None

    target_f = float(target)
    budget_guess = float(plan.get("total_stake_inr") or 0) + float(plan.get("reserve_inr") or 0)
    if budget_guess <= 0:
        budget_guess = sum(float(l.get("stake_inr") or 0) for l in legs) * 1.5
    target_profit = float(plan.get("target_profit_inr") or target_profit_inr(budget_guess, target_f))
    for leg in legs:
        leg["return_inr"] = leg.get("return_inr") or round(
            (leg.get("stake_inr") or 0) * (leg.get("odds") or 1)
        )
    annotate_leg_profit_flags(legs, target_profit)

    path_label = (
        plan.get("path_label")
        or plan.get("path_headline")
        or plan.get("name")
        or ""
    ).strip()
    from bet_placer.engine.match_card import _GENERIC_VARIANT_NOTES, path_label_from_legs
    tickets_label = path_label_from_legs(legs)
    if tickets_label and (
        not path_label
        or path_label in _GENERIC_VARIANT_NOTES
        or "tickets ·" in path_label
        or path_label.startswith("")
    ):
        path_label = tickets_label
    elif not path_label:
        path_label = tickets_label
    # Never append leg names again  -  path_label_from_legs is the single source of truth.

    if ptype == "stake_combo":
        slip_type = "stake_sgm"
    elif ptype == "single":
        slip_type = "single"
    else:
        slip_type = "spread_card"

    return {
        **plan,
        "id": "match_card",
        "slip_type": slip_type,
        "name": plan.get("name") or plan.get("plan_type_label") or "Target plan",
        "path_label": path_label,
        "path_legs": [l.get("label", "") for l in legs if l.get("label")],
        "worth_label": plan.get("worth_label") or "",
        "worth_taking": bool(plan.get("worth_taking")),
        "description": plan.get("description") or plan.get("path_headline") or "",
        "why": plan.get("why") or plan.get("path_headline") or "",
        "target_cashout_inr": target_f,
        "target_profit_inr": target_profit,
        "target_return_inr": plan.get("target_return_inr") or target_f,
        "legs": legs,
        "coherence_checked": True,
        "home_team": home,
        "away_team": away,
    }


def short_leg_preview(label: str, max_len: int = 28) -> str:
    """Compact leg name for path picker labels."""
    s = (label or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _leg_set_signature(slip_or_plan: dict) -> tuple:
    """Dedupe paths by the actual tickets  -  not labels or stake sizing."""
    return tuple(sorted(
        (l.get("market"), l.get("selection"), l.get("line"))
        for l in (slip_or_plan.get("legs") or [])
    ))


def _card_has_balanced_spread(plan: dict) -> bool:
    """Spread card with insurance + route (1 to 20 tickets)."""
    legs = plan.get("legs") or []
    if not (1 <= len(legs) <= 20):
        return False
    insurance = [l for l in legs if (l.get("role") or "") in _INSURANCE_ROLES]
    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not routes:
        return False
    route = routes[0]
    if route.get("market") == "player_goal":
        return False
    if float(route.get("our_probability") or 0) < 0.10:
        return False
    anchor = next((l for l in insurance if l.get("role") == "anchor"), insurance[0] if insurance else None)
    if anchor and leg_net_if_solo_win(anchor, legs) < -10:
        best_route = max((leg_net_if_solo_win(l, legs) for l in routes), default=0)
        if best_route < 80:
            return False
    return True


def _card_has_partial_route(plan: dict, target_cashout: float | None = None) -> bool:
    """Spread where the profit route reaches at least 35% of the goal."""
    if not _card_has_balanced_spread(plan):
        return False
    legs = plan.get("legs") or []
    budget = float(
        plan.get("budget_inr")
        or (plan.get("reserve_inr") or 0) + (plan.get("total_stake_inr") or 0)
        or 300
    )
    tgt = float(
        target_cashout or plan.get("target_cashout_inr") or plan.get("target_return_inr") or 0
    )
    profit = target_profit_inr(budget, tgt) if tgt > budget else float(plan.get("target_profit_inr") or 0)
    if profit <= 0:
        return False
    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not routes:
        routes = [l for l in legs if l.get("partial_profit_route") or l.get("hits_target")]
    return any(leg_net_if_solo_win(l, legs) >= profit * 0.35 for l in routes)


def _card_has_target_route(plan: dict, target_cashout: float | None = None) -> bool:
    """Balanced spread where the swing ticket hits the profit target."""
    if not _card_has_balanced_spread(plan):
        return False
    return _path_hits_profit_target(plan, target_cashout)


def _all_legs_hit_target(plan: dict, target: float | None = None) -> bool:
    """Every ticket pays the cashout goal if it wins alone."""
    legs = plan.get("legs") or []
    if not legs:
        return False
    tgt = float(
        target
        or plan.get("target_return_inr")
        or plan.get("target_cashout_inr")
        or 0
    )
    if tgt <= 0:
        return False
    floor = tgt * 0.95
    return all(
        float(l.get("return_inr") or (l.get("stake_inr", 0) * l.get("odds", 1))) >= floor
        for l in legs
    )


def _path_reaches_target(plan: dict, target: float | None = None) -> bool:
    ptype = plan.get("plan_type") or plan.get("slip_type") or ""
    if ptype in ("match_card", "spread_card"):
        return _card_has_target_route(plan, target)
    return _all_legs_hit_target(plan, target)


def _plan_leg_bucket(plan: dict) -> str:
    """Group paths for balanced UI mix."""
    legs = plan.get("legs") or []
    n = len(legs)
    if plan.get("plan_type") == "stake_combo" or plan.get("slip_type") == "stake_sgm":
        return "sgm"
    if plan.get("path_thesis") == "sgm":
        return "sgm"
    if n <= 1:
        return "single"
    if n <= 3:
        return "compact"
    if n == 4:
        return "spread"
    return "full"


def _tier_target_plans(
    plans: list[dict],
    *,
    prefers_spread: bool = True,
    max_paths: int = MAX_MATCH_CARD_PATHS,
    target: float | None = None,
) -> list[dict]:
    """Pick distinct paths  -  balance ticket count, combos, and risk."""
    if not plans:
        return []

    def _rank(p: dict) -> tuple:
        legs = p.get("legs") or []
        hp = float(p.get("hit_probability") or 0)
        all_hit = 1 if _card_has_target_route(p, target) else (1 if _card_has_partial_route(p, target) else 0)
        spread_bonus = 1 if (p.get("plan_type") == "match_card" and len(legs) >= 2) else 0
        return (
            all_hit,
            spread_bonus,
            p.get("worth_score", 0),
            hp,
            -abs(len(legs) - 3),
            len(legs),
        )

    ranked = sorted(plans, key=_rank, reverse=True)
    buckets: dict[str, list[dict]] = {
        "sgm": [], "single": [], "compact": [], "spread": [], "full": [],
    }
    for p in ranked:
        buckets[_plan_leg_bucket(p)].append(p)

    quotas = [
        ("sgm", 6),
        ("compact", 5),
        ("spread", 4),
        ("single", 2),
        ("full", 2),
    ]
    selected: list[dict] = []
    seen_legs: set[tuple] = set()

    def _try_add(p: dict) -> bool:
        sig = _leg_set_signature(p)
        if not sig or sig in seen_legs:
            return False
        seen_legs.add(sig)
        selected.append(p)
        return True

    for bucket, quota in quotas:
        added = 0
        for p in buckets.get(bucket, []):
            if len(selected) >= max_paths:
                break
            if _try_add(p):
                added += 1
            if added >= quota:
                break

    for p in ranked:
        if len(selected) >= max_paths:
            break
        _try_add(p)

    return selected[:max_paths]


def _stake_sgm_display_paths(
    overlay: dict | None,
    budget: float,
    pool: list,
    home: str,
    away: str,
    ctx: dict | None,
    max_n: int = 3,
) -> list[dict]:
    """Verified Stake SGMs sized for net profit goal if the combo wins."""
    if not overlay:
        return []
    from bet_placer.engine.card_coherence import stake_combo_fits_thesis
    from bet_placer.engine.stake_sgm import estimate_stake_combo_probability, _sgm_sweetness

    target = float((ctx or {}).get("target_cashout_inr") or max(budget * 2.5, budget + 500))
    target_profit = float((ctx or {}).get("target_profit_inr") or target_profit_inr(budget, target))
    profit_floor = target_profit * 0.95

    combos = overlay.get("stake_combos") or []
    out: list[dict] = []
    for c in sorted(
        combos,
        key=lambda x: (
            estimate_stake_combo_probability(x, pool, home, away) >= 0.18,
            _sgm_sweetness(float(x.get("odds") or 0)),
            estimate_stake_combo_probability(x, pool, home, away),
        ),
        reverse=True,
    ):
        odds = float(c.get("odds") or 0)
        if odds <= 1.05 or odds > 12:
            continue
        stake = min_stake_for_profit(odds, target_profit, 0)
        if stake > budget * 0.55:
            continue
        net = stake * odds - stake
        if net < profit_floor:
            continue
        if home and away and not stake_combo_fits_thesis(c, pool, home, away, ctx):
            continue
        hit_prob = estimate_stake_combo_probability(c, pool, home, away)
        if hit_prob < 0.12:
            continue
        hit_pct = round(hit_prob * 100, 1)
        lbl = c.get("label") or c.get("stake_market") or "Stake combo"
        from bet_placer.markets.labels import format_combo_label
        ret = round(stake * odds)
        leg = {
            "market": "stake_combo",
            "label": format_combo_label(lbl, odds, home, away, stake_market=c.get("stake_market")),
            "selection": c.get("selection"),
            "line": c.get("line"),
            "odds": odds,
            "stake_inr": stake,
            "return_inr": ret,
            "hits_target": net >= profit_floor,
            "profit_if_solo_inr": round(net, 0),
            "our_probability": hit_prob,
            "our_probability_pct": hit_pct,
            "role": "stake_combo",
            "verified_stake": True,
            "odds_source": "stake",
            "live_odds": True,
            "stake_market": c.get("stake_market"),
        }
        out.append({
            "plan_type": "stake_combo",
            "verified_stake": True,
            "path_label": f"Stake SGM · {odds}x",
            "path_thesis": "sgm",
            "path_legs": [lbl],
            "name": " Stake combo",
            "description": f"{lbl} @ {odds}x  -  nets {format_inr(target_profit)} profit if it wins",
            "legs": [leg],
            "total_stake_inr": stake,
            "reserve_inr": budget - stake,
            "combined_odds": odds,
            "hit_probability": hit_prob,
            "hit_probability_pct": hit_pct,
            "target_return_inr": target,
            "target_profit_inr": target_profit,
            "worth_taking": hit_prob >= 0.08,
        })
        if len(out) >= max_n:
            break
    return out


def _build_match_card_alternatives(
    pool, budget, profile, home, away, stake_only, human_context=None,
    match=None, probabilities=None,
) -> list[dict]:
    from bet_placer.engine.match_card import (
        build_balanced_sized_paths,
        build_coherent_match_paths,
        build_match_card_variants,
        build_target_match_slips,
    )
    from bet_placer.engine.target_planner import (
        build_target_plans,
        _dedupe_plans,
        _plan_signature,
        _score_plan_worth,
        _search_stake_combos,
    )

    ctx = human_context or {}
    target = float(ctx.get("target_cashout_inr") or max(budget * 2.5, budget + 500))
    # Main cards pick structure per match (not Settings style)
    prefers_spread = True
    all_opts = list(ctx.get("_all_options") or pool)

    plans: list[dict] = []
    seen_sigs: set = set()

    def _add_plan(plan: dict | None) -> None:
        if not plan or not plan.get("legs"):
            return
        ptype = plan.get("plan_type") or plan.get("slip_type") or ""
        if ptype in ("match_card", "spread_card", "coverage"):
            if not (
                _card_has_target_route(plan, target)
                or _card_has_partial_route(plan, target)
                or _card_has_balanced_spread(plan)
            ):
                return
        elif ptype in ("stake_combo", "single"):
            profit = float(ctx.get("target_profit_inr") or target_profit_inr(budget, target))
            legs = plan.get("legs") or []
            if len(legs) == 1:
                leg = legs[0]
                net = float(leg.get("stake_inr") or 0) * (float(leg.get("odds") or 1) - 1)
                if net < profit * 0.95:
                    return
        else:
            return
        sig = _plan_signature(plan)
        if sig in seen_sigs:
            return
        seen_sigs.add(sig)
        plans.append(plan)

    def _add_slip(slip: dict | None) -> None:
        if not slip:
            return
        if slip.get("plan_type") == "stake_combo" or slip.get("slip_type") == "stake_sgm":
            _add_plan(slip)
            return
        plan = _plan_from_spread_slip(slip, target)
        if plan:
            _add_plan(plan)

    # 1. Coverage routes + target-sized spreads (each ticket pays goal solo)
    tp = build_target_plans(
        all_opts, budget, target, home, away,
        match=match, probabilities=probabilities,
        human_context=ctx,
    )
    for p in tp.get("plans") or []:
        _add_plan(p)

    for slip in build_balanced_sized_paths(
        pool, budget, target, profile, home, away, stake_only, ctx,
    ):
        _add_slip(slip)
    for slip in build_target_match_slips(
        pool, budget, target, profile, home, away, stake_only, ctx, max_slips=3,
    ):
        _add_slip(slip)
    # 3. Coherent paths + verified Stake SGMs
    for slip in build_coherent_match_paths(
        pool, budget, profile, home, away, stake_only, ctx,
        max_paths=3, target=target,
    ):
        _add_slip(slip)

    # 2. Verified Stake SGMs  -  real combo prices from Stake Combos tab
    overlay = ctx.get("stake_overlay")
    if overlay and overlay.get("stake_combos"):
        for p in _stake_sgm_display_paths(overlay, budget, pool, home, away, ctx, max_n=2):
            _add_plan(p)
        for p in _search_stake_combos(
            overlay, budget, target, stake_only, pool=pool, home=home, away=away, ctx=ctx,
        )[:6]:
            lbl = (p.get("label") or p.get("path_headline") or "Stake combo")[:48]
            p["path_label"] = f"Stake SGM · {p.get('combined_odds') or p.get('odds')}x · {lbl}"
            p["path_thesis"] = "sgm"
            p["path_legs"] = [lbl]
            _add_plan(p)

    if len(plans) < 5:
        for v in build_match_card_variants(
            all_opts, budget, target, profile, home, away, stake_only, ctx,
            max_variants=max(2, MAX_MATCH_CARD_PATHS - len(plans)),
        ):
            _add_plan(v)

    plans = _dedupe_plans(plans)
    for p in plans:
        if not p.get("worth_taking") and _path_reaches_target(p, target):
            p["worth_taking"] = True
    plans = [_score_plan_worth(p, ctx, None) for p in plans]
    selected = _tier_target_plans(plans, prefers_spread=prefers_spread, target=target)

    slips: list[dict] = []
    seen: set = set()
    for plan in selected:
        slip = _target_plan_to_slip(plan, target, home, away)
        if not slip:
            continue
        sig = _leg_set_signature(slip)
        if sig in seen:
            continue
        seen.add(sig)
        slips.append(slip)

    if not slips:
        return []
    return [
        _annotate_slip(s, "match_card", i + 1, recommended=(i == 0))
        for i, s in enumerate(slips[:MAX_MATCH_CARD_PATHS])
    ]


def _build_min_loss_alternatives(pool, budget, profile, home, away, stake_only, human_context=None) -> list[dict]:
    """Loss-min: spread-only. Empty if no safe spread exists."""
    candidates = _enumerate_loss_min_options(
        pool, budget, profile, home, away, stake_only, human_context=human_context,
    )
    if not candidates:
        return []
    return [
        _annotate_slip(s, "min_loss", i + 1, recommended=(i == 0))
        for i, s in enumerate(candidates)
    ]


def _build_single_alternatives(pool, budget, profile, home, away, stake_only, exclude_keys=None, human_context=None) -> list[dict]:
    ctx = human_context or {}
    easy = ctx.get("easy_money_picks") or []
    unified = ctx.get("unified_picks") or []
    lead_picks = easy + [p for p in unified if p.get("label") not in {e.get("label") for e in easy}]
    candidates = _enumerate_singles(
        pool, budget, profile, home, away, stake_only,
        "singles_focus", " One best bet",
        "One clear single where the edge is worth the stake.",
        SINGLE_MIN_PROB, SINGLE_MIN_EV, 0.50, False,
        require_positive_ev=False,
        min_win_prob=SINGLE_MIN_PROB,
        max_n=max(8, MAX_OPTIONS_PER_TAB),
        initial_exclude=exclude_keys,
    )

    if lead_picks:
        matched = None
        aligned_pick = None
        for pick in lead_picks:
            if (pick.get("our_probability") or 0) < SINGLE_ALIGN_MIN_PROB:
                continue
            matched = _pool_match_for_pick(pool, pick, home, away)
            if matched:
                aligned_pick = pick
                break
        if matched and aligned_pick:
            why = aligned_pick.get("why") or aligned_pick.get("reason") or (
                "High-confidence lead  -  same read as easy money / build slip."
            )
            primary = _build_single_from_option(
                matched, "singles_focus", " One best bet", why,
                budget, profile, stake_only, home, away,
            )
            primary["_unified_aligned"] = True
            lead_key = (matched.market, matched.selection, matched.line)
            candidates = [primary] + [
                c for c in candidates
                if lead_key not in _leg_keys(c)
            ]
        elif lead_picks[0].get("our_probability", 0) >= SINGLE_ALIGN_MIN_PROB:
            primary = _build_single_from_pick(
                lead_picks[0], "singles_focus", " One best bet",
                lead_picks[0].get("why") or "High-confidence thesis pick.",
                budget, profile, stake_only, home, away,
            )
            candidates = [primary] + candidates
    candidates.sort(
        key=lambda s: (
            -max((l.get("our_probability", 0) for l in s.get("legs", [])), default=0),
            -_slip_ev(s),
        ),
    )
    return [
        _annotate_slip(s, "singles_focus", i + 1, recommended=(i == 0))
        for i, s in enumerate(candidates[:MAX_OPTIONS_PER_TAB])
    ]


def _build_value_alternatives(pool, budget, profile, home, away, stake_only, exclude_keys=None) -> list[dict]:
    """Value tab: diverse singles only  -  no fake multi-leg slips."""
    ex = exclude_keys or set()
    raw: list[dict] = []

    raw.extend(_enumerate_singles(
        pool, budget, profile, home, away, stake_only,
        "value", " Value-for-money",
        "Best single where the payout is worth the risk.",
        VALUE_MIN_PROB, -0.02, 0.45, False,
        require_positive_ev=False,
        max_n=max(10, MAX_OPTIONS_PER_TAB),
        initial_exclude=ex,
    ))

    raw = _dedupe_slips(raw)
    # Prefer higher win probability; EV only as tie-break
    raw.sort(key=lambda s: (
        -max((l.get("our_probability", 0) for l in s.get("legs", [])), default=0),
        -_slip_ev(s),
        -_likely_profit(s),
    ))
    return [
        _annotate_slip(s, "value", i + 1, recommended=(i == 0))
        for i, s in enumerate(raw[:MAX_OPTIONS_PER_TAB])
    ]


def _build_parlay_alternatives(
    pool, budget, profile, stake_only, exclude_keys=None, max_n: int = MAX_STAKE_SGM_PER_SLIP,
    overlay: dict | None = None,
    home: str = "",
    away: str = "",
    human_context: dict | None = None,
) -> list[dict]:
    """Stake SGMs when scraped; else estimated 2-leg multis from distinct families."""
    from bet_placer.engine.card_coherence import stake_combo_fits_thesis, stake_combo_is_garbage

    combos = (overlay or {}).get("stake_combos") or []
    alts: list[dict] = []
    for combo in sorted(combos, key=lambda c: float(c.get("odds") or 0)):
        if float(combo.get("odds") or 0) > 15:
            continue
        if home and away and stake_combo_is_garbage(combo, home, away):
            continue
        if home and away and not stake_combo_fits_thesis(combo, pool, home, away, human_context):
            continue
        slip = _slip_from_stake_combo(combo, budget, stake_only, pool=pool, home=home, away=away)
        if slip:
            alts.append(_annotate_slip(slip, "smart_parlay", len(alts) + 1, recommended=(len(alts) == 0)))
        if len(alts) >= max_n:
            break
    if alts:
        alts.sort(key=lambda s: (_best_win_prob(s), -float(s.get("combined_odds") or 0)), reverse=True)
        return alts

    # No scraped SGM  -  still offer real combo options (estimated, verify on Stake).
    return _estimated_parlay_alts(
        pool, budget, profile, stake_only, home, away, max_n=max_n, exclude_keys=exclude_keys,
    )


def _option_family(o) -> str:
    m = getattr(o, "market", None) or ""
    if m in ("match_winner", "double_chance", "draw_no_bet"):
        return "result"
    if m == "over_under_goals":
        return "totals"
    if m == "btts":
        return "btts"
    if m in ("asian_handicap", "handicap"):
        return "handicap"
    return str(m or "other")


def _estimated_parlay_alts(
    pool, budget, profile, stake_only, home, away, *, max_n: int = 3, exclude_keys=None,
) -> list[dict]:
    """2-leg estimated multis across different market families."""
    exclude = set(exclude_keys or [])
    cands = []
    for o in pool or []:
        key = (o.market, o.selection, o.line)
        if key in exclude:
            continue
        if float(getattr(o, "our_probability", 0) or 0) < 0.40:
            continue
        if float(getattr(o, "ev_pct", 0) or 0) < -8:
            continue
        if float(getattr(o, "odds", 0) or 0) <= 1.05:
            continue
        cands.append(o)
    cands.sort(key=lambda o: (
        float(getattr(o, "our_probability", 0) or 0) * 0.6
        + max(0.0, float(getattr(o, "ev_pct", 0) or 0)) / 100.0
    ), reverse=True)

    alts: list[dict] = []
    used: set[tuple] = set()
    for i, a in enumerate(cands[:18]):
        fa = _option_family(a)
        for b in cands[i + 1:i + 12]:
            if _option_family(b) == fa:
                continue
            pair_key = tuple(sorted([
                (a.market, a.selection, a.line),
                (b.market, b.selection, b.line),
            ]))
            if pair_key in used:
                continue
            used.add(pair_key)
            slip = _build_multi_from_picks(
                (a, b),
                "smart_parlay",
                "Estimated multi",
                "Two separate markets · verify combined price on Stake before placing.",
                budget, profile, 0.35, stake_only, home, away,
            )
            if not slip.get("legs") or len(slip["legs"]) < 2:
                continue
            # Combined odds as product of decimals (estimate)
            odds_prod = 1.0
            hit_p = 1.0
            for leg in slip["legs"]:
                odds_prod *= float(leg.get("odds") or 1)
                hit_p *= float(leg.get("our_probability") or 0.45)
            slip["combined_odds"] = round(odds_prod, 2)
            slip["hit_probability"] = round(hit_p, 4)
            slip["slip_type"] = "estimated_parlay"
            slip["placement_mode"] = "estimated_parlay"
            alts.append(_annotate_slip(slip, "smart_parlay", len(alts) + 1, recommended=(len(alts) == 0)))
            if len(alts) >= max_n:
                return alts
    return alts


def _build_multi_from_picks(
    picks: tuple,
    id_: str,
    name: str,
    why: str,
    budget: float,
    profile: dict,
    reserve_pct: float,
    stake_only: bool,
    home: str = "",
    away: str = "",
) -> dict:
    if not picks:
        return _empty(id_, name, budget, profile)
    legs: list[dict] = []
    remaining = budget
    reserve = _round(budget * reserve_pct)
    remaining -= reserve
    roles = ["main", "support", "extra"]
    for i, opt in enumerate(picks):
        if remaining < 40:
            break
        share = 0.55 if i == 0 else 0.45 / max(1, len(picks) - 1)
        stake = _round(min(remaining * share, remaining)) if i < len(picks) - 1 else _round(remaining)
        if stake < 20:
            continue
        legs.append(_leg(opt, stake, roles[min(i, 2)], _reason(opt, profile, roles[min(i, 2)]), home, away))
        remaining -= stake
    if not legs:
        return _empty(id_, name, budget, profile)
    reserve += max(0, remaining)
    total = sum(l["stake_inr"] for l in legs)
    sc = _scenarios_multi(legs, reserve)
    labels = ", ".join(l["label"] for l in legs[:3])
    if len(picks) > 3:
        labels += f" +{len(picks) - 3} more"
    return {
        "id": id_,
        "name": name,
        "description": f"{len(legs)} bets · {labels}",
        "why": why,
        "risk": "high",
        "legs": legs,
        "total_stake_inr": total,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": _slip_ev({"scenarios": sc}),
    }


def _slip_from_stake_combo(
    combo: dict,
    budget: float,
    stake_only: bool,
    *,
    pool: list | None = None,
    home: str = "",
    away: str = "",
) -> dict | None:
    """One verified Stake same-game combo  -  never multiply single-line odds."""
    from bet_placer.engine.stake_sgm import estimate_stake_combo_probability
    from bet_placer.markets.labels import format_combo_label

    odds = float(combo.get("odds") or 0)
    if odds <= 1.0 or odds > 15:
        return None
    stake = _round(min(budget * 0.12, 80))
    if stake < 20:
        return None
    hit_prob = estimate_stake_combo_probability(combo, pool, home, away)
    if hit_prob < 0.03:
        return None
    hit_pct = round(hit_prob * 100, 1)
    reserve = budget - stake
    ret = round(stake * odds, 0)
    raw_lbl = combo.get("label") or combo.get("stake_market")
    leg = {
        "label": format_combo_label(raw_lbl, odds, home, away, stake_market=combo.get("stake_market")),
        "market": "stake_combo",
        "selection": combo.get("selection"),
        "line": combo.get("line"),
        "odds": odds,
        "stake_inr": stake,
        "role": "stake_combo",
        "reason": "Verified Stake combo market",
        "live_odds": True,
        "odds_source": "stake",
        "stake_market": combo.get("stake_market"),
        "our_probability": hit_prob,
        "our_probability_pct": hit_pct,
        "ev_pct": 0,
        "return_inr": ret,
    }
    ev = round(stake * (odds - 1) * hit_prob - stake * (1 - hit_prob), 0)
    return {
        "id": "stake_combo",
        "plan_type": "stake_combo",
        "name": "Stake combo",
        "description": f"{leg['label']} @ {odds}x  -  scraped from Stake Combos",
        "why": (
            f"This exact combo exists on Stake under Combos: “{combo.get('stake_market')}”. "
            f"Price is from Stake  -  ~{hit_pct}% model chance."
        ),
        "risk": "high",
        "legs": [leg],
        "total_stake_inr": stake,
        "reserve_inr": reserve,
        "stake_inr": stake,
        "combined_odds": odds,
        "combined_probability": hit_prob,
        "combined_probability_pct": hit_pct,
        "hit_probability": hit_prob,
        "hit_probability_pct": hit_pct,
        "target_return_inr": ret,
        "scenarios": _scenarios_parlay(stake, odds, hit_prob, 1),
        "stake_only": stake_only,
        "expected_value_inr": ev,
        "slip_type": "stake_sgm",
        "verified_stake": True,
        "placement_mode": "stake_sgm",
    }


def _parlay_from_legs(budget, legs_opts: list, comb_odds: float, cp: float, ev: float, stake_only) -> dict:
    n = len(legs_opts)
    stake = _round(min(budget * (0.08 + 0.03 * n), 60))
    reserve = budget - stake
    legs = [
        {**_leg(opt, 0, "parlay_leg", opt.reason), "stake_inr": 0}
        for opt in legs_opts
    ]
    labels = " + ".join(o.label for o in legs_opts)
    profit = round(stake * comb_odds - stake, 0)
    return {
        "id": "parlay",
        "name": " Parlays",
        "description": f"{n}-leg parlay @ {round(comb_odds, 2)}x · {cp:.0%} all hit",
        "why": f"All {n} legs must win. Bigger payout, lower chance than singles.",
        "risk": "high",
        "legs": legs,
        "combined_odds": round(comb_odds, 2),
        "combined_probability_pct": round(cp * 100, 1),
        "stake_inr": stake,
        "total_stake_inr": stake,
        "reserve_inr": reserve,
        "stake_only": stake_only,
        "expected_value_inr": round(stake * ev, 0),
        "scenarios": _scenarios_parlay(stake, comb_odds, cp, n),
    }


def _scenarios_parlay(stake: float, comb_odds: float, cp: float, n_legs: int = 2) -> dict:
    profit = round(stake * comb_odds - stake, 0)
    p_lose = 1 - cp
    return {
        "worst_case": {
            "label": "Misses",
            "profit_inr": -stake,
            "description": f"Combo misses  -  lose {format_inr(stake)}.",
        },
        "likely_case": {
            "label": "Win chance",
            "profit_inr": -stake,
            "description": (
                f"{cp:.0%} chance this combo hits · payout {format_inr(round(stake * comb_odds))}."
            ),
        },
        "best_case": {
            "label": "If it hits",
            "profit_inr": profit,
            "description": payout_text(stake, comb_odds),
        },
        "expected_value_inr": round(stake * (cp * (comb_odds - 1) - (1 - cp)), 0),
        "win_probability_pct": round(cp * 100, 1),
    }


def _option_pool(
    options: list,
    home: str,
    away: str,
    *,
    overlay: dict | None = None,
    require_stake: bool = False,
) -> list:
    """Placeable options: core markets, no traps, optional Stake overlay filter."""
    from bet_placer.data.team_stars import player_goal_eligible
    from bet_placer.engine.stake_odds import option_on_stake, stake_overlay_ready
    from bet_placer.markets.labels import is_core_bet_market

    use_overlay_filter = require_stake and stake_overlay_ready(overlay)
    pool = []
    for o in options:
        if not is_core_bet_market(o.market):
            continue
        if is_generic_trap(o):
            continue
        if o.recommendation == "AVOID":
            continue
        if getattr(o, "ev_pct", 0) < -8:
            continue
        if o.market == "player_goal" and not player_goal_eligible(home, away, o.selection):
            continue
        if use_overlay_filter and not option_on_stake(o.market, o.selection, o.line, overlay):
            continue
        pool.append(o)
    return pool


def _stake_pool(
    options: list, overlay: dict | None, stake_only: bool, home: str, away: str,
    ctx: dict | None = None,
) -> list:
    """All placeable options: Stake lines only, no traps, no heavy negative EV."""
    from bet_placer.engine.stake_odds import stake_lines_usable

    ctx = ctx or {}
    if not stake_lines_usable(overlay, ctx):
        return []
    return _option_pool(options, home, away, overlay=overlay, require_stake=True)


def _model_pool(options: list, home: str, away: str, ctx: dict | None = None) -> list:
    """Model-priced options when Stake lines are not available yet."""
    return _option_pool(options, home, away, require_stake=False)


def _profile_bonus(o, profile: dict) -> float:
    """How well THIS bet fits THIS game's character  -  drives match-specific picks
    so we don't recommend the same favorite double-chance in every game."""
    style = profile.get("style")
    m, sel, line = o.market, o.selection, o.line
    fav = profile.get("favorite", "") or ""
    b = 0.0
    if style == "dominant_favorite":
        if fav and fav in o.label and m in ("match_winner", "double_chance", "draw_no_bet", "asian_handicap"):
            b += 14
    elif style == "high_scoring":
        if m == "over_under_goals" and sel == "over" and line in (1.5, 2.5):
            b += 14
        if m == "btts" and sel == "yes":
            b += 9
    elif style == "low_scoring":
        if m == "over_under_goals" and sel == "under" and line in (2.5, 3.5):
            b += 14
        if m == "btts" and sel == "no":
            b += 9
        if m == "double_chance":
            b += 6
    elif style == "tight":
        if m == "double_chance":
            b += 14
        if m == "draw_no_bet":
            b += 9
        if m == "match_winner" and sel == "draw":
            b -= 8  # don't boost Draw against a sided lean
    elif style == "chaotic":
        if m == "corners" and sel == "over":
            b += 9
        if m == "cards" and sel == "over":
            b += 7
        if m == "over_under_goals" and sel == "over" and line == 2.5:
            b += 6
    return b


def _slip_profile_bonus(slip: dict, profile: dict) -> float:
    total = 0.0
    for leg in slip.get("legs", []):
        total += _profile_bonus(_LegProbe(leg), profile)
    return total


class _LegProbe:
    """Adapt a serialized leg dict back to the attribute shape _profile_bonus wants."""

    def __init__(self, leg: dict):
        self.market = leg.get("market")
        self.selection = leg.get("selection")
        self.line = leg.get("line")
        self.label = leg.get("label", "")


def _score_option(o, profile: dict, home: str, away: str, prefer_core: bool) -> float:
    """Rank: probability first, then EV + market quality (core > props) + game fit."""
    p = o.our_probability
    ev = getattr(o, "ev_pct", 0) / 100.0
    # Cap EV contribution so longshots cannot outrank favorites
    score = p * 55 + min(max(ev, 0), 0.12) * 20
    score += _profile_bonus(o, profile)
    if o.market in CORE_MARKETS:
        score += 15
    # Props are higher variance; penalize unless the match is chaotic.
    if o.market in ("corners", "cards"):
        score -= 6 if profile.get("style") != "chaotic" else 0
    if o.market == "player_goal":
        score += 5 if p >= 0.38 else -5
    if o.market in ("half_time", "team_first_goal", "team_prop"):
        score += 2
    if prefer_core and o.market not in CORE_MARKETS:
        score -= 8
    if getattr(o, "source", "") == "stake":
        score += 3
    if p < 0.55:
        score -= 25
    return score


def _candidates(
    pool: list,
    profile: dict,
    home: str,
    away: str,
    markets: frozenset,
    min_prob: float,
    min_ev: float,
    exclude_keys: set,
    prefer_core: bool = False,
    sort_by: str = "score",
) -> list:
    out = []
    for o in pool:
        key = (o.market, o.selection, o.line)
        if key in exclude_keys:
            continue
        if o.market not in markets:
            continue
        if o.our_probability < min_prob:
            continue
        if getattr(o, "ev_pct", 0) / 100.0 < min_ev:
            if not (o.market in CORE_MARKETS and o.our_probability >= 0.62 and getattr(o, "ev_pct", 0) >= -1):
                continue
        out.append(o)
    if sort_by == "probability":
        out.sort(key=lambda o: (-o.our_probability, -getattr(o, "ev_pct", 0)))
    else:
        out.sort(key=lambda o: -_score_option(o, profile, home, away, prefer_core))
    return out


def _pick_diversified(candidates: list, max_legs: int) -> list:
    picked: list = []
    used_markets: set[str] = set()
    for o in candidates:
        if len(picked) >= max_legs:
            break
        if o.market in used_markets and o.market != "player_goal":
            continue
        picked.append(o)
        used_markets.add(o.market)
    return picked


def _build_multi_leg_slip(
    id_: str,
    name: str,
    why: str,
    pool: list,
    budget: float,
    profile: dict,
    home: str,
    away: str,
    markets: frozenset,
    min_prob: float,
    min_ev: float,
    max_legs: int,
    reserve_pct: float,
    stake_only: bool,
    exclude_keys: set | None = None,
    prefer_core: bool = False,
) -> dict:
    cands = _candidates(
        pool, profile, home, away, markets, min_prob, min_ev,
        exclude_keys or set(), prefer_core=prefer_core,
    )
    picks = _pick_diversified(cands, max_legs)
    if not picks:
        return _empty(id_, name, budget, profile)

    legs: list[dict] = []
    remaining = budget
    reserve = _round(budget * reserve_pct)
    remaining -= reserve

    roles = ["main", "support", "extra"]
    for i, opt in enumerate(picks):
        if remaining < 40:
            break
        share = 0.55 if i == 0 else 0.45 / max(1, len(picks) - 1)
        stake = _round(min(remaining * share, remaining)) if i < len(picks) - 1 else _round(remaining)
        if stake < 20:
            continue
        legs.append(_leg(opt, stake, roles[min(i, 2)], _reason(opt, profile, roles[min(i, 2)]), home, away))
        remaining -= stake

    if not legs:
        return _empty(id_, name, budget, profile)

    reserve += max(0, remaining)
    total = sum(l["stake_inr"] for l in legs)
    ev = _slip_ev({"legs": legs, "scenarios": _scenarios_multi(legs, reserve)})

    return {
        "id": id_,
        "name": name,
        "description": f"{len(legs)} bet{'s' if len(legs) > 1 else ''} · {markets_friendly(markets)}",
        "why": why,
        "risk": "low" if id_ == "safe" else "medium" if id_ in ("goals", "result") else "high",
        "legs": legs,
        "total_stake_inr": total,
        "reserve_inr": reserve,
        "scenarios": _scenarios_multi(legs, reserve),
        "stake_only": stake_only,
        "expected_value_inr": ev,
    }


def _build_parlay_slip(
    pool: list,
    budget: float,
    profile: dict,
    stake_only: bool,
    exclude_keys: set,
    min_leg_prob: float,
    min_combined: float,
) -> dict:
    cands = _candidates(
        pool, profile, "", "", ALL_MARKETS,
        min_leg_prob, 0.0, exclude_keys, prefer_core=True,
    )
    best = None
    best_ev = -999.0
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.market == b.market:
                continue
            cp = a.our_probability * b.our_probability
            if cp < min_combined:
                continue
            comb_odds = a.odds * b.odds
            ev = cp * (comb_odds - 1) - (1 - cp)
            if ev > best_ev:
                best_ev = ev
                best = (cp, a, b, comb_odds)
    if not best or best_ev < 0:
        return _empty("smart_parlay", "Parlays", budget, profile)

    cp, leg1, leg2, comb_odds = best
    stake = _round(min(budget * 0.15, 50))
    reserve = budget - stake
    legs = [
        {**_leg(leg1, 0, "parlay_leg", leg1.reason), "stake_inr": 0},
        {**_leg(leg2, 0, "parlay_leg", leg2.reason), "stake_inr": 0},
    ]
    profit = round(stake * comb_odds - stake, 0)
    return {
        "id": "parlay",
        "name": " Parlays",
        "description": f"{leg1.label} + {leg2.label} @ {round(comb_odds, 2)}x · {cp:.0%} combined",
        "why": "Only when both legs are likely AND the combined chance clears our minimum. Not a random long shot.",
        "risk": "high",
        "legs": legs,
        "combined_odds": round(comb_odds, 2),
        "combined_probability_pct": round(cp * 100, 1),
        "stake_inr": stake,
        "total_stake_inr": stake,
        "reserve_inr": reserve,
        "stake_only": stake_only,
        "expected_value_inr": round(stake * best_ev, 0),
        "scenarios": {
            "worst_case": {"label": "Both wrong", "profit_inr": -stake, "description": f"Lose {format_inr(stake)}."},
            "likely_case": {"label": "Typical", "profit_inr": -stake, "description": f"~{(1-cp)*100:.0f}% chance you lose {format_inr(stake)}."},
            "best_case": {"label": "Both hit", "profit_inr": profit, "description": payout_text(stake, comb_odds)},
            "expected_value_inr": round(stake * best_ev, 0),
        },
    }


def _leg_from_pick(
    pick: dict,
    stake: float,
    role: str,
    reason: str,
    home: str = "",
    away: str = "",
) -> dict:
    from bet_placer.markets.labels import format_ticket_label

    odds = float(pick.get("odds") or 0)
    prob = float(pick.get("our_probability") or 0)
    leg = {
        "market": pick.get("market") or "situation",
        "selection": pick.get("selection") or "",
        "line": pick.get("line"),
        "odds": odds,
        "stake_inr": stake,
        "our_probability": prob,
        "our_probability_pct": round(prob * 100, 1),
        "ev_pct": (pick.get("verdict") or {}).get("ev_pct") or pick.get("edge_pct") or 0,
        "role": role,
        "reason": reason,
        "payout_text": payout_text(stake, odds) if stake > 0 and odds > 1 else "",
        "return_inr": round(stake * odds, 0) if stake > 0 and odds > 1 else 0,
        "odds_source": pick.get("odds_source") or pick.get("source") or "book",
        "live_odds": (pick.get("source") or "") == "stake",
    }
    leg["label"] = format_ticket_label(leg, home, away)
    return leg


def _build_single_from_pick(
    pick: dict,
    id_: str,
    name: str,
    why: str,
    budget: float,
    profile: dict,
    stake_only: bool,
    home: str = "",
    away: str = "",
    *,
    max_stake_pct: float = 0.40,
    min_reserve_pct: float = 0.60,
) -> dict:
    reserve = _round(max(budget * min_reserve_pct, budget * (1 - max_stake_pct)))
    stake = _round(budget - reserve)
    leg = _leg_from_pick(pick, stake, "main", why or pick.get("why") or "Thesis-aligned pick", home, away)
    sc = _scenarios_multi([leg], reserve)
    prob = float(pick.get("our_probability") or 0)
    return {
        "id": id_,
        "name": name,
        "description": f"{leg['label']}  -  {prob:.0%} win chance · stake {format_inr(stake)}",
        "why": why or pick.get("why") or "Aligned with the build-slip thesis.",
        "risk": "medium",
        "legs": [leg],
        "total_stake_inr": stake,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": _slip_ev({"scenarios": sc}),
        "win_probability_pct": round(prob * 100, 1),
        "_unified_aligned": True,
    }


def _build_single_from_option(
    opt,
    id_: str,
    name: str,
    why: str,
    budget: float,
    profile: dict,
    stake_only: bool,
    home: str = "",
    away: str = "",
    *,
    max_stake_pct: float = 0.40,
    min_reserve_pct: float = 0.60,
) -> dict:
    reserve = _round(max(budget * min_reserve_pct, budget * (1 - max_stake_pct)))
    stake = _round(budget - reserve)
    leg = _leg(opt, stake, "main", _reason(opt, profile, "Safest pick"), home, away)
    sc = _scenarios_multi([leg], reserve)
    return {
        "id": id_,
        "name": name,
        "description": f"{leg['label']}  -  {opt.our_probability:.0%} win chance · stake {format_inr(stake)}",
        "why": why,
        "risk": "low" if id_ == "min_loss" else "medium" if id_ == "singles_focus" else "high",
        "legs": [leg],
        "total_stake_inr": stake,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": _slip_ev({"scenarios": sc}),
        "win_probability_pct": round(opt.our_probability * 100, 1),
    }


def _build_single_slip(
    id_: str,
    name: str,
    why: str,
    pool,
    budget,
    profile,
    home,
    away,
    stake_only,
    exclude_keys,
    min_prob: float,
    min_ev: float,
    reserve_pct: float = 0.60,
    prefer_core: bool = True,
) -> dict:
    cands = _candidates(
        pool, profile, home, away, ALL_MARKETS,
        min_prob, min_ev, exclude_keys, prefer_core=prefer_core,
    )
    if not cands:
        return _empty(id_, name, budget, profile)
    opt = cands[0]
    reserve = _round(budget * reserve_pct)
    stake = _round(budget - reserve)
    leg = _leg(opt, stake, "main", _reason(opt, profile, "Best single"), home, away)
    sc = _scenarios_multi([leg], reserve)
    return {
        "id": id_,
        "name": name,
        "description": f"{opt.label}  -  {opt.our_probability:.0%} chance",
        "why": why,
        "risk": "low" if id_ == "min_loss" else "medium" if id_ == "singles_focus" else "high",
        "legs": [leg],
        "total_stake_inr": stake,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": _slip_ev({"scenarios": sc}),
    }


def _single_from_best(pool, budget, profile, home, away, stake_only, exclude_keys, min_prob=SINGLE_MIN_PROB, min_ev=SINGLE_MIN_EV):
    return _build_single_slip(
        "singles_focus", " One best bet",
        "The single highest-quality bet on Stake for this match.",
        pool, budget, profile, home, away, stake_only, exclude_keys,
        min_prob=min_prob, min_ev=min_ev,
    )


def _build_value_slip(pool, budget, profile, home, away, stake_only, exclude_keys, min_prob, min_ev):
    cands = _candidates(pool, profile, home, away, ALL_MARKETS, min_prob, min_ev, exclude_keys, prefer_core=False)
    if not cands:
        return _empty("value", " Value-for-money", budget, profile)
    # pick top 2 by EV-tilted score, diversified by market
    picks = _pick_diversified(cands, 2)
    if not picks:
        return _empty("value", " Value-for-money", budget, profile)
    legs = []
    reserve = _round(budget * 0.10)
    remaining = budget - reserve
    for i, opt in enumerate(picks):
        stake = _round(remaining * (0.6 if i == 0 else 0.4)) if i == 0 else _round(remaining - legs[0]["stake_inr"])
        legs.append(_leg(opt, stake, "main" if i == 0 else "support", _reason(opt, profile, "Value"), home, away))
    total = sum(l["stake_inr"] for l in legs)
    sc = _scenarios_multi(legs, reserve)
    return {
        "id": "value",
        "name": " Value-for-money",
        "description": "Higher payout picks that are still worth the risk on this match.",
        "why": "This tab is where we take calculated risk: higher EV, lower win% than the loss-minimizing tab.",
        "risk": "high",
        "legs": legs,
        "total_stake_inr": total,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": _slip_ev({"scenarios": sc}),
    }


def _strategy_learning_weights() -> dict[str, float]:
    try:
        from bet_placer.ml.params import load_params
        return (load_params().get("rec_learning") or {}).get("strategy_weights") or {}
    except Exception:
        return {}


def _weighted_slip_score(slip: dict) -> float:
    w = _strategy_learning_weights()
    tab = slip.get("tab_id") or slip.get("id") or ""
    base = tab.split("_")[0] if tab else ""
    weight = w.get(tab, w.get(base, 1.0))
    win_p = max((l.get("our_probability", 0) for l in slip.get("legs", [])), default=0)
    return (win_p * 100.0 + _slip_ev(slip) * 0.15) * weight


def _pick_recommended_slip(slips: list[dict], budget: float = 0, profile: dict | None = None) -> dict:
    """Fallback ranker when curation finds nothing."""
    viable = [s for s in slips if s.get("legs") and _is_realistic_slip(s) and _likely_profit(s) >= 0]
    if not viable:
        empty = _empty("skip", "Skip this match", budget, profile or {})
        empty["why"] = "Nothing here wins on the typical outcome  -  skip this match."
        return empty

    singles = [s for s in viable if s.get("tab_id") == "singles_focus" and s.get("_unified_aligned")]
    if singles:
        return max(singles, key=lambda s: (_best_win_prob(s), _weighted_slip_score(s)))

    loss_min = [s for s in viable if s.get("tab_id") == "min_loss" and _qualifies_loss_min(s)]
    if loss_min:
        return max(loss_min, key=_loss_preservation_score)

    match_cards = [s for s in viable if s.get("tab_id") == "match_card"]
    if match_cards:
        return max(match_cards, key=lambda s: (_likely_profit(s), _best_win_prob(s), _weighted_slip_score(s)))

    return max(viable, key=lambda s: (_likely_profit(s), _best_win_prob(s), _weighted_slip_score(s)))


def _slip_ev(slip: dict) -> float:
    if slip.get("expected_value_inr") is not None:
        return float(slip["expected_value_inr"])
    sc = slip.get("scenarios") or {}
    return float(sc.get("expected_value_inr") or 0)


def _leg_keys(slip: dict) -> set:
    if not slip:
        return set()
    return {
        (l["market"], l["selection"], l.get("line"))
        for l in slip.get("legs", [])
        if l.get("stake_inr", 0) > 0 or l.get("role") == "parlay_leg"
    }


def _slip_signature(slip: dict) -> tuple:
    return tuple(sorted(_leg_keys(slip)))


def markets_friendly(markets: frozenset) -> str:
    m = {
        "match_winner": "result", "double_chance": "double chance", "draw_no_bet": "DNB",
        "over_under_goals": "goals", "btts": "BTTS", "asian_handicap": "handicap",
        "player_goal": "scorers", "corners": "corners", "cards": "cards",
    }
    return ", ".join(sorted({m.get(x, x) for x in markets}))


def _scenarios_multi(legs: list[dict], reserve: float) -> dict:
    if not legs:
        return {}
    total = sum(l["stake_inr"] for l in legs)
    probs = [l["our_probability"] for l in legs]
    profits = [l["stake_inr"] * (l["odds"] - 1) for l in legs]
    p_all = math.prod(probs)
    p_at_least_one = 1 - math.prod(1 - p for p in probs)
    # \"Most likely\" outcome is NOT \"at least one wins\" for a slip; for multiple
    # bets it's usually \"exactly one wins\". For a single bet it's win vs lose.
    p_exactly_one = 0.0
    if len(probs) == 1:
        p_exactly_one = probs[0]
    else:
        for i, p in enumerate(probs):
            other = 1.0
            for j, pj in enumerate(probs):
                if i == j:
                    continue
                other *= (1 - pj)
            p_exactly_one += p * other
    ev = sum(p * s * (o - 1) - (1 - p) * s for l in legs for p, s, o in [(l["our_probability"], l["stake_inr"], l["odds"])])

    if len(legs) == 1:
        stake = legs[0]["stake_inr"]
        p = legs[0]["our_probability"]
        win_profit = profits[0]
        lose_profit = -stake
        likely_profit, likely_desc = _single_likely_scenario(p, stake, win_profit, lose_profit)
        likely_label = "If it wins" if p >= COMFORTABLE_WIN else "Win chance"
        if p < COMFORTABLE_WIN:
            likely_desc = f"{p:.0%} chance to win · profit {format_inr(win_profit)} if it lands."
        return {
            "worst_case": {"label": "Lose", "profit_inr": round(lose_profit, 0), "description": f"If it loses (~{1-p:.0%}), you lose {format_inr(stake)}."},
            "likely_case": {"label": likely_label, "profit_inr": round(likely_profit, 0), "description": likely_desc},
            "best_case": {"label": "Win", "profit_inr": round(win_profit, 0), "description": f"If it wins (~{p:.0%}), profit {format_inr(win_profit)}."},
            "expected_value_inr": round(ev, 0),
        }

    # Multi-leg: compare three outcome buckets (all lose / one wins / all win).
    stakes = [l["stake_inr"] for l in legs]
    p_lose_all = math.prod(1 - p for p in probs)
    p_exactly_one = 0.0
    partial_outcomes: list[tuple[float, float, str]] = []
    for i, p_i in enumerate(probs):
        p_only = p_i
        for j, p_j in enumerate(probs):
            if j != i:
                p_only *= (1 - p_j)
        p_exactly_one += p_only
        profit_only = profits[i] - sum(stakes[j] for j in range(len(legs)) if j != i)
        short = legs[i]["label"]
        if len(short) > 36:
            short = short[:33] + "…"
        partial_outcomes.append((
            p_only,
            profit_only,
            f"{short} wins alone (~{p_only:.0%})",
        ))

    best_partial_p, best_partial_profit, best_partial_desc = max(
        partial_outcomes, key=lambda x: x[0],
    )
    outcomes: list[tuple[str, float, float, str]] = [
        (
            "All lose",
            p_lose_all,
            -total,
            f"All miss (~{p_lose_all:.0%}). Lose {format_inr(total)}; keep {format_inr(reserve)}.",
        ),
        (
            "One wins, one loses",
            p_exactly_one,
            best_partial_profit,
            f"Most common (~{p_exactly_one:.0%}): one leg wins, one loses  -  usually {best_partial_desc}.",
        ),
        (
            "All win",
            p_all,
            sum(profits),
            f"Every leg hits (~{p_all:.0%}). Profit {format_inr(sum(profits))}.",
        ),
    ]

    likely_label, likely_p, likely_profit, likely_desc = max(outcomes, key=lambda x: x[1])
    if likely_label == "One wins, one loses" and likely_profit < 0:
        likely_desc = (
            f"Typical (~{likely_p:.0%}): one leg wins, one loses  -  "
            f"net {format_inr(likely_profit)}."
        )

    likely_label_out = "Typical result" if likely_profit < 0 else "Typical result"

    return {
        "worst_case": {"label": "All lose", "profit_inr": round(-total, 0), "description": outcomes[0][3]},
        "likely_case": {
            "label": likely_label_out,
            "profit_inr": round(likely_profit, 0),
            "description": likely_desc,
        },
        "best_case": {"label": "All win", "profit_inr": round(sum(profits), 0), "description": outcomes[-1][3]},
        "expected_value_inr": round(ev, 0),
    }


def _reason(opt, profile: dict, role: str) -> str:
    pct = round(float(opt.our_probability or 0) * 100)
    label = getattr(opt, "label", None) or ""
    if role.lower() in ("anchor", "support"):
        return f"{label}: insurance angle, about {pct}% to land."
    if role.lower() in ("target_lotto", "route"):
        return f"{label}: profit route, about {pct}% to land."
    return f"{label}: about {pct}% to land."


def _leg(opt, stake: float, role: str, reason: str, home: str = "", away: str = "") -> dict:
    from bet_placer.markets.labels import format_ticket_label

    src = getattr(opt, "source", "book")
    our_p = float(opt.our_probability or 0)
    odds = float(opt.odds or 1)
    # Goalscorer UI: never show model % wildly above what Stake odds imply.
    if opt.market == "player_goal" and odds > 1.01:
        book_impl = 1.0 / odds
        our_p = min(our_p, book_impl * 1.35)
    leg = {
        "market": opt.market,
        "selection": opt.selection,
        "line": opt.line,
        "odds": opt.odds,
        "stake_inr": stake,
        "our_probability": our_p,
        "our_probability_pct": round(our_p * 100, 1),
        "ev_pct": getattr(opt, "ev_pct", 0),
        "role": role,
        "reason": reason,
        "payout_text": payout_text(stake, opt.odds) if stake > 0 else "",
        "return_inr": round(stake * opt.odds, 0) if stake > 0 else 0,
        "odds_source": src,
        "live_odds": src == "stake",
    }
    leg["label"] = format_ticket_label(leg, home, away)
    return leg


def _empty(id_: str, name: str, budget: float, profile: dict) -> dict:
    return {
        "id": id_, "name": name, "description": "No qualifying bets for this slip.",
        "legs": [], "total_stake_inr": 0, "reserve_inr": budget,
        "scenarios": {}, "why": profile.get("narrative", "Keep your money."),
    }


def _round(n: float) -> float:
    return max(20, round(n / 10) * 10)


def format_inr(n: float) -> str:
    return f"₹{int(round(n)):,}"
