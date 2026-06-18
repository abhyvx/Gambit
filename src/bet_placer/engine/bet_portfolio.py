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

# ── Intuitive win-chance tiers (we never treat 50% as “good enough to bet”) ──
COMFORTABLE_WIN = 0.58       # minimum “I’d consider this” — clearly better than a coin flip
CONFIDENT_WIN = 0.62         # loss-min tab — genuinely safer side
STRONG_WIN = 0.68            # very high confidence label

# ── Loss-min tab: preserve capital first (NOT profit-max) ──
LOSS_MIN_LEG_MIN_PROB = CONFIDENT_WIN       # 62%+ per leg in a spread
LOSS_MIN_SINGLE_MIN_PROB = STRONG_WIN         # singles only at 68%+ confidence
LOSS_MIN_SPREAD_MAX_RISK_PCT = 0.28           # deploy ≤28% across spread legs
LOSS_MIN_SPREAD_MIN_RESERVE_PCT = 0.72        # keep ≥72% untouched
LOSS_MIN_SINGLE_MAX_STAKE_PCT = 0.18          # confident single: tiny stake
LOSS_MIN_SINGLE_MIN_RESERVE_PCT = 0.82        # keep ≥82% if we dare use a single
LOSS_MIN_MIN_EV = -0.01                       # tiny -EV ok if it protects bankroll

SINGLE_MIN_PROB = COMFORTABLE_WIN   # one best bet: at least 58%
SINGLE_MIN_EV = 0.0

VALUE_MIN_PROB = 0.42               # value tab accepts more risk, but not coin-flip territory
VALUE_MIN_EV = 0.02

PARLAY_MIN_LEG = 0.52
PARLAY_MIN_COMBINED = 0.12
PARLAY_MAX_LEGS = 4
MAX_OPTIONS_PER_TAB = 5

ALL_MARKETS = frozenset({
    "match_winner", "double_chance", "draw_no_bet",
    "over_under_goals", "btts", "asian_handicap",
    "corners", "cards", "player_goal",
})
CORE_MARKETS = frozenset({
    "match_winner", "double_chance", "draw_no_bet",
    "over_under_goals", "btts", "asian_handicap",
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

    ctx = human_context or {}
    overlay = ctx.get("stake_overlay")
    stake_only = bool(overlay and overlay.get("available"))

    pool = _stake_pool(options, overlay, stake_only)
    if not pool:
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = "No Stake markets pass our safety filters for this game — keep your money."
        empty["skip_recommended"] = True
        return _portfolio_result(empty, [], profile, stake_only, live_h2h_odds, skip_recommended=True)

    strategy_plans = {
        "min_loss": _build_min_loss_alternatives(
            pool, budget_inr, profile, home, away, stake_only,
        ),
    }
    used = _used_keys_from_plans(strategy_plans)

    strategy_plans["singles_focus"] = _build_single_alternatives(
        pool, budget_inr, profile, home, away, stake_only, exclude_keys=used,
    )
    used |= _used_keys_from_plans({"s": strategy_plans["singles_focus"]})

    strategy_plans["value"] = _build_value_alternatives(
        pool, budget_inr, profile, home, away, stake_only, exclude_keys=used,
    )
    used |= _used_keys_from_plans({"s": strategy_plans["value"]})

    strategy_plans["smart_parlay"] = _build_parlay_alternatives(
        pool, budget_inr, profile, stake_only,
        exclude_keys=set(),  # parlays are their own plan — don't drain the leg pool
    )

    caution, caution_reason = _assess_match_caution(strategy_plans)

    if _should_skip_match(strategy_plans):
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = caution_reason or (
            "We checked spreads, singles, and parlays — nothing clears our bar. "
            "Keep your full budget for this game."
        )
        empty["skip_recommended"] = True
        return _portfolio_result(empty, [], profile, stake_only, live_h2h_odds, skip_recommended=True, skip_reason=empty["why"])

    bet_slips = [
        plans[0]
        for key in ("min_loss", "singles_focus", "value", "smart_parlay")
        for plans in [strategy_plans.get(key, [])]
        if plans
    ]

    have_non_parlay = any(
        strategy_plans.get(k) for k in ("min_loss", "singles_focus", "value")
    )
    if not have_non_parlay:
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = "Nothing on Stake clears our probability + value checks — skip this match."
        empty["skip_recommended"] = True
        return _portfolio_result(empty, [], profile, stake_only, live_h2h_odds, skip_recommended=True)

    bet_slips = [s for s in bet_slips if _slip_ev(s) >= -5]
    if not bet_slips:
        empty = _empty("skip", "Skip this match", budget_inr, profile)
        empty["why"] = "Nothing on Stake clears our safety + value checks for this game — keep your money."
        empty["skip_recommended"] = True
        return _portfolio_result(empty, [], profile, stake_only, live_h2h_odds, skip_recommended=True)

    recommended = _pick_recommended_slip(bet_slips)
    return _portfolio_result(
        recommended,
        bet_slips,
        profile,
        stake_only,
        live_h2h_odds,
        strategies=strategy_plans,
        skip_recommended=caution,
        skip_reason=caution_reason,
    )


def _portfolio_result(recommended, bet_slips, profile, stake_only, live_h2h_odds, strategies=None, skip_recommended=False, skip_reason=None):
    rec = recommended if isinstance(recommended, dict) and recommended.get("legs") else (bet_slips[0] if bet_slips else recommended)
    rec_id = rec.get("tab_id") or rec.get("id", "min_loss")
    strat = strategies or {
        "min_loss": [rec] if rec.get("legs") else [],
        "singles_focus": [],
        "value": [],
        "smart_parlay": [],
    }
    # Legacy single-object views (first option per tab)
    legacy = {
        key: (_first_plan(strat, key) or _empty(key, key, 0, profile))
        for key in ("min_loss", "singles_focus", "value", "smart_parlay")
    }
    skip_reason = skip_reason or (
        (recommended.get("why") if isinstance(recommended, dict) else None)
        if skip_recommended or rec_id == "skip" else None
    ) or (
        "Most likely outcome is losing money — we recommend skipping this match."
        if skip_recommended else None
    )
    return {
        "recommended_strategy": rec_id if rec_id in ("min_loss", "safe", "singles_focus", "value", "smart_parlay", "skip") else "min_loss",
        "recommended_slip_id": rec.get("option_id") or rec.get("id"),
        "skip_recommended": bool(skip_recommended or rec_id == "skip"),
        "skip_reason": skip_reason,
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
        "portfolio_engine": "spread_loss_min_v2",
        "odds_note": (
            "Each slip uses only markets Stake lists for this game, at Stake's real prices."
            if stake_only else
            "Couldn't confirm Stake — verify every pick exists before betting."
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
    is_parlay = slip.get("id") == "parlay" or any(l.get("role") == "parlay_leg" for l in legs)
    n = len(legs)
    if is_parlay:
        slip_type, slip_type_label = "parlay", f"Parlay · {n} legs"
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
        f"Option {option_index} · Recommended"
        if recommended and option_index == 1
        else f"Option {option_index} · Alternative"
    )
    out["option_summary"] = " · ".join(
        l.get("label", "") for l in legs[:3]
    ) + (f" +{len(legs) - 3} more" if len(legs) > 3 else "")
    if legs:
        out["win_probability_pct"] = round(_best_win_prob(out) * 100, 1)
        out["confidence_label"] = _confidence_label(_best_win_prob(out))
    return out


def _likely_profit(slip: dict) -> float:
    sc = slip.get("scenarios") or {}
    return float((sc.get("likely_case") or {}).get("profit_inr", -999))


def _should_skip_match(strategy_plans: dict) -> bool:
    """Skip when no plan clears our comfort bar with +EV."""
    core = ("min_loss", "singles_focus", "value", "smart_parlay")
    all_plans = [p for tab in core for p in strategy_plans.get(tab, [])]
    if not all_plans:
        return True
    good = [
        p for p in all_plans
        if _best_win_prob(p) >= COMFORTABLE_WIN and _likely_profit(p) >= 0 and _slip_ev(p) >= 0
    ]
    return len(good) == 0


def _assess_match_caution(strategy_plans: dict) -> tuple[bool, str | None]:
    """Return (show_caution, reason). Honest flags — not every match is worth betting."""
    min_loss = strategy_plans.get("min_loss") or []
    singles = strategy_plans.get("singles_focus") or []
    value = strategy_plans.get("value") or []

    if not min_loss:
        if not singles and not value:
            return True, "No safe spread and no singles — skip unless you love the parlay risk."
        return True, "No capital-preservation spread — only higher-risk singles/value below."

    core = [p for tab in ("min_loss", "singles_focus", "value") for p in strategy_plans.get(tab, [])]
    if core and max(_likely_profit(p) for p in core) < 0:
        return True, "Even our best plan's most-likely outcome is a loss — bet small or skip."

    return False, None


def _skip_caution(strategy_plans: dict) -> bool:
    """Deprecated alias."""
    caution, _ = _assess_match_caution(strategy_plans)
    return caution


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
    """Most-likely case for a single — never use 50% as the comfort bar."""
    if p >= CONFIDENT_WIN:
        return win_profit, f"Most likely: wins (~{p:.0%} chance) — {_confidence_label(p)}."
    if p >= COMFORTABLE_WIN:
        return win_profit, (
            f"Likely wins (~{p:.0%}), but {1 - p:.0%} of the time you still lose {format_inr(stake)}."
        )
    return lose_profit, (
        f"Most likely: loses (~{1 - p:.0%} miss rate). "
        f"Below our {COMFORTABLE_WIN:.0%} minimum — not worth your money."
    )


def _best_win_prob(slip: dict) -> float:
    legs = slip.get("legs") or []
    if not legs:
        return 0.0
    return max(l.get("our_probability", 0) for l in legs)


def _prob_all_legs_lose(legs: list[dict]) -> float:
    if not legs:
        return 1.0
    return math.prod(1 - l.get("our_probability", 0) for l in legs)


def _combo_contradicts(picks: tuple) -> bool:
    """Drop combos that fight each other on the same match."""
    labels = " ".join(p.label.lower() for p in picks)
    markets = [p.market for p in picks]
    if markets.count("over_under_goals") > 1:
        return True
    if "over" in labels and "under" in labels and "over_under_goals" in markets:
        return True
    if "btts" in markets and "over_under_goals" in markets:
        ou = next((p for p in picks if p.market == "over_under_goals"), None)
        btts = next((p for p in picks if p.market == "btts"), None)
        if ou and btts:
            if ou.selection == "under" and btts.selection == "yes":
                return True
            if ou.selection == "over" and ou.line and ou.line <= 1.5 and btts.selection == "no":
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
                f"Every bet loses (~{p_all_lose:.0%}) — down {format_inr(total)}, "
                f"but you still keep {format_inr(reserve)} unbet."
            ),
        },
        "likely_case": {
            "label": "Most likely",
            "profit_inr": round(ev, 0),
            "description": (
                f"~{p_at_least_one:.0%} chance at least one wins — "
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
        _leg(opt, stake_each, roles[min(i, 2)], _reason(opt, profile, "Safe leg"))
        for i, opt in enumerate(picks)
    ]
    labels = ", ".join(p.label for p in picks)
    sc = _scenarios_loss_min_spread(legs, reserve)
    min_p = min(p.our_probability for p in picks)
    return {
        "id": "min_loss",
        "name": "📉 Loss-minimizing",
        "description": f"{n} small bets · {labels}",
        "why": (
            f"Spread {format_inr(total)} across {n} likely picks ({min_p:.0%}+ each). "
            f"Keep {format_inr(reserve)} ({reserve / budget:.0%} of budget) untouched — "
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
) -> list[dict]:
    """Loss-min: spread-only (2–3 small stakes). No singles — those live on One best bet."""
    cands = _candidates(
        pool, profile, home, away, CORE_MARKETS,
        LOSS_MIN_LEG_MIN_PROB, LOSS_MIN_MIN_EV, set(),
        prefer_core=True, sort_by="probability",
    )[:12]
    alts: list[dict] = []

    for n_legs in (2, 3):
        for combo in combinations(cands, n_legs):
            if len({c.market for c in combo}) < n_legs:
                continue
            if _combo_contradicts(combo):
                continue
            slip = _build_loss_min_spread(combo, budget, profile, stake_only)
            if _qualifies_loss_min(slip):
                alts.append(slip)

    alts = _dedupe_slips(alts)
    # Prefer spreads that fit THIS game's character; safety breaks ties so we
    # still never sacrifice capital preservation just to look different.
    alts.sort(key=lambda s: (_slip_profile_bonus(s, profile), _loss_preservation_score(s)), reverse=True)
    return alts[:MAX_OPTIONS_PER_TAB]


def _build_min_loss_alternatives(pool, budget, profile, home, away, stake_only) -> list[dict]:
    """Loss-min: spread-only. Empty if no safe spread exists."""
    candidates = _enumerate_loss_min_options(pool, budget, profile, home, away, stake_only)
    if not candidates:
        return []
    return [
        _annotate_slip(s, "min_loss", i + 1, recommended=(i == 0))
        for i, s in enumerate(candidates)
    ]


def _build_single_alternatives(pool, budget, profile, home, away, stake_only, exclude_keys=None) -> list[dict]:
    candidates = _enumerate_singles(
        pool, budget, profile, home, away, stake_only,
        "singles_focus", "🎯 One best bet",
        "One clear single where the edge is worth the stake.",
        SINGLE_MIN_PROB, SINGLE_MIN_EV, 0.55, True,
        require_positive_ev=True,
        min_win_prob=COMFORTABLE_WIN,
        initial_exclude=exclude_keys,
    )
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
    """Value tab: diverse singles + 2/3-leg independent combos (not parlays)."""
    ex = exclude_keys or set()
    raw: list[dict] = []

    raw.extend(_enumerate_singles(
        pool, budget, profile, home, away, stake_only,
        "value", "💰 Value-for-money",
        "Best single where the payout is worth the risk.",
        VALUE_MIN_PROB, VALUE_MIN_EV, 0.55, False,
        require_positive_ev=True,
        max_n=3,
        initial_exclude=ex,
    ))

    cands = _candidates(
        pool, profile, home, away, ALL_MARKETS,
        VALUE_MIN_PROB, VALUE_MIN_EV, ex, prefer_core=False,
    )[:12]
    for n_legs in (2, 3):
        for combo in combinations(cands, n_legs):
            if len({c.market for c in combo}) < len(combo):
                continue
            slip = _build_multi_from_picks(
                combo, "value", "💰 Value-for-money",
                f"{n_legs} independent bets — higher payout, more ways to lose part of the stake.",
                budget, profile, 0.12, stake_only,
            )
            if slip.get("legs") and _slip_ev(slip) > 0:
                raw.append(slip)

    raw = _dedupe_slips(raw)
    raw.sort(key=lambda s: (_likely_profit(s) < 0, -_slip_ev(s), -_likely_profit(s)))
    return [
        _annotate_slip(s, "value", i + 1, recommended=(i == 0))
        for i, s in enumerate(raw[:MAX_OPTIONS_PER_TAB])
    ]


def _build_parlay_alternatives(pool, budget, profile, stake_only, exclude_keys=None, max_n: int = MAX_OPTIONS_PER_TAB) -> list[dict]:
    ex = exclude_keys or set()
    cands = _candidates(
        pool, profile, "", "", ALL_MARKETS,
        PARLAY_MIN_LEG, 0.0, ex, prefer_core=True,
    )[:14]
    scored: list[tuple] = []
    for n in range(2, min(PARLAY_MAX_LEGS, len(cands)) + 1):
        for combo in combinations(cands, n):
            if len({c.market for c in combo}) < len(combo):
                continue
            cp = math.prod(c.our_probability for c in combo)
            if cp < PARLAY_MIN_COMBINED:
                continue
            comb_odds = math.prod(c.odds for c in combo)
            ev = cp * (comb_odds - 1) - (1 - cp)
            if ev <= 0:
                continue
            scored.append((ev, cp, combo, comb_odds))

    scored.sort(key=lambda x: x[0], reverse=True)
    alts: list[dict] = []
    seen: set = set()
    for ev, cp, combo, comb_odds in scored:
        key = tuple(sorted((c.market, c.selection, c.line) for c in combo))
        if key in seen:
            continue
        seen.add(key)
        slip = _parlay_from_legs(budget, list(combo), comb_odds, cp, ev, stake_only)
        alts.append(_annotate_slip(slip, "smart_parlay", len(alts) + 1, recommended=(len(alts) == 0)))
        if len(alts) >= max_n:
            break
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
        legs.append(_leg(opt, stake, roles[min(i, 2)], _reason(opt, profile, roles[min(i, 2)])))
        remaining -= stake
    if not legs:
        return _empty(id_, name, budget, profile)
    reserve += max(0, remaining)
    total = sum(l["stake_inr"] for l in legs)
    sc = _scenarios_multi(legs, reserve)
    labels = ", ".join(p.label for p in picks[:3])
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
        "name": "🔗 Parlays",
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
            "label": "Miss",
            "profit_inr": -stake,
            "description": f"At least one leg misses — lose {format_inr(stake)}.",
        },
        "likely_case": {
            "label": "Most likely",
            "profit_inr": -stake,
            "description": (
                f"Most likely: parlay misses (~{p_lose:.0%}). "
                f"All {n_legs} legs must hit ({cp:.0%} chance)."
            ),
        },
        "best_case": {
            "label": "All hit",
            "profit_inr": profit,
            "description": payout_text(stake, comb_odds),
        },
        "expected_value_inr": round(stake * (cp * (comb_odds - 1) - (1 - cp)), 0),
    }


def _stake_pool(options: list, overlay: dict | None, stake_only: bool) -> list:
    """All placeable options: Stake-filtered, no traps, no heavy negative EV."""
    from bet_placer.engine.stake_odds import option_on_stake

    pool = []
    for o in options:
        if is_generic_trap(o):
            continue
        if o.recommendation == "AVOID":
            continue
        if getattr(o, "ev_pct", 0) < -3:
            continue
        if stake_only and overlay and not option_on_stake(o.market, o.selection, o.line, overlay):
            continue
        pool.append(o)
    return pool


def _profile_bonus(o, profile: dict) -> float:
    """How well THIS bet fits THIS game's character — drives match-specific picks
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
            b += 5
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
    """Rank: probability + EV + market quality (core > props) + game fit."""
    p = o.our_probability
    ev = getattr(o, "ev_pct", 0) / 100.0
    score = p * 40 + ev * 25
    score += _profile_bonus(o, profile)
    if o.market in CORE_MARKETS:
        score += 15
    # Props are higher variance; penalize unless the match is chaotic.
    if o.market in ("corners", "cards"):
        score -= 12 if profile.get("style") != "chaotic" else 0
    if o.market == "player_goal":
        score += 5 if p >= 0.38 else -5
    if prefer_core and o.market not in CORE_MARKETS:
        score -= 20
    if getattr(o, "source", "") == "stake":
        score += 3
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
        legs.append(_leg(opt, stake, roles[min(i, 2)], _reason(opt, profile, roles[min(i, 2)])))
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
        "name": "🔗 Parlays",
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


def _build_single_from_option(
    opt,
    id_: str,
    name: str,
    why: str,
    budget: float,
    profile: dict,
    stake_only: bool,
    *,
    max_stake_pct: float = 0.40,
    min_reserve_pct: float = 0.60,
) -> dict:
    reserve = _round(max(budget * min_reserve_pct, budget * (1 - max_stake_pct)))
    stake = _round(budget - reserve)
    leg = _leg(opt, stake, "main", _reason(opt, profile, "Safest pick"))
    sc = _scenarios_multi([leg], reserve)
    return {
        "id": id_,
        "name": name,
        "description": f"{opt.label} — {opt.our_probability:.0%} win chance · stake {format_inr(stake)}",
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
    leg = _leg(opt, stake, "main", _reason(opt, profile, "Best single"))
    sc = _scenarios_multi([leg], reserve)
    return {
        "id": id_,
        "name": name,
        "description": f"{opt.label} — {opt.our_probability:.0%} chance",
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
        "singles_focus", "🎯 One best bet",
        "The single highest-quality bet on Stake for this match.",
        pool, budget, profile, home, away, stake_only, exclude_keys,
        min_prob=min_prob, min_ev=min_ev,
    )


def _build_value_slip(pool, budget, profile, home, away, stake_only, exclude_keys, min_prob, min_ev):
    cands = _candidates(pool, profile, home, away, ALL_MARKETS, min_prob, min_ev, exclude_keys, prefer_core=False)
    if not cands:
        return _empty("value", "💰 Value-for-money", budget, profile)
    # pick top 2 by EV-tilted score, diversified by market
    picks = _pick_diversified(cands, 2)
    if not picks:
        return _empty("value", "💰 Value-for-money", budget, profile)
    legs = []
    reserve = _round(budget * 0.10)
    remaining = budget - reserve
    for i, opt in enumerate(picks):
        stake = _round(remaining * (0.6 if i == 0 else 0.4)) if i == 0 else _round(remaining - legs[0]["stake_inr"])
        legs.append(_leg(opt, stake, "main" if i == 0 else "support", _reason(opt, profile, "Value")))
    total = sum(l["stake_inr"] for l in legs)
    sc = _scenarios_multi(legs, reserve)
    return {
        "id": "value",
        "name": "💰 Value-for-money",
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


def _pick_recommended_slip(slips: list[dict]) -> dict:
    loss_min = next(
        (s for s in slips if s.get("tab_id") == "min_loss" or s.get("id") == "min_loss"),
        None,
    )
    if loss_min and _qualifies_loss_min(loss_min):
        return loss_min
    min_loss_candidates = [
        s for s in slips
        if (s.get("tab_id") == "min_loss" or s.get("id") == "min_loss") and s.get("legs")
    ]
    if min_loss_candidates:
        return max(min_loss_candidates, key=_loss_preservation_score)
    pos = [
        s for s in slips
        if s.get("tab_id") in ("min_loss", "singles_focus", "value")
        or s.get("id") in ("min_loss", "singles_focus", "value")
        if _slip_ev(s) > 0
    ]
    if pos:
        return max(pos, key=lambda s: (_best_win_prob(s), _slip_ev(s)))
    if loss_min and loss_min.get("legs"):
        return loss_min
    return max(slips, key=lambda s: (_best_win_prob(s), _slip_ev(s)))


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
        return {
            "worst_case": {"label": "Lose", "profit_inr": round(lose_profit, 0), "description": f"If it loses (~{1-p:.0%}), you lose {format_inr(stake)}."},
            "likely_case": {"label": "Most likely", "profit_inr": round(likely_profit, 0), "description": likely_desc},
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
            f"Most common (~{p_exactly_one:.0%}): one leg wins, one loses — usually {best_partial_desc}.",
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
            f"Most common (~{likely_p:.0%}): one leg wins, one loses — "
            f"net loss {format_inr(abs(likely_profit))}. Try a single-bet option above."
        )

    return {
        "worst_case": {"label": "All lose", "profit_inr": round(-total, 0), "description": outcomes[0][3]},
        "likely_case": {
            "label": "Most likely",
            "profit_inr": round(likely_profit, 0),
            "description": likely_desc,
        },
        "best_case": {"label": "All win", "profit_inr": round(sum(profits), 0), "description": outcomes[-1][3]},
        "expected_value_inr": round(ev, 0),
    }


def _reason(opt, profile: dict, role: str) -> str:
    return f"{role}: {opt.our_probability:.0%} likely — {opt.reason}"


def _leg(opt, stake: float, role: str, reason: str) -> dict:
    src = getattr(opt, "source", "book")
    return {
        "label": opt.label,
        "market": opt.market,
        "selection": opt.selection,
        "line": opt.line,
        "odds": opt.odds,
        "stake_inr": stake,
        "our_probability": opt.our_probability,
        "our_probability_pct": round(opt.our_probability * 100, 1),
        "ev_pct": getattr(opt, "ev_pct", 0),
        "role": role,
        "reason": reason,
        "payout_text": payout_text(stake, opt.odds) if stake > 0 else "",
        "return_inr": round(stake * opt.odds, 0) if stake > 0 else 0,
        "odds_source": src,
        "live_odds": src == "stake",
    }


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
