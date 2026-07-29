"""Target-cashout planner — find bet combinations that reach a payout goal.

Uses scraped Stake odds for singles and only lists same-game multis that exist
as pre-built Stake combo markets (never multiplies single-line odds).
"""

from __future__ import annotations

import math
from itertools import combinations

from bet_placer.engine.bet_portfolio import (
    _combo_contradicts,
    _leg,
    _model_pool,
    _reason,
    _round,
    _scenarios_multi,
    _stake_pool,
    format_inr,
)
from bet_placer.engine.game_profile import profile_match

MIN_STAKE = 20
MAX_PLANS = 12
MAX_SPLIT_LEGS = 10
MAX_COVERAGE_LEGS = 12
MAX_COMBO_TRIES = 80
MIN_LEG_PROB = 0.12
MIN_WORTH_PROB = 0.22


def build_target_plans(
    options: list,
    budget_inr: float,
    target_cashout_inr: float,
    home: str,
    away: str,
    match=None,
    probabilities=None,
    human_context: dict | None = None,
) -> dict:
    """Return ranked plans to reach *target_cashout_inr* gross payout within *budget_inr*."""
    ctx = human_context or {}
    betting_style = ctx.get("betting_style") or {}
    profile = profile_match(match, probabilities or [], ctx) if match else {
        "style": "balanced", "narrative": "", "min_bet_probability": 0.5,
    }
    overlay = ctx.get("stake_overlay")
    from bet_placer.engine.stake_odds import stake_lines_usable

    stake_only = stake_lines_usable(overlay, ctx)
    if overlay:
        from bet_placer.engine.stake_odds import reprice_options_from_overlay, inject_goalscorer_options
        reprice_options_from_overlay(options, overlay, home, away)
        inject_goalscorer_options(options, overlay, home, away)
    ctx = {**ctx, "_all_options": options}
    pool = (
        _stake_pool(options, overlay, stake_only, home, away, ctx=ctx)
        if stake_only else
        _model_pool(options, home, away, ctx=ctx)
    )
    if not pool and stake_only:
        pool = _model_pool(options, home, away, ctx=ctx)
        stake_only = False

    target = max(float(target_cashout_inr), float(budget_inr) + 1)
    budget = max(float(budget_inr), MIN_STAKE)
    ctx = {**ctx, "target_cashout_inr": target}

    if not pool:
        return _result(
            budget, target, [], impossible=True,
            reason="No markets available to build a cashout path for this match.",
            stake_only=stake_only, profile=profile,
        )

    all_options = list(options)
    max_return = _max_achievable_return(
        pool, budget, overlay, all_options=all_options, home=home, away=away,
    )

    plans: list[dict] = []
    target_hit = bool(ctx.get("target_hit_mode"))
    mult = target / max(budget, 1)
    combo_cap = 10 if target_hit else (6 if mult >= 8 else 4 if mult >= 5 else 3)

    if target_hit:
        # Multi-ticket stacks first — 3+ separate Stake slips, one sized to hit target.
        plans.extend(_search_ticket_stack(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:16])
        plans.extend(_search_target_hit_routes(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:12])
        plans.extend(_search_coverage(
            pool, budget, target, profile, stake_only, ctx, betting_style, home, away,
        )[:12])
        plans.extend(_search_spray_routes(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:12])
        plans.extend(_search_moderate_sgm_portfolio(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:8])
        plans.extend(_search_build_slip_routes(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:10])
        plans.extend(_search_volume_singles(
            pool, budget, target, profile, stake_only, ctx, betting_style, home, away,
        )[:8])
        if combo_cap:
            plans.extend(_search_combo_routes(
                pool, budget, target, profile, stake_only, ctx, home, away,
            )[:max(2, combo_cap // 2)])
    else:
        if combo_cap:
            plans.extend(_search_combo_routes(
                pool, budget, target, profile, stake_only, ctx, home, away,
            )[:combo_cap])
        plans.extend(_search_moderate_sgm_portfolio(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:4])
        plans.extend(_search_spread_portfolio(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:12])
        plans.extend(_search_build_slip_routes(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:15])
        plans.extend(_search_match_card_variants(
            pool, budget, target, profile, stake_only, ctx, home, away, max_variants=10,
        ))
        plans.extend(_search_target_hit_routes(
            pool, budget, target, profile, stake_only, ctx, home, away,
        )[:12])
        plans.extend(_search_coverage(
            pool, budget, target, profile, stake_only, ctx, betting_style, home, away,
        )[:12])
        plans.extend(_search_volume_singles(
            pool, budget, target, profile, stake_only, ctx, betting_style, home, away,
        )[:10])
    # ponytail: split = all legs must win — wrong semantics for hit-target (use spread card)
    if not target_hit:
        plans.extend(_search_splits(pool, budget, target, profile, stake_only, ctx, home, away)[:6])
    plans.extend(_search_stake_combos(
        overlay, budget, target, stake_only, pool=pool, home=home, away=away, ctx=ctx,
    )[:8 if target_hit else 6])
    plans.extend(_search_singles(pool, budget, target, profile, stake_only, ctx, home, away)[:4])

    plans = _sanitize_plans(plans)
    from bet_placer.engine.card_coherence import path_is_coherent

    plans = [p for p in plans if path_is_coherent(p.get("legs") or [], home, away)]
    plans = _dedupe_plans(plans)
    thesis = ctx.get("match_thesis")
    if thesis:
        from bet_placer.engine.card_coherence import filter_plans_by_thesis
        filtered = filter_plans_by_thesis(plans, None, thesis, home, away)
        if filtered:
            plans = filtered
        plans = [p for p in plans if not _plan_fights_thesis(p, thesis, home, away)]
    for p in plans:
        p.update(_plan_profit_summary(p, budget, target))
    winnable = [p for p in plans if (p.get("win_probability") or 0) > 0]
    if winnable:
        plans = winnable
    plans = _prefer_probable_spreads(plans)
    if max_return < target and not plans:
        return _result(
            budget, target, [], impossible=True,
            reason=(
                f"No combination of available markets can return {format_inr(target)} "
                f"within {format_inr(budget)}. Best possible gross payout is "
                f"{format_inr(max_return)}."
            ),
            max_achievable_inr=max_return,
            stake_only=stake_only, profile=profile,
        )

    plans = [_score_plan_worth(p, ctx, betting_style) for p in plans]
    plans.sort(key=lambda p: _rank_key(p, ctx), reverse=True)
    plans = _pick_ranked_plans(plans, MAX_PLANS, ctx)
    plans = [_annotate_plan(p, i + 1, home, away, budget=budget, target=target) for i, p in enumerate(plans)]
    # Re-sort after ticket_count is known — separate Stake slips beat one parlay in target mode.
    target_hit = bool(ctx.get("target_hit_mode"))
    plans.sort(
        key=lambda p: _display_rank_key(p, target_hit),
        reverse=True,
    )
    for i, p in enumerate(plans):
        p["rank"] = i + 1
        p["option_index"] = i + 1
        p["rank_label"] = f"#{i + 1}" + (" · Best path" if i == 0 else f" · Path {i + 1}")
    placeable = [p for p in plans if (p.get("ticket_count") or 0) > 0]
    if placeable:
        plans = placeable

    return _result(
        budget, target, plans,
        impossible=not plans and max_return < target,
        reason=None if plans else (
            "We found enough payout on the board, but the planner could not assemble a valid route yet."
            if max_return >= target else
            "Could not assemble a valid plan."
        ),
        max_achievable_inr=max_return,
        stake_only=stake_only, profile=profile,
        betting_style=betting_style,
    )


def _max_achievable_return(
    pool: list, budget: float, overlay: dict | None = None,
    all_options: list | None = None,
    home: str = "", away: str = "",
) -> float:
    """Optimistic upper bound from singles, verified combos, and synthetic parlays."""
    search = list(all_options or []) + list(pool)
    best = 0.0
    for o in search:
        odds = getattr(o, "odds", 0) or 0
        if odds > 1:
            best = max(best, budget * odds)
    if overlay:
        for c in overlay.get("stake_combos") or []:
            odds = float(c.get("odds") or 0)
            if odds > 1:
                best = max(best, budget * odds)
    parlay_odds = _optimistic_parlay_odds(search, home, away)
    if parlay_odds > 1:
        best = max(best, budget * parlay_odds)
    return round(best, 0)


def _optimistic_parlay_odds(search: list, home: str, away: str, max_legs: int = 4) -> float:
    """Greedy same-match parlay ceiling from the widest available option set.

    This is only an upper bound for target feasibility, not a verified Stake price.
    """
    cands = [
        o for o in search
        if (getattr(o, "odds", 0) or 0) > 1.01 and (getattr(o, "our_probability", 0) or 0) >= 0.02
    ]
    cands.sort(key=lambda o: (-(getattr(o, "odds", 0) or 0), -(getattr(o, "our_probability", 0) or 0)))
    chosen = []
    for opt in cands:
        if len(chosen) >= max_legs:
            break
        trial = tuple(chosen + [opt])
        try:
            if _combo_contradicts(trial, home, away):
                continue
        except Exception:
            continue
        chosen.append(opt)
    odds = 1.0
    for opt in chosen:
        odds *= float(getattr(opt, "odds", 1.0) or 1.0)
    return odds if len(chosen) >= 2 else 0.0


def _min_stake_for_return(odds: float, target: float) -> float:
    return max(MIN_STAKE, _round_up(target / odds))


def _round_up(n: float) -> float:
    return max(MIN_STAKE, math.ceil(n / 10) * 10)


def _leg_worth_bonus(opt, ctx: dict) -> float:
    """Boost legs the model already likes — easy money / thesis picks."""
    bonus = 0.0
    ev = float(getattr(opt, "ev_pct", 0) or 0)
    if ev > 0:
        bonus += min(0.12, ev * 0.004)
    tier = (getattr(opt, "verdict", None) or {}).get("tier")
    if tier in ("trap", "bad"):
        bonus -= 0.25
    elif tier in ("value", "strong"):
        bonus += 0.06
    labels = {
        (p.get("label") or "").lower()
        for p in (ctx.get("easy_money_picks") or []) + (ctx.get("unified_picks") or [])
    }
    if (opt.label or "").lower() in labels:
        bonus += 0.10
    return bonus


def _wide_pool(pool: list, ctx: dict, stake_only: bool, home: str, away: str) -> list:
    """Longshots and niche markets — same wider pool as match cards."""
    from bet_placer.engine.match_card import _match_card_pool

    overlay = ctx.get("stake_overlay")
    all_opts = ctx.get("_all_options") or pool
    wide = _match_card_pool(all_opts, overlay, stake_only, home, away)
    return wide


def _search_match_card_variants(
    pool, budget, target, profile, stake_only, ctx, home, away, *, max_variants: int = 3,
) -> list[dict]:
    from bet_placer.engine.match_card import build_match_card_variants

    return build_match_card_variants(
        pool, budget, target, profile, home, away, stake_only, ctx,
        max_variants=max_variants,
    )


def _search_build_slip_routes(
    pool, budget, target, profile, stake_only, ctx, home, away,
) -> list[dict]:
    """Reuse the richer build-slip route assembly for target mode."""
    from bet_placer.engine.bet_portfolio import _plan_from_spread_slip
    from bet_placer.engine.match_card import (
        build_balanced_sized_paths,
        build_coherent_match_paths,
        build_target_match_slips,
    )

    seen: set[tuple] = set()
    out: list[dict] = []

    def _sig(plan: dict) -> tuple:
        return tuple(sorted(
            (
                l.get("market"),
                l.get("selection"),
                l.get("line"),
                l.get("role"),
                int(float(l.get("stake_inr") or 0)),
            )
            for l in (plan.get("legs") or [])
        ))

    def _add_slip(slip: dict | None) -> None:
        if not slip:
            return
        plan = _plan_from_spread_slip(slip, target)
        if not plan:
            return
        sig = _sig(plan)
        if not sig or sig in seen:
            return
        seen.add(sig)
        out.append(plan)

    for slip in build_balanced_sized_paths(
        pool, budget, target, profile, home, away, stake_only, ctx,
    ):
        _add_slip(slip)
    for slip in build_target_match_slips(
        pool, budget, target, profile, home, away, stake_only, ctx, max_slips=8,
    ):
        _add_slip(slip)
    for slip in build_coherent_match_paths(
        pool, budget, profile, home, away, stake_only, ctx, max_paths=6, target=target,
    ):
        _add_slip(slip)

    return out


def _sanitize_plans(plans: list) -> list[dict]:
    """Hard block fake same-game multis and all-must-win bundles."""
    allowed = {"match_card", "coverage", "stake_combo", "single", "split", "combo"}
    out: list[dict] = []
    for p in plans:
        if not isinstance(p, dict):
            continue
        ptype = p.get("plan_type")
        if ptype not in allowed:
            continue
        if p.get("placement_mode") == "same_game_multi":
            continue
        legs = p.get("legs") or []
        if ptype != "combo" and any(l.get("role") == "parlay_leg" for l in legs):
            continue
        # Reject fake SGMs — but allow match_card with verified Stake combo legs
        verified_sgm_card = (
            ptype == "match_card"
            and legs
            and all(
                l.get("verified_stake") and l.get("market") == "stake_combo"
                for l in legs
            )
        )
        label = (p.get("plan_type_label") or "").lower()
        headline = (p.get("path_headline") or "").lower()
        if "sgm" in label and ptype != "stake_combo" and not verified_sgm_card:
            continue
        if "same-game multi" in label and ptype != "stake_combo" and not verified_sgm_card:
            continue
        if "sgm" in headline and ptype != "stake_combo" and not verified_sgm_card:
            continue
        if ptype == "stake_combo" and not p.get("verified_stake"):
            continue
        if ptype == "combo" and p.get("combined_odds", 0) <= 1:
            continue
        if ptype in ("match_card", "coverage") and not legs:
            continue
        out.append(p)
    return out


def _search_match_card(pool, budget, target, profile, stake_only, ctx, home, away) -> list[dict]:
    from bet_placer.engine.match_card import build_match_card_plan

    plan = build_match_card_plan(
        pool, budget, target, profile, home, away, stake_only, ctx,
    )
    return [plan] if plan else []


def _search_singles(pool, budget, target, profile, stake_only, ctx, home, away) -> list[dict]:
    from bet_placer.engine.match_card import _aligns_thesis

    out: list[dict] = []
    search = _wide_pool(pool, ctx, stake_only, home, away)
    thesis_side = _thesis_side(ctx)
    for opt in sorted(search, key=lambda o: (-o.our_probability, -o.odds)):
        if opt.odds <= 1.01 or opt.our_probability < 0.03:
            continue
        if thesis_side and not _aligns_thesis(opt, thesis_side, home, away):
            continue
        stake = _min_stake_for_return(opt.odds, target)
        if stake > budget:
            continue
        ret = round(stake * opt.odds, 0)
        if ret < target:
            continue
        reserve = budget - stake
        leg = _leg(opt, stake, "main", _reason(opt, profile, "Target single"), home, away)
        sc = _scenarios_multi([leg], reserve)
        profit = ret - stake
        out.append({
            "plan_type": "single",
            "plan_type_label": "Single bet",
            "name": "🎯 Single to target",
            "description": f"{opt.label} @ {opt.odds}x — stake {format_inr(stake)}",
            "why": (
                f"One bet: if it wins you get {format_inr(ret)} "
                f"({format_inr(profit)} profit). "
                f"~{opt.our_probability:.0%} model chance."
            ),
            "path_headline": (
                f"Single · {round(opt.our_probability * 100, 1)}% to {format_inr(target)} · "
                f"{opt.label} ({format_inr(stake)}→{format_inr(ret)})"
            ),
            "legs": [leg],
            "total_stake_inr": stake,
            "reserve_inr": reserve,
            "target_return_inr": ret,
            "target_profit_inr": round(profit, 0),
            "hit_probability": opt.our_probability,
            "hit_probability_pct": round(opt.our_probability * 100, 1),
            "model_alignment": round(opt.our_probability * 100, 1),
            "combined_odds": opt.odds,
            "scenarios": sc,
            "stake_only": stake_only,
            "expected_value_inr": sc.get("expected_value_inr", 0),
            "feasibility": _feasibility(opt.our_probability, stake / budget),
            "placement_mode": "single",
        })
    out.sort(
        key=lambda p: (
            p["hit_probability"],
            -abs(p["target_return_inr"] - target) / max(target, 1),
        ),
        reverse=True,
    )
    return out


def _thesis_side(ctx: dict | None) -> str | None:
    from bet_placer.engine.match_card import _thesis_side_from_ctx
    return _thesis_side_from_ctx(ctx)


def _plan_fights_thesis(plan: dict, thesis: dict, home: str, away: str) -> bool:
    from bet_placer.engine.card_coherence import plan_fights_match_thesis
    return plan_fights_match_thesis(plan, thesis, home, away)


def _is_multi_slip_plan(plan: dict) -> bool:
    ptype = plan.get("plan_type")
    n = len([l for l in (plan.get("legs") or []) if float(l.get("stake_inr") or 0) > 0])
    return ptype in ("coverage", "match_card") and n >= 2


def _pick_labels(ctx: dict) -> set[str]:
    labels: set[str] = set()
    for p in (ctx.get("unified_picks") or []) + (ctx.get("easy_money_picks") or []):
        lbl = (p.get("label") if isinstance(p, dict) else getattr(p, "label", None)) or ""
        if lbl:
            labels.add(lbl.lower())
    return labels


def _combo_thesis_anchor_ok(combo, thesis_side: str | None, home: str, away: str) -> bool:
    """Parlay must tell one story — favorite result and/or their scorers, not the other side."""
    if not thesis_side or thesis_side == "neutral":
        return True
    from bet_placer.engine.match_card import _option_result_side

    fav = home if thesis_side == "home" else away
    neutral_only = True
    has_fav_read = False
    for opt in combo:
        m = (getattr(opt, "market", None) or "").lower()
        lbl = (getattr(opt, "label", "") or "").lower()
        if m in ("over_under_goals", "btts", "corners", "cards"):
            continue
        neutral_only = False
        if m in ("match_winner", "draw_no_bet", "asian_handicap", "half_time"):
            if _option_result_side(opt, home, away) == thesis_side:
                has_fav_read = True
        elif m == "player_goal" or "scorer" in lbl:
            if fav.lower() in lbl:
                has_fav_read = True
            else:
                return False
        elif m == "double_chance":
            opp = away.lower() if thesis_side == "home" else home.lower()
            if opp in lbl and fav.lower() not in lbl:
                return False
            if fav.lower() in lbl:
                has_fav_read = True
    if neutral_only:
        return True
    return has_fav_read


def _combo_story_score(combo, ctx: dict, thesis_side: str | None, home: str, away: str) -> float:
    """Boost legs that match this fixture's picks and narrative — not a fixed template."""
    score = 0.0
    markets = {(getattr(c, "market", None) or "").lower() for c in combo}
    picks = _pick_labels(ctx)
    for opt in combo:
        lbl = (getattr(opt, "label", "") or "").lower()
        if lbl in picks:
            score += 0.20
        prob = float(getattr(opt, "our_probability", 0) or 0)
        score += prob * 0.10
    if thesis_side and markets & {"match_winner", "asian_handicap", "draw_no_bet", "double_chance"}:
        score += 0.06
    return score


def _combo_match_fit(combo, profile: dict, ctx: dict, home: str, away: str) -> float:
    """How well this combo fits THIS match profile — varies by fixture."""
    style = profile.get("style") or "balanced"
    markets = {(getattr(c, "market", "") or "").lower() for c in combo}
    labels = " ".join((getattr(c, "label", "") or "").lower() for c in combo)
    pick_labels = _pick_labels(ctx)
    score = 0.0

    for opt in combo:
        if (getattr(opt, "label", "") or "").lower() in pick_labels:
            score += 0.30

    if style == "low_scoring":
        if "over_under_goals" in markets and "under" in labels:
            score += 0.22
        if "btts" in markets and "no" in labels:
            score += 0.16
    elif style == "high_scoring":
        if "over_under_goals" in markets and "over" in labels:
            score += 0.22
        if "btts" in markets and "yes" in labels:
            score += 0.16
        if "player_goal" in markets:
            score += 0.20
    elif style == "dominant_favorite":
        fav = (profile.get("favorite") or "").lower()
        if fav and fav in labels:
            score += 0.22
        if "player_goal" in markets:
            score += 0.18
        if "asian_handicap" in markets:
            score += 0.10
    elif style == "tight":
        if "double_chance" in markets:
            score += 0.20
        if "draw_no_bet" in markets:
            score += 0.12
        if "under" in labels:
            score += 0.10
    elif style == "chaotic":
        if markets & {"cards", "corners"}:
            score += 0.14
        if "over" in labels:
            score += 0.10
    else:
        if markets & {"cards", "corners", "player_goal"}:
            score += 0.08

    generic = {"over_under_goals", "btts", "match_winner", "draw_no_bet", "asian_handicap"}
    if markets and markets <= generic and "player_goal" not in markets:
        if not any((getattr(c, "label", "") or "").lower() in pick_labels for c in combo):
            score -= 0.15

    return score


def _combo_hit_probability(combo, profile: dict | None = None, thesis_side: str | None = None) -> float:
    """Coherent same-match legs correlate — boost depends on match style, not one template."""
    probs = [float(getattr(o, "our_probability", 0) or 0) for o in combo]
    if not probs:
        return 0.0
    product = math.prod(probs)
    n = len(probs)
    style = (profile or {}).get("style") or "balanced"
    boost = 1.0
    if style in ("dominant_favorite", "high_scoring") and n >= 2:
        boost += 0.06
    elif style == "low_scoring" and n >= 2:
        boost += 0.04
    if thesis_side:
        boost += 0.03
    adjusted = product * (boost ** max(0, n - 1))
    return max(product, min(adjusted, min(probs) * 0.99, 0.50))


def _dedupe_combo_templates(plans: list[dict], max_n: int) -> list[dict]:
    """Don't fill the board with the same market mix — one per template shape."""
    picked: list[dict] = []
    seen_markets: set = set()
    seen_labels: set = set()
    for p in plans:
        legs = p.get("legs") or []
        m_sig = frozenset((l.get("market") or "").lower() for l in legs)
        l_sig = frozenset((l.get("label") or "").lower() for l in legs)
        if m_sig in seen_markets and len(picked) >= 1:
            continue
        if l_sig in seen_labels:
            continue
        seen_markets.add(m_sig)
        seen_labels.add(l_sig)
        picked.append(p)
        if len(picked) >= max_n:
            break
    return picked if picked else plans[:max_n]


def _search_combo_routes(pool, budget, target, profile, stake_only, ctx, home, away) -> list[dict]:
    """Custom-estimated same-match combos built from coherent singles."""
    from bet_placer.engine.match_card import _aligns_thesis, _score_option

    thesis_side = _thesis_side(ctx)
    target_hit = bool(ctx.get("target_hit_mode"))
    search = _wide_pool(pool, ctx, stake_only, home, away)
    cands = [
        o for o in search
        if (getattr(o, "odds", 0) or 0) > 1.05 and (getattr(o, "our_probability", 0) or 0) >= (0.10 if target_hit else 0.04)
    ]
    if thesis_side:
        cands = [o for o in cands if _aligns_thesis(o, thesis_side, home, away)]
    cands.sort(
        key=lambda o: (
            _score_option(o, profile, home, away, ctx),
            float(getattr(o, "our_probability", 0) or 0),
        ),
        reverse=True,
    )
    top = cands[:16 if target_hit else 20]
    out: list[dict] = []
    fav_name = home if thesis_side == "home" else away if thesis_side == "away" else ""

    leg_max = 3 if target_hit else 6
    for n in range(2, min(leg_max, len(top)) + 1):
        for combo in combinations(top, n):
            if len({c.market for c in combo}) < n:
                continue
            result_legs = sum(
                1 for c in combo
                if (getattr(c, "market", "") or "").lower() in {
                    "match_winner", "draw_no_bet", "asian_handicap", "double_chance", "half_time",
                }
            )
            if target_hit and result_legs > 1:
                continue
            if _combo_contradicts(combo, home, away):
                continue
            if not _combo_thesis_anchor_ok(combo, thesis_side, home, away):
                continue
            odds = 1.0
            for opt in combo:
                odds *= float(opt.odds or 1.0)
            hp = _combo_hit_probability(combo, profile, thesis_side)
            if odds <= 1.01:
                continue
            if target_hit:
                if odds < 3.2 or odds > 6.5:
                    continue
                if hp < 0.16:
                    continue
            stake = _min_stake_for_return(odds, target)
            if stake > budget:
                continue
            ret = round(stake * odds, 0)
            if ret < target:
                continue
            legs = [
                _leg(opt, 0, "parlay_leg", _reason(opt, profile, "Parlay leg"), home, away)
                for opt in combo
            ]
            profit = ret - stake
            ev = round(stake * odds * hp - stake, 0)
            lbl = ", ".join(opt.label for opt in combo[:3])
            if len(combo) > 3:
                lbl += f" +{len(combo) - 3}"
            story = f"{fav_name} lean · " if fav_name else ""
            match_fit = _combo_match_fit(combo, profile, ctx, home, away)
            sweet = -abs(math.log(max(odds, 1.01)) - math.log(4.0))
            custom_combo = {
                "plan_type": "combo",
                "plan_type_label": f"Estimated custom combo · {n} legs",
                "name": "Custom combo route",
                "description": f"{n} judged legs @ {round(odds, 2)}x — stake {format_inr(stake)}",
                "why": (
                    f"{story}{profile.get('style', 'match')}-fit custom combo for {home} vs {away}. "
                    f"All {n} legs must hit together. ~{hp:.0%} chance → {format_inr(ret)} "
                    f"(stake {format_inr(stake)})."
                ),
                "path_headline": (
                    f"Custom {n}-leg combo · {round(hp * 100, 1)}% · "
                    f"{lbl} @ {round(odds, 2)}x"
                ),
                "path_label": lbl if n <= 2 else f"{n}-leg custom combo · {lbl}",
                "legs": legs,
                "total_stake_inr": stake,
                "reserve_inr": budget - stake,
                "target_return_inr": ret,
                "target_profit_inr": round(profit, 0),
                "hit_probability": hp,
                "hit_probability_pct": round(hp * 100, 1),
                "model_alignment": round(sum(float(o.our_probability or 0) for o in combo) / n * 100, 1),
                "combined_odds": round(odds, 2),
                "scenarios": {"expected_value_inr": ev},
                "stake_only": stake_only,
                "expected_value_inr": ev,
                "feasibility": _feasibility(hp, stake / budget),
                "placement_mode": "parlay",
                "verified_stake": False,
                "_story_score": _combo_story_score(combo, ctx, thesis_side, home, away),
                "_match_fit": match_fit,
                "_sweet_score": sweet,
            }
            out.append(custom_combo)

    out.sort(
        key=lambda p: (
            p.get("hit_probability", 0) * 0.55 + float(p.get("_match_fit") or 0) * 0.45,
            p.get("_match_fit", 0),
            p.get("_story_score", 0),
            -abs((p.get("target_return_inr") or 0) - target) / max(target, 1),
        ),
        reverse=True,
    )
    return _dedupe_combo_templates(out, MAX_PLANS)


def _clean_single_hits_target(pool: list, budget: float, target: float) -> bool:
    """True when a single can hit target with ≥25% model chance and tight payout."""
    for opt in pool or []:
        if opt.odds <= 1.01 or opt.our_probability < 0.25:
            continue
        stake = _min_stake_for_return(opt.odds, target)
        if stake > budget:
            continue
        ret = stake * opt.odds
        if ret >= target and ret <= target * 1.15:
            return True
    return False


def _search_stake_combos(
    overlay, budget, target, stake_only,
    pool=None, home: str = "", away: str = "", ctx: dict | None = None,
) -> list[dict]:
    """Only Stake pre-built combo markets — real SGM prices, not multiplied singles."""
    from bet_placer.engine.stake_sgm import search_stake_combos
    from bet_placer.engine.card_coherence import stake_combo_fits_thesis

    if not overlay:
        return []
    combos = overlay.get("stake_combos") or []
    if not combos:
        return []

    if home and away:
        combos = [
            c for c in combos
            if stake_combo_fits_thesis(c, pool, home, away, ctx)
        ]

    raw = search_stake_combos(
        combos, budget, target,
        min_prob=0.10 if ctx and ctx.get("target_hit_mode") else 0.0,
        min_odds=2.0 if ctx and ctx.get("target_hit_mode") else 0.0,
        max_odds=10.0 if ctx and ctx.get("target_hit_mode") else None,
        pool=pool,
        home=home,
        away=away,
    )
    out: list[dict] = []
    for c in raw:
        stake = c["stake_inr"]
        ret = c["return_inr"]
        reserve = budget - stake
        profit = ret - stake
        hit_prob = float(c.get("hit_probability") or 0)
        hit_pct = round(hit_prob * 100, 1)
        leg = {
            **c["legs"][0],
            "stake_inr": stake,
            "return_inr": ret,
            "payout_text": f"₹{int(stake):,} → ₹{int(ret):,}",
            "role": "stake_combo",
            "stake_market": c.get("stake_market"),
            "live_odds": True,
            "odds_source": "stake",
            "our_probability": hit_prob,
            "our_probability_pct": hit_pct,
        }
        ev = round(stake * (c["odds"] - 1) * hit_prob - stake * (1 - hit_prob), 0)
        out.append({
            "plan_type": "stake_combo",
            "plan_type_label": "Stake SGM (verified combo)",
            "name": "🔗 Stake combo",
            "description": f"{c['label']} @ {c['odds']}x — scraped from Stake Combos",
            "why": (
                f"This exact combo exists on Stake under Combos. "
                f"Stake {format_inr(stake)} → {format_inr(ret)} if it wins "
                f"(~{hit_pct}% model chance)."
            ),
            "path_headline": f"Stake combo @ {c['odds']}x → {format_inr(ret)}",
            "legs": [leg],
            "stake_market": c.get("stake_market"),
            "label": c.get("label"),
            "combined_odds": c["odds"],
            "combined_probability": hit_prob,
            "combined_probability_pct": hit_pct,
            "stake_inr": stake,
            "total_stake_inr": stake,
            "reserve_inr": reserve,
            "target_return_inr": ret,
            "target_profit_inr": round(profit, 0),
            "hit_probability": hit_prob,
            "hit_probability_pct": hit_pct,
            "model_alignment": hit_pct,
            "scenarios": {"expected_value_inr": ev},
            "stake_only": stake_only,
            "expected_value_inr": ev,
            "feasibility": _feasibility(hit_prob, stake / budget),
            "verified_stake": True,
            "placement_mode": "stake_sgm",
        })
    return out


def _search_splits(pool, budget, target, profile, stake_only, ctx, home, away) -> list[dict]:
    """Independent singles — if all win, combined return hits target."""
    cands = [
        o for o in pool
        if o.our_probability >= MIN_LEG_PROB and o.odds > 1.1
    ]
    cands.sort(key=lambda o: (-o.our_probability, -o.odds))
    cands = cands[:24]
    out: list[dict] = []

    for n in range(2, min(MAX_SPLIT_LEGS, len(cands)) + 1):
        for combo in combinations(cands, n):
            if len({c.market for c in combo}) < n:
                continue
            if _combo_contradicts(combo, home, away):
                continue
            plan = _allocate_split(combo, budget, target, profile, stake_only, home, away)
            if plan:
                out.append(plan)

    out.sort(key=lambda p: p["hit_probability"], reverse=True)
    return out[:MAX_PLANS]


def _allocate_split(combo, budget, target, profile, stake_only, home: str = "", away: str = "") -> dict | None:
    """Find stake split so sum(stake_i * odds_i) >= target and sum(stake_i) <= budget."""
    n = len(combo)
    best = None
    best_score = -1.0

    for alpha in (0.35, 0.45, 0.55, 0.65, 0.75):
        stakes = []
        remaining = budget
        for i, opt in enumerate(combo):
            if i == n - 1:
                s = _round(remaining)
            else:
                s = _round(budget * alpha / (n - 1 + alpha)) if n > 1 else _round(budget * alpha)
                s = min(s, remaining - MIN_STAKE * (n - i - 1))
            if s < MIN_STAKE:
                break
            stakes.append(s)
            remaining -= s
        if len(stakes) != n:
            continue
        total_stake = sum(stakes)
        if total_stake > budget:
            continue
        ret = sum(s * o.odds for s, o in zip(stakes, combo))
        if ret < target:
            continue
        cp = math.prod(o.our_probability for o in combo)
        score = cp * (ret / target)
        if score > best_score:
            best_score = score
            best = (stakes, ret, cp)

    if not best:
        return None

    stakes, ret, cp = best
    reserve = budget - sum(stakes)
    roles = ["main", "support", "extra"]
    legs = [
        _leg(opt, stakes[i], roles[min(i, 2)], _reason(opt, profile, roles[min(i, 2)]), home, away)
        for i, opt in enumerate(combo)
    ]
    sc = _scenarios_multi(legs, reserve)
    profit = ret - sum(stakes)
    labels = ", ".join(c.label for c in combo)

    return {
        "plan_type": "split",
        "plan_type_label": f"Separate singles · {n} must all win",
        "name": "📊 Separate singles (all hit)",
        "description": f"{n} independent singles on Stake · {labels}",
        "why": (
            f"Place {n} separate singles — not a same-game multi. "
            f"If all win you collect {format_inr(round(ret, 0))} (~{cp:.0%})."
        ),
        "path_headline": f"{n} separate singles → {format_inr(round(ret, 0))} if all hit",
        "legs": legs,
        "total_stake_inr": sum(stakes),
        "reserve_inr": reserve,
        "target_return_inr": round(ret, 0),
        "target_profit_inr": round(profit, 0),
        "hit_probability": cp,
        "hit_probability_pct": round(cp * 100, 1),
        "model_alignment": round(sum(c.our_probability for c in combo) / n * 100, 1),
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": sc.get("expected_value_inr", 0),
        "feasibility": _feasibility(cp, sum(stakes) / budget),
    }


def _search_target_hit_routes(
    pool, budget, target, profile, stake_only, ctx, home, away,
) -> list[dict]:
    """Separate singles — each sized to pay target; rank by chance any route wins."""
    from bet_placer.engine.match_card import _build_target_hit_legs

    search = _wide_pool(pool, ctx, stake_only, home, away)
    thesis_side = _thesis_side(ctx)

    out: list[dict] = []
    seen: set[tuple] = set()
    from bet_placer.engine.bet_portfolio import max_tickets_for_budget
    leg_cap = min(8, max_tickets_for_budget(budget))
    for max_legs in range(leg_cap, 1, -1):
        legs = _build_target_hit_legs(
            search, budget, target, profile, home, away, ctx,
            thesis=thesis_side, max_legs=max_legs, min_legs=2,
        )
        if len(legs) < 2:
            continue
        sig = tuple(sorted(
            (l.get("market"), l.get("selection"), l.get("line"))
            for l in legs
        ))
        if sig in seen:
            continue
        seen.add(sig)
        total = sum(float(l.get("stake_inr") or 0) for l in legs)
        reserve = budget - total
        probs = [float(l.get("our_probability") or 0) for l in legs]
        p_win = 1.0 - math.prod(1.0 - p for p in probs)
        sc = _scenarios_multi(legs, reserve)
        n = len(legs)
        out.append({
            "plan_type": "coverage",
            "plan_type_label": f"Target routes · {n} singles",
            "name": f"🎯 {n} routes to {format_inr(target)}",
            "description": f"{n} separate singles — any one pays {format_inr(target)} if it wins",
            "why": _target_route_why(legs, target, p_win),
            "path_headline": _target_route_headline(legs, target, p_win),
            "legs": legs,
            "total_stake_inr": total,
            "reserve_inr": reserve,
            "target_return_inr": target,
            "target_profit_inr": round(target - total, 0),
            "hit_probability": p_win,
            "hit_probability_pct": round(p_win * 100, 1),
            "model_alignment": round(sum(probs) / n * 100, 1),
            "scenarios": sc,
            "stake_only": stake_only,
            "expected_value_inr": sc.get("expected_value_inr", 0),
            "feasibility": _feasibility(p_win, total / budget),
            "placement_mode": "separate_singles",
        })

    out.sort(
        key=lambda p: (p.get("hit_probability", 0), len(p.get("legs") or [])),
        reverse=True,
    )
    return out[:MAX_PLANS]


def _target_route_headline(legs: list[dict], target: float, p_win: float) -> str:
    best = max(legs, key=lambda l: float(l.get("our_probability") or 0))
    label = best.get("label") or "Best route"
    stake = float(best.get("stake_inr") or 0)
    ret = float(best.get("return_inr") or stake * float(best.get("odds") or 1))
    pct = round(float(best.get("our_probability") or 0) * 100, 1)
    n = len(legs)
    return (
        f"{n} routes to {format_inr(target)} · "
        f"{round(p_win * 100, 1)}% any hits · "
        f"lead: {label} ({pct}% · {format_inr(stake)}→{format_inr(ret)})"
    )


def _target_route_why(legs: list[dict], target: float, p_win: float) -> str:
    best = max(legs, key=lambda l: float(l.get("our_probability") or 0))
    pct = round(float(best.get("our_probability") or 0) * 100, 1)
    return (
        f"Each ticket pays {format_inr(target)} if it wins. "
        f"~{p_win:.0%} chance at least one lands — "
        f"best line {best.get('label')} ({pct}%)."
    )


def _search_coverage(pool, budget, target, profile, stake_only, ctx, betting_style, home, away) -> list[dict]:
    """Separate singles — each sized so if THAT bet wins you hit the profit target."""
    from bet_placer.engine.match_card import _aligns_thesis
    from bet_placer.engine.bet_portfolio import (
        leg_net_if_solo_win,
        max_tickets_for_budget,
        size_independent_route_stakes,
        target_profit_inr,
    )

    search = _wide_pool(pool, ctx, stake_only, home, away)
    thesis_side = _thesis_side(ctx)
    profit_goal = target_profit_inr(budget, target)
    floor_net = profit_goal * 0.95

    cands = [
        o for o in search
        if o.odds > 1.08 and o.our_probability >= 0.04 and _aligns_thesis(o, thesis_side, home, away)
    ]
    cands.sort(key=lambda o: (-(o.our_probability + _leg_worth_bonus(o, ctx)), -o.odds))
    max_routes = max_tickets_for_budget(budget)
    if betting_style.get("prefers_spread_singles"):
        max_routes = min(20, max_routes + 2)
    cands = cands[:28]
    out: list[dict] = []
    best_per_n: dict[int, dict] = {}
    max_n = min(max_routes, len(cands) + 1)
    tries_per_n = max(16, MAX_COMBO_TRIES // max(max_n - 1, 1))

    for n in range(max_n - 1, 1, -1):
        local_tries = 0
        for combo in combinations(cands, n):
            local_tries += 1
            if local_tries > tries_per_n:
                break
            if len({c.market for c in combo}) < n:
                continue
            if _combo_contradicts(combo, home, away):
                continue
            odds_list = [float(o.odds or 1) for o in combo]
            stakes = size_independent_route_stakes(odds_list, budget, profit_goal)
            if not stakes:
                continue
            total = sum(stakes)
            if total > budget:
                continue
            legs = [
                _leg(opt, stakes[i], "route", _reason(opt, profile, "Route to target"), home, away)
                for i, opt in enumerate(combo)
            ]
            for leg in legs:
                net = leg_net_if_solo_win(leg, legs)
                leg["hits_target"] = net >= floor_net
                leg["profit_if_solo_inr"] = round(net, 0)
            if not any(l.get("hits_target") for l in legs):
                continue
            probs = [o.our_probability for o in combo]
            p_win = 1.0 - math.prod(1.0 - p for p in probs)
            reserve = budget - total
            sc = _scenarios_multi(legs, reserve)
            plan = {
                "plan_type": "coverage",
                "plan_type_label": f"Separate singles · {n} routes",
                "name": f"🛤️ {n} routes to {format_inr(target)}",
                "description": f"{n} separate singles — any one can hit your target if it wins",
                "why": _target_route_why(legs, target, p_win),
                "path_headline": _target_route_headline(legs, target, p_win),
                "legs": legs,
                "total_stake_inr": total,
                "reserve_inr": reserve,
                "target_return_inr": target,
                "target_profit_inr": round(profit_goal, 0),
                "hit_probability": p_win,
                "hit_probability_pct": round(p_win * 100, 1),
                "model_alignment": round(sum(probs) / n * 100, 1),
                "scenarios": sc,
                "stake_only": stake_only,
                "expected_value_inr": sc.get("expected_value_inr", 0),
                "feasibility": _feasibility(p_win, total / budget),
                "placement_mode": "separate_singles",
            }
            prev = best_per_n.get(n)
            if not prev or p_win > float(prev.get("hit_probability") or 0):
                best_per_n[n] = plan

    out = list(best_per_n.values())
    out.sort(
        key=lambda p: (p.get("hit_probability", 0), len(p.get("legs") or [])),
        reverse=True,
    )
    return out[:MAX_PLANS]


def _ticket_stack_leg(
    kind: str,
    item,
    stake: float,
    hit_prob: float,
    profile: dict,
    home: str,
    away: str,
    *,
    budget: float,
    target: float,
    hits_target: bool = False,
) -> dict:
    if kind == "combo":
        leg = _stake_combo_leg(
            item, stake, "route", hit_prob, home, away,
            budget=budget, target=target, profile=profile,
        )
    else:
        leg = _leg(item, stake, "route", _reason(item, profile, "Separate ticket"), home, away)
    if hits_target:
        leg["hits_target"] = True
    return leg


def _search_ticket_stack(
    pool, budget, target, profile, stake_only, ctx, home, away,
) -> list[dict]:
    """3–8 separate Stake slips — cheap probable tickets + one sized to hit target."""
    from bet_placer.engine.card_coherence import path_is_coherent, stake_combo_fits_thesis, stake_combo_is_garbage
    from bet_placer.engine.match_card import _aligns_thesis
    from bet_placer.engine.bet_portfolio import (
        leg_net_if_solo_win,
        max_tickets_for_budget,
        min_stake_for_profit,
        target_profit_inr,
    )
    from bet_placer.engine.stake_sgm import estimate_stake_combo_probability

    search = _wide_pool(pool, ctx, stake_only, home, away)
    thesis_side = _thesis_side(ctx)
    profit_goal = target_profit_inr(budget, target)
    floor_net = profit_goal * 0.90
    max_deploy = budget * 0.96
    max_tix = max_tickets_for_budget(budget)
    overlay = ctx.get("stake_overlay")

    spray: list[tuple[str, object, float, float]] = []
    for o in search:
        odds = float(o.odds or 0)
        prob = float(o.our_probability or 0)
        if not (1.12 <= odds <= 4.2 and prob >= 0.10 and _aligns_thesis(o, thesis_side, home, away)):
            continue
        spray.append(("single", o, odds, prob))
    spray.sort(key=lambda x: (-x[3], -x[2]))

    if overlay:
        for c in overlay.get("stake_combos") or []:
            odds = float(c.get("odds") or 0)
            if not (2.0 <= odds <= 5.0):
                continue
            if stake_combo_is_garbage(c, home, away):
                continue
            if not stake_combo_fits_thesis(c, pool, home, away, ctx):
                continue
            hp = estimate_stake_combo_probability(c, pool, home, away)
            if hp < 0.10:
                continue
            spray.append(("combo", c, odds, hp))
    spray.sort(key=lambda x: (-x[3], -x[2]))

    targets: list[tuple[str, object, float, float]] = []
    for o in search:
        odds = float(o.odds or 0)
        prob = float(o.our_probability or 0)
        if odds < 3.8 or prob < 0.04 or not _aligns_thesis(o, thesis_side, home, away):
            continue
        targets.append(("single", o, odds, prob))
    if overlay:
        for c in overlay.get("stake_combos") or []:
            odds = float(c.get("odds") or 0)
            if not (3.2 <= odds <= 12.0):
                continue
            if stake_combo_is_garbage(c, home, away) or not stake_combo_fits_thesis(c, pool, home, away, ctx):
                continue
            hp = estimate_stake_combo_probability(c, pool, home, away)
            if hp < 0.06:
                continue
            targets.append(("combo", c, odds, hp))
    targets.sort(key=lambda x: (-x[3], -min(abs(x[2] - 6.0), 4.0)))

    best_per_n: dict[int, dict] = {}
    seen: set[tuple] = set()

    def _try_stack(target_entry, extras: tuple):
        t_kind, t_item, t_odds, t_prob = target_entry
        legs: list[dict] = []
        for e_kind, e_item, _, e_prob in extras:
            legs.append(_ticket_stack_leg(
                e_kind, e_item, float(MIN_STAKE), e_prob, profile, home, away,
                budget=budget, target=target,
            ))
        other = sum(float(l.get("stake_inr") or 0) for l in legs)
        t_stake = min_stake_for_profit(t_odds, profit_goal, other)
        target_leg = _ticket_stack_leg(
            t_kind, t_item, t_stake, t_prob, profile, home, away,
            budget=budget, target=target,
        )
        legs.append(target_leg)
        total = sum(float(l.get("stake_inr") or 0) for l in legs)
        if total > max_deploy or len(legs) < 3:
            return
        if not path_is_coherent(legs, home, away):
            return
        net = leg_net_if_solo_win(target_leg, legs)
        if net < floor_net:
            return
        sig = tuple(
            (l.get("market"), l.get("selection"), l.get("line"), int(float(l.get("stake_inr") or 0)))
            for l in legs
        )
        if sig in seen:
            return
        seen.add(sig)
        target_leg["hits_target"] = True
        target_leg["profit_if_solo_inr"] = round(net, 0)
        reserve = budget - total
        probs = [float(l.get("our_probability") or 0) for l in legs]
        p_any = 1.0 - math.prod(1.0 - p for p in probs if p > 0)
        n = len(legs)
        sc = _scenarios_multi(legs, reserve)
        plan = {
            "plan_type": "coverage",
            "plan_type_label": f"{n} separate tickets",
            "name": f"🎫 {n}-ticket stack",
            "description": (
                f"{n} separate bets on Stake — {format_inr(total)} deployed. "
                f"Target ticket nets {format_inr(net)} if it wins."
            ),
            "why": (
                f"{n} separate Stake slips — {n - 1} probable ticket{'s' if n > 2 else ''} "
                f"at {format_inr(MIN_STAKE)} plus one target route at {format_inr(t_stake)}. "
                f"Losing the others is fine. ~{p_any:.0%} any winner · "
                f"target ~{t_prob:.0%}."
            ),
            "path_headline": _target_route_headline(legs, target, p_any),
            "legs": legs,
            "total_stake_inr": total,
            "reserve_inr": reserve,
            "target_return_inr": target,
            "target_profit_inr": round(profit_goal, 0),
            "hit_probability": p_any,
            "hit_probability_pct": round(p_any * 100, 1),
            "model_alignment": round(sum(probs) / max(len(probs), 1) * 100, 1),
            "scenarios": sc,
            "stake_only": stake_only,
            "expected_value_inr": sc.get("expected_value_inr", 0),
            "feasibility": _feasibility(p_any, total / budget),
            "placement_mode": "separate_singles",
        }
        score = p_any + n * 0.12
        prev = best_per_n.get(n)
        if not prev or score > float(prev.get("_stack_score") or 0):
            plan["_stack_score"] = score
            best_per_n[n] = plan

    spray_top = spray[:30]
    for t_entry in targets[:20]:
        t_odds = t_entry[2]
        max_extra = 5 if t_odds >= 7.0 else 4 if t_odds >= 5.5 else 3
        for n_extra in range(min(max_extra, max_tix - 1, len(spray_top)), 1, -1):
            tries = 0
            for extras in combinations(spray_top, n_extra):
                tries += 1
                if tries > 200:
                    break
                singles = [item for k, item, _, _ in extras if k == "single"]
                if singles and _combo_contradicts(tuple(singles), home, away):
                    continue
                _try_stack(t_entry, extras)

    out = list(best_per_n.values())
    out.sort(key=lambda p: (p.get("_stack_score", 0), len(p.get("legs") or [])), reverse=True)
    for p in out:
        p.pop("_stack_score", None)
    return out[:MAX_PLANS]


def _search_spray_routes(
    pool, budget, target, profile, stake_only, ctx, home, away,
) -> list[dict]:
    """Several probable cheap tickets + routes sized to hit target — no anchor/lotto tiers."""
    from bet_placer.engine.match_card import _aligns_thesis
    from bet_placer.engine.bet_portfolio import (
        leg_net_if_solo_win,
        max_tickets_for_budget,
        min_stake_for_profit,
        target_profit_inr,
    )

    search = _wide_pool(pool, ctx, stake_only, home, away)
    thesis_side = _thesis_side(ctx)
    profit_goal = target_profit_inr(budget, target)
    floor_net = profit_goal * 0.95
    max_deploy = budget * 0.88
    max_n = max_tickets_for_budget(budget)

    routes = [
        o for o in search
        if float(o.odds or 0) >= 3.5
        and float(o.our_probability or 0) >= 0.05
        and _aligns_thesis(o, thesis_side, home, away)
    ]
    spray = [
        o for o in search
        if 1.12 <= float(o.odds or 0) <= 4.5
        and float(o.our_probability or 0) >= 0.12
        and _aligns_thesis(o, thesis_side, home, away)
    ]
    routes.sort(key=lambda o: (-(o.our_probability + _leg_worth_bonus(o, ctx)), -o.odds))
    spray.sort(key=lambda o: (-o.our_probability, -o.odds))

    best_per_n: dict[int, dict] = {}
    for route_opt in routes[:12]:
        route_odds = float(route_opt.odds or 1)
        for n_spray in range(0, min(max_n - 1, len(spray), 6)):
            for spray_combo in combinations(spray[:14], n_spray) if n_spray else [()]:
                spray_stakes = [float(MIN_STAKE)] * n_spray
                other = sum(spray_stakes)
                route_stake = min_stake_for_profit(route_odds, profit_goal, other)
                total = other + route_stake
                if total > max_deploy:
                    continue
                legs: list[dict] = []
                for i, opt in enumerate(spray_combo):
                    legs.append(_leg(opt, spray_stakes[i], "route", _reason(opt, profile, "Probable ticket"), home, away))
                route_leg = _leg(route_opt, route_stake, "route", _reason(route_opt, profile, "Target route"), home, away)
                legs.append(route_leg)
                net = leg_net_if_solo_win(route_leg, legs)
                if net < floor_net:
                    continue
                route_leg["hits_target"] = True
                route_leg["profit_if_solo_inr"] = round(net, 0)
                reserve = budget - total
                probs = [float(l.get("our_probability") or 0) for l in legs]
                p_any = 1.0 - math.prod(1.0 - p for p in probs if p > 0)
                n = len(legs)
                sc = _scenarios_multi(legs, reserve)
                plan = {
                    "plan_type": "coverage",
                    "plan_type_label": f"{n} separate tickets",
                    "name": f"🎫 {n}-ticket spread",
                    "description": (
                        f"{n} separate bets — {format_inr(total)} deployed. "
                        f"If the target route wins you net {format_inr(net)}."
                    ),
                    "why": (
                        f"{n} separate tickets on Stake. "
                        f"{n_spray} probable leg{'s' if n_spray != 1 else ''} at {format_inr(MIN_STAKE)} "
                        f"+ one route at {format_inr(route_stake)}. "
                        f"~{p_any:.0%} any winner · target route ~{route_opt.our_probability:.0%}."
                    ),
                    "path_headline": _target_route_headline(legs, target, p_any),
                    "legs": legs,
                    "total_stake_inr": total,
                    "reserve_inr": reserve,
                    "target_return_inr": target,
                    "target_profit_inr": round(profit_goal, 0),
                    "hit_probability": p_any,
                    "hit_probability_pct": round(p_any * 100, 1),
                    "model_alignment": round(sum(probs) / max(len(probs), 1) * 100, 1),
                    "scenarios": sc,
                    "stake_only": stake_only,
                    "expected_value_inr": sc.get("expected_value_inr", 0),
                    "feasibility": _feasibility(p_any, total / budget),
                    "placement_mode": "separate_singles",
                }
                prev = best_per_n.get(n)
                score = p_any + n * 0.06
                if not prev or score > float(prev.get("_spray_score") or 0):
                    plan["_spray_score"] = score
                    best_per_n[n] = plan

    out = list(best_per_n.values())
    out.sort(key=lambda p: (p.get("_spray_score", 0), len(p.get("legs") or [])), reverse=True)
    for p in out:
        p.pop("_spray_score", None)
    return out[:MAX_PLANS]


def _sgm_route_sort_key(odds: float, hit_prob: float) -> tuple:
    """Prefer Stake-style 3–5x SGMs with real hit rate over moonshots."""
    from bet_placer.engine.stake_sgm import _sgm_sweetness
    sweet = _sgm_sweetness(odds)
    moderate = 1 if 2.0 <= odds <= 8.0 else 0
    return (moderate, hit_prob >= 0.18, hit_prob, sweet)


def _stake_combo_leg(
    combo: dict,
    stake: float,
    role: str,
    hit_prob: float,
    home: str,
    away: str,
    *,
    budget: float = 0,
    target: float = 0,
    profile: dict | None = None,
) -> dict:
    from bet_placer.engine.leg_explain import explain_leg
    from bet_placer.markets.labels import format_combo_label

    odds = float(combo.get("odds") or 0)
    raw_lbl = combo.get("label") or combo.get("stake_market")
    leg = {
        "label": format_combo_label(raw_lbl, odds, home, away, stake_market=combo.get("stake_market")),
        "market": "stake_combo",
        "selection": combo.get("selection"),
        "line": combo.get("line"),
        "odds": odds,
        "stake_inr": stake,
        "our_probability": hit_prob,
        "our_probability_pct": round(hit_prob * 100, 1),
        "role": role,
        "odds_source": "stake",
        "live_odds": True,
        "verified_stake": True,
        "stake_market": combo.get("stake_market"),
        "return_inr": round(stake * odds, 0),
        "payout_text": f"₹{int(stake):,} → ₹{int(stake * odds):,}",
    }
    leg["reason"] = explain_leg(
        leg, home=home, away=away, budget=budget, target_cashout=target, all_legs=[leg],
    )
    return leg


def _search_moderate_sgm_portfolio(
    pool, budget, target, profile, stake_only, ctx, home, away,
) -> list[dict]:
    """2–3 verified Stake SGMs (2–8x) as separate tickets — like real Stake slips."""
    overlay = ctx.get("stake_overlay")
    if not overlay:
        return []

    from bet_placer.engine.card_coherence import path_is_coherent, stake_combo_fits_thesis, stake_combo_is_garbage
    from bet_placer.engine.bet_portfolio import leg_net_if_solo_win, min_stake_for_profit, target_profit_inr
    from bet_placer.engine.stake_sgm import estimate_stake_combo_probability

    profit_goal = target_profit_inr(budget, target)
    floor_net = profit_goal * 0.90
    max_deploy = budget * 0.85
    thesis_side = _thesis_side(ctx)
    fav = home if thesis_side == "home" else away if thesis_side == "away" else ""

    cands: list[tuple] = []
    companion_pool: list[tuple] = []
    for c in overlay.get("stake_combos") or []:
        odds = float(c.get("odds") or 0)
        if odds < 2.0 or odds > 8.5:
            continue
        if stake_combo_is_garbage(c, home, away):
            continue
        if not stake_combo_fits_thesis(c, pool, home, away, ctx):
            continue
        hp = estimate_stake_combo_probability(c, pool, home, away)
        if hp < 0.12:
            continue
        entry = (_sgm_route_sort_key(odds, hp), hp, odds, c)
        companion_pool.append(entry)
        need = min_stake_for_profit(odds, profit_goal, 0)
        if need > budget:
            continue
        cands.append((*entry, need))
    _sgm_sort = lambda x: (x[0], x[1], x[2])
    cands.sort(key=_sgm_sort, reverse=True)
    companion_pool.sort(key=_sgm_sort, reverse=True)
    if not cands:
        return []

    out: list[dict] = []
    seen: set = set()

    for _, hp_main, odds_main, combo_main, stake_main in cands[:10]:
        companions: list[tuple] = []
        main_key = (combo_main.get("selection") or combo_main.get("label") or "").lower()
        for item in companion_pool:
            c2 = item[3]
            if c2 is combo_main:
                continue
            key = (c2.get("selection") or c2.get("label") or "").lower()
            if key == main_key:
                continue
            companions.append((item[1], item[2], c2))
            if len(companions) >= 5:
                break

        comp_stakes = []
        remaining = budget - stake_main
        for _hp2, _odds2, _c2 in companions:
            if remaining < MIN_STAKE:
                break
            s = float(MIN_STAKE)
            comp_stakes.append(s)
            remaining -= s
            if len(comp_stakes) >= 5:
                break

        if not comp_stakes:
            # Solo moderate SGM still valid when budget is tight
            comp_legs = []
            other = 0
        else:
            other = sum(comp_stakes)

        total = stake_main + other
        if total > budget or stake_main < MIN_STAKE:
            continue

        legs = [_stake_combo_leg(
            combo_main, stake_main, "route", hp_main, home, away,
            budget=budget, target=target, profile=profile,
        )]
        for (hp2, odds2, c2), s in zip(companions[:len(comp_stakes)], comp_stakes):
            legs.append(_stake_combo_leg(
                c2, s, "route", hp2, home, away,
                budget=budget, target=target, profile=profile,
            ))

        if not path_is_coherent(legs, home, away):
            continue
        net = leg_net_if_solo_win(legs[0], legs)
        if net < floor_net:
            continue
        legs[0]["hits_target"] = True
        legs[0]["profit_if_solo_inr"] = round(net, 0)

        reserve = budget - total
        sc = _scenarios_multi(legs, reserve)
        probs = [float(l.get("our_probability") or 0) for l in legs]
        p_target = float(legs[0].get("our_probability") or 0)
        p_any = 1.0 - math.prod(1.0 - p for p in probs if p > 0)
        win_probs = [p_target] if net >= floor_net else []
        labels = " · ".join(l.get("label", "")[:32] for l in legs[:2])
        comp_txt = (
            f"Companion SGMs at {format_inr(comp_stakes[0])} each · "
            if comp_stakes else ""
        )
        plan = {
            "plan_type": "coverage",
            "plan_type_label": f"Stake SGMs · {len(legs)} separate tickets",
            "name": f"🔗 {len(legs)} Stake SGMs",
            "description": (
                f"{len(legs)} verified same-game multis on Stake — "
                f"{format_inr(total)} deployed · lead SGM ~{p_target:.0%}"
            ),
            "why": (
                f"{fav + ' · ' if fav else ''}"
                f"Place {len(legs)} separate Stake SGMs (not one parlay). "
                f"Lead ticket {format_inr(stake_main)} @ {odds_main:.1f}x nets {format_inr(net)} if it hits "
                f"(~{p_target:.0%}). {comp_txt}"
                f"~{p_any:.0%} any winner."
            ),
            "path_headline": (
                f"{len(legs)} Stake SGMs · {p_target:.0%} lead · "
                f"{labels}"
            ),
            "path_label": f"{len(legs)} Stake SGMs",
            "legs": legs,
            "total_stake_inr": total,
            "reserve_inr": reserve,
            "target_return_inr": target,
            "target_profit_inr": round(profit_goal, 0),
            "hit_probability": p_target,
            "win_probability": (1.0 - math.prod(1.0 - p for p in win_probs)) if win_probs else p_target,
            "hit_probability_pct": round(p_target * 100, 1),
            "model_alignment": round(sum(probs) / max(len(probs), 1) * 100, 1),
            "scenarios": sc,
            "stake_only": stake_only,
            "expected_value_inr": sc.get("expected_value_inr", 0),
            "feasibility": _feasibility(p_target, total / budget),
            "placement_mode": "separate_singles",
            "_moderate_sgm": True,
        }

        sig = tuple((l.get("stake_market") or l.get("label") or "").lower() for l in legs)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(plan)

    out.sort(
        key=lambda p: (
            p.get("_moderate_sgm"),
            float(p.get("hit_probability") or 0),
            len(p.get("legs") or []),
        ),
        reverse=True,
    )
    for p in out:
        p.pop("_moderate_sgm", None)
    return out[:MAX_PLANS]


def _search_spread_portfolio(
    pool, budget, target, profile, stake_only, ctx, home, away,
) -> list[dict]:
    """3–8 separate Stake tickets: tiny safe stakes + medium props + sized lotto to hit target."""
    from bet_placer.engine.match_card import _aligns_thesis
    from bet_placer.engine.bet_portfolio import (
        leg_net_if_solo_win,
        max_tickets_for_budget,
        min_stake_for_profit,
        target_profit_inr,
    )

    thesis_side = _thesis_side(ctx)
    search = _wide_pool(pool, ctx, stake_only, home, away)
    profit_goal = target_profit_inr(budget, target)
    max_deploy = budget * 0.88
    floor_net = profit_goal * 0.90
    fav_name = home if thesis_side == "home" else away if thesis_side == "away" else ""

    def _ok(opt) -> bool:
        return (
            float(opt.odds or 0) > 1.12
            and float(opt.our_probability or 0) >= 0.04
            and _aligns_thesis(opt, thesis_side, home, away)
        )

    safe = [o for o in search if _ok(o) and 1.15 <= o.odds <= 2.35 and o.our_probability >= 0.32]
    medium = [o for o in search if _ok(o) and 2.0 <= o.odds <= 7.0 and o.our_probability >= 0.10]
    lotto = [o for o in search if _ok(o) and 5.5 <= o.odds <= 30.0 and o.our_probability >= 0.03]

    safe.sort(key=lambda o: (-o.our_probability, -o.odds))
    medium.sort(key=lambda o: (-(o.our_probability + _leg_worth_bonus(o, ctx)), -o.odds))
    lotto.sort(key=lambda o: (-o.our_probability, abs(math.log(o.odds) - math.log(target / max(MIN_STAKE, 1)))))

    overlay = ctx.get("stake_overlay")
    combo_routes: list[tuple[float, dict, float]] = []
    if overlay:
        from bet_placer.engine.stake_sgm import estimate_stake_combo_probability
        from bet_placer.engine.card_coherence import stake_combo_fits_thesis
        for c in overlay.get("stake_combos") or []:
            odds = float(c.get("odds") or 0)
            if odds < 2.0 or odds > 10.0:
                continue
            if not stake_combo_fits_thesis(c, pool, home, away, human_context=ctx):
                continue
            hp = estimate_stake_combo_probability(c, pool, home, away)
            if hp < 0.12:
                continue
            combo_routes.append((hp, c, odds))
        combo_routes.sort(key=lambda x: (_sgm_route_sort_key(x[2], x[0]), x[0]), reverse=True)

    if not lotto and not combo_routes:
        return []

    best_per_n: dict[int, dict] = {}
    max_n = min(max_tickets_for_budget(budget), 8)
    max_deploy = budget * 0.88  # ponytail: slightly higher cap so 3-ticket spreads can fit

    def _max_insurance(_route_odds: float) -> int:
        # ponytail: ticket count from budget, not route odds — 6x routes still get 3+ slips.
        return min(6, max(1, max_tickets_for_budget(budget) - 1))

    def _min_insurance(route_odds: float) -> int:
        """Sub-7x routes can't fit 3+ tickets at profit target — need 1 insurance only."""
        if route_odds < 7.0:
            return 1
        return 2 if budget >= 80 else 1

    def _size_spread(insurance: list, route_odds: float) -> tuple[list[float], float] | None:
        n = len(insurance)
        if n < 1:
            return None
        stakes = [float(MIN_STAKE)] * n
        for _ in range(64):
            other = sum(stakes)
            route_stake = min_stake_for_profit(route_odds, profit_goal, other)
            total = other + route_stake
            if total > max_deploy + 0.01:
                return None
            spare = max_deploy - total
            if spare < 5 or n < 2:
                return stakes, route_stake
            idx = max(
                range(1, n),
                key=lambda i: float(getattr(insurance[i], "our_probability", 0) or 0),
            )
            stakes[idx] += 5
        other = sum(stakes)
        route_stake = min_stake_for_profit(route_odds, profit_goal, other)
        return stakes, route_stake

    def _try_plan(insurance: list, route_opt, route_odds: float, route_prob: float, route_is_combo: bool = False):
        min_ins = _min_insurance(route_odds)
        if len(insurance) < min_ins:
            return
        if _combo_contradicts(tuple(insurance), home, away):
            return
        if len(insurance) > _max_insurance(route_odds):
            return
        sized = _size_spread(insurance, route_odds)
        if not sized:
            lo = _min_insurance(route_odds)
            while len(insurance) > lo:
                insurance = insurance[:-1]
                sized = _size_spread(insurance, route_odds)
                if sized:
                    break
            if not sized:
                return
        ins_stakes, route_stake = sized
        total = sum(ins_stakes) + route_stake

        legs: list[dict] = []
        for i, opt in enumerate(insurance):
            role = "anchor" if i == 0 and opt.odds <= 2.4 else "support" if opt.odds <= 3.5 else "route"
            legs.append(_leg(opt, ins_stakes[i], role, _reason(opt, profile, "Spread ticket"), home, away))

        if route_is_combo:
            from bet_placer.engine.leg_explain import explain_leg
            route_leg = {
                "label": route_opt.get("label") or route_opt.get("stake_market"),
                "market": "stake_combo",
                "selection": route_opt.get("selection"),
                "line": route_opt.get("line"),
                "odds": route_odds,
                "stake_inr": route_stake,
                "our_probability": route_prob,
                "our_probability_pct": round(route_prob * 100, 1),
                "role": "target_lotto",
                "odds_source": "stake",
                "live_odds": True,
                "verified_stake": True,
                "stake_market": route_opt.get("stake_market"),
            }
            route_leg["reason"] = explain_leg(
                route_leg, home=home, away=away, budget=budget, target_cashout=target,
                all_legs=legs,
            )
        else:
            route_leg = _leg(route_opt, route_stake, "target_lotto", _reason(route_opt, profile, "Target lotto"), home, away)

        legs.append(route_leg)
        net = leg_net_if_solo_win(route_leg, legs)
        if net < floor_net:
            return

        route_leg["hits_target"] = True
        route_leg["profit_if_solo_inr"] = round(net, 0)
        route_leg["return_inr"] = round(route_stake * route_odds, 0)

        reserve = budget - total
        sc = _scenarios_multi(legs, reserve)
        probs = [float(l.get("our_probability") or 0) for l in legs if float(l.get("stake_inr") or 0) > 0]
        p_any = 1.0 - math.prod(1.0 - p for p in probs if p > 0)
        n = len(legs)
        labels_short = ", ".join(l.get("label", "")[:28] for l in legs[:3])
        if n > 3:
            labels_short += f" +{n - 3}"
        story = f"{fav_name} spread · " if fav_name else ""
        plan = {
            "plan_type": "match_card",
            "plan_type_label": f"Spread portfolio · {n} separate tickets",
            "name": f"🎫 {n}-ticket spread",
            "description": (
                f"{n} separate bets on Stake — {format_inr(total)} deployed, "
                f"{format_inr(reserve)} kept · lotto ticket nets {format_inr(net)} if it hits"
            ),
            "why": (
                f"{story}{n} separate tickets: "
                f"{len(insurance)} insurance stake{'s' if len(insurance) != 1 else ''} "
                f"({', '.join(format_inr(s) for s in ins_stakes)}) + "
                f"one minimal target route ({format_inr(route_stake)}). "
                f"~{p_any:.0%} any winner · target route ~{route_prob:.0%}."
            ),
            "path_headline": labels_short,
            "path_label": f"{n}-ticket spread · {labels_short}",
            "legs": legs,
            "total_stake_inr": total,
            "reserve_inr": reserve,
            "target_return_inr": target,
            "target_profit_inr": round(profit_goal, 0),
            "hit_probability": p_any,
            "hit_probability_pct": round(p_any * 100, 1),
            "model_alignment": round(sum(probs) / max(len(probs), 1) * 100, 1),
            "scenarios": sc,
            "stake_only": stake_only,
            "expected_value_inr": sc.get("expected_value_inr", 0),
            "feasibility": _feasibility(p_any, total / budget),
            "placement_mode": "separate_singles",
        }
        prev = best_per_n.get(n)
        route_p = float(route_leg.get("our_probability") or 0)
        score = route_p * 2 + p_any + n * 0.08 - total / budget
        if not prev or score > float(prev.get("_spread_score") or 0):
            plan["_spread_score"] = score
            best_per_n[n] = plan

    safe_top = safe[:8]
    med_top = medium[:10]
    lotto_top = lotto[:10]

    # Stake combo routes first — higher odds unlock more small insurance tickets.
    for hp, combo, odds in combo_routes[:12]:
        cap = _max_insurance(odds)
        lo = _min_insurance(odds)
        for n_ins in range(lo, min(cap, len(safe_top)) + 1):
            for s_combo in combinations(safe_top, n_ins):
                _try_plan(list(s_combo), combo, odds, hp, route_is_combo=True)
                if len(med_top) >= 1 and n_ins < cap:
                    for m1 in med_top[:6]:
                        if m1 in s_combo:
                            continue
                        _try_plan(list(s_combo) + [m1], combo, odds, hp, route_is_combo=True)
                if len(med_top) >= 2 and n_ins + 2 <= cap:
                    for m_combo in combinations(med_top[:6], 2):
                        ins = list(s_combo) + list(m_combo)
                        if len(ins) <= cap:
                            _try_plan(ins, combo, odds, hp, route_is_combo=True)

    for route_opt, route_odds, route_prob in [
        (o, float(o.odds), float(o.our_probability)) for o in lotto_top
    ]:
        cap = _max_insurance(route_odds)
        lo = _min_insurance(route_odds)
        for n_ins in range(lo, min(cap, len(safe_top)) + 1):
            for combo in combinations(safe_top, n_ins):
                _try_plan(list(combo), route_opt, route_odds, route_prob)
        if route_odds >= 7.0:
            for n_med in range(2, min(4, len(med_top) + 1)):
                for m_combo in combinations(med_top[:8], n_med):
                    anchor = safe_top[0] if safe_top else None
                    ins = ([anchor] if anchor else []) + list(m_combo)
                    if len(ins) >= lo and len(ins) <= cap:
                        _try_plan(ins, route_opt, route_odds, route_prob)

    for n_med in range(2, min(5, len(med_top) + 1)):
        for m_combo in combinations(med_top[:8], n_med):
            for route_opt, route_odds, route_prob in [
                (o, float(o.odds), float(o.our_probability)) for o in lotto_top[:4]
            ]:
                if len(m_combo) <= _max_insurance(route_odds):
                    _try_plan(list(m_combo), route_opt, route_odds, route_prob)

    out = list(best_per_n.values())
    out.sort(
        key=lambda p: (
            p.get("_spread_score", 0),
            len(p.get("legs") or []),
            p.get("hit_probability", 0),
        ),
        reverse=True,
    )
    for p in out:
        p.pop("_spread_score", None)
    return out[:MAX_PLANS]


def _search_volume_singles(
    pool, budget, target, profile, stake_only, ctx, betting_style, home, away,
) -> list[dict]:
    """Spread budget across 3–5 thesis-aligned singles — combined wins reach target."""
    from bet_placer.engine.match_card import _aligns_thesis

    search = _wide_pool(pool, ctx, stake_only, home, away)
    thesis_side = _thesis_side(ctx)
    n_target = min(8, max(4, int(round(betting_style.get("avg_bets_per_fixture") or 5))))
    cands = [
        o for o in search
        if o.odds > 1.15 and o.our_probability >= 0.10 and _aligns_thesis(o, thesis_side, home, away)
    ]
    cands.sort(key=lambda o: (-(o.our_probability + _leg_worth_bonus(o, ctx)), -o.odds))
    cands = cands[:16]
    out: list[dict] = []
    best_per_n: dict[int, dict] = {}
    max_n = min(n_target + 1, len(cands) + 1)
    n_values = list(range(max_n - 1, 1, -1))
    tries_per_n = max(12, MAX_COMBO_TRIES // max(len(n_values), 1))

    for n in n_values:
        per_stake = max(MIN_STAKE, _round(budget / n))
        if per_stake * n > budget:
            continue
        local_tries = 0
        for combo in combinations(cands, n):
            local_tries += 1
            if local_tries > tries_per_n:
                break
            if len({c.market for c in combo}) < n:
                continue
            if _combo_contradicts(combo, home, away):
                continue
            returns = [per_stake * o.odds for o in combo]
            probs = [o.our_probability for o in combo]
            p_any = 1.0 - math.prod(1.0 - p for p in probs)
            avg_prob = sum(probs) / n
            any_solo = max(returns, default=0) >= target * 0.90
            top2 = sum(sorted(returns, reverse=True)[:min(2, len(returns))])
            if not any_solo and p_any < 0.12 and top2 < target * 0.40:
                continue
            reserve = budget - per_stake * n
            legs = [
                _leg(opt, per_stake, "route", _reason(opt, profile, "Spread single"), home, away)
                for opt in combo
            ]
            sc = _scenarios_multi(legs, reserve)
            labels_short = ", ".join(c.label for c in combo[:3])
            if len(combo) > 3:
                labels_short += f" +{len(combo) - 3}"
            plan = {
                "plan_type": "match_card",
                "plan_type_label": f"Match card · {n} separate singles",
                "name": "🎫 Spread singles (your style)",
                "description": (
                    f"{n} separate singles ~{format_inr(per_stake)} each — "
                    f"combined wins can reach {format_inr(target)}"
                ),
                "why": (
                    f"{n} separate probable singles on this match — "
                    f"~{p_any:.0%} chance at least one lands "
                    f"(avg leg ~{avg_prob:.0%}). Spread beats one longshot ticket."
                ),
                "path_headline": labels_short,
                "path_label": (
                    labels_short if n <= 2 else f"{n}-leg spread · {labels_short}"
                ),
                "legs": legs,
                "total_stake_inr": per_stake * n,
                "reserve_inr": reserve,
                "target_return_inr": target,
                "target_profit_inr": round(target - per_stake * n, 0),
                "hit_probability": p_any,
                "hit_probability_pct": round(p_any * 100, 1),
                "model_alignment": round(sum(probs) / n * 100, 1),
                "scenarios": sc,
                "stake_only": stake_only,
                "expected_value_inr": sc.get("expected_value_inr", 0),
                "feasibility": _feasibility(p_any, (per_stake * n) / budget),
                "placement_mode": "separate_singles",
            }
            prev = best_per_n.get(n)
            if not prev or p_any > float(prev.get("hit_probability") or 0):
                best_per_n[n] = plan

    out = list(best_per_n.values())

    out.sort(
        key=lambda p: (
            p.get("hit_probability", 0),
            len(p.get("legs") or []),
            p.get("model_alignment", 0),
        ),
        reverse=True,
    )
    return out[:MAX_PLANS]


def _prefer_probable_spreads(plans: list[dict]) -> list[dict]:
    """Target-paying routes first — sorted by real win chance, not 'any leg hits'."""
    paying = [p for p in plans if (p.get("win_probability") or 0) > 0]
    if not paying:
        return plans
    paying.sort(
        key=lambda p: (
            p.get("win_probability", 0),
            len([l for l in (p.get("legs") or []) if float(l.get("stake_inr") or 0) > 0]),
            len([l for l in (p.get("legs") or []) if l.get("hits_target")]),
            len(p.get("legs") or []),
        ),
        reverse=True,
    )
    pay_sigs = {_plan_signature(p) for p in paying}
    tail = [p for p in plans if _plan_signature(p) not in pay_sigs]
    return paying + tail


def _score_plan_worth(plan: dict, ctx: dict, betting_style: dict | None = None) -> dict:
    """How suitable this path is — not just whether it can hit target."""
    style = betting_style or {}
    wp = float(plan.get("win_probability") or plan.get("hit_probability") or 0)
    hp = wp
    ev = float(plan.get("expected_value_inr", 0) or 0)
    stake = max(plan.get("total_stake_inr", 1), 1)
    ev_ratio = ev / stake
    ma = plan.get("model_alignment", 50) / 100.0
    type_bonus = {
        "coverage": 0.38,
        "match_card": 0.12,
        "single": -0.10,
        "split": -0.12,
        "combo": -0.28,
        "stake_combo": -0.20,
    }.get(plan.get("plan_type"), 0)
    from bet_placer.engine.bet_portfolio import _strategy_learning_weights
    lw = _strategy_learning_weights()
    if plan.get("plan_type") == "coverage":
        type_bonus += (float(lw.get("target_stack", 1) or 1) - 1.0) * 0.25
    if plan.get("placement_mode") == "separate_singles":
        type_bonus += (float(lw.get("target_hit", 1) or 1) - 1.0) * 0.15
    n_legs = len(plan.get("legs") or [])
    if plan.get("placement_mode") == "separate_singles" and n_legs >= 2:
        type_bonus += min(n_legs, 8) * 0.07
    if plan.get("plan_type") == "coverage" and n_legs >= 3:
        type_bonus += 0.14
    if n_legs >= 5:
        type_bonus += 0.12
    elif n_legs >= 4:
        type_bonus += 0.08
    if plan.get("plan_type") == "match_card":
        sgm_legs = [
            l for l in (plan.get("legs") or [])
            if l.get("verified_stake") and l.get("market") == "stake_combo"
        ]
        if len(sgm_legs) >= 2:
            type_bonus += 0.50
        elif len(sgm_legs) == 1:
            type_bonus += 0.20
    if style.get("prefers_spread_singles"):
        if plan.get("plan_type") == "match_card" and n_legs >= 3:
            type_bonus += 0.18
        elif plan.get("plan_type") == "single":
            type_bonus -= 0.35
        elif n_legs >= 3 and plan.get("placement_mode") == "separate_singles":
            type_bonus += 0.12
    if plan.get("plan_type") == "single" and hp < 0.22:
        type_bonus -= 0.30
    if plan.get("plan_type") == "combo":
        odds = float(plan.get("combined_odds") or 0)
        if 3.2 <= odds <= 6.5 and hp >= 0.18:
            type_bonus += 0.35
        elif 2.0 <= odds <= 8.5 and hp >= 0.12:
            type_bonus += 0.18
        else:
            type_bonus -= 0.10
    if plan.get("plan_type") == "stake_combo":
        odds = plan.get("combined_odds") or 0
        hp_combo = float(plan.get("hit_probability") or 0)
        if plan.get("verified_stake") and 2.0 <= odds <= 8.0 and hp_combo >= 0.18:
            type_bonus += 0.35
        elif plan.get("verified_stake") and 2.0 <= odds <= 8.0 and hp_combo >= 0.12:
            type_bonus += 0.15
        else:
            type_bonus -= 0.10
        ret = plan.get("target_return_inr") or 0
        tgt = float(ctx.get("target_cashout_inr") or ret or 1)
        if tgt > 0 and ret > tgt * 1.25:
            type_bonus -= 0.08
    if plan.get("placement_mode") == "separate_singles":
        type_bonus -= 0.08

    worth = hp * 0.62 + ma * 0.18 + max(-0.15, min(0.20, ev_ratio)) * 0.20 + type_bonus
    min_hp = 0.18 if plan.get("plan_type") == "single" else 0.14
    hits_target = float(plan.get("target_return_inr") or 0) >= float(ctx.get("target_cashout_inr") or 0) * 0.95
    worth_taking = wp > 0 and ev >= -stake * 0.08 and wp >= min_hp
    if plan.get("plan_type") in ("match_card", "coverage") and wp >= 0.12:
        worth_taking = True
    elif plan.get("plan_type") == "single" and hits_target and hp >= 0.20:
        worth_taking = True
    elif style.get("prefers_spread_singles") and plan.get("plan_type") == "single":
        worth_taking = hp >= 0.45
    elif (
        style.get("prefers_spread_singles")
        and plan.get("plan_type") == "match_card"
        and n_legs >= 3
    ):
        worth_taking = hp >= 0.14
    if plan.get("plan_type") == "stake_combo" and not plan.get("verified_stake"):
        worth_taking = False
    if plan.get("plan_type") == "stake_combo" and hp < 0.10:
        worth_taking = False
    # Moderate verified SGMs are always worth showing in target mode
    if (
        plan.get("plan_type") == "stake_combo"
        and plan.get("verified_stake")
        and 2.0 <= float(plan.get("combined_odds") or 0) <= 8.0
        and hp >= 0.15
    ):
        worth_taking = True
    if plan.get("plan_type") == "combo":
        odds = float(plan.get("combined_odds") or 0)
        worth_taking = hits_target and hp >= (0.12 if 2.0 <= odds <= 8.5 else 0.10)

    plan = dict(plan)
    hp = plan.get("hit_probability", 0)
    hp_pct = round(hp * 100, 1)
    ptype = plan.get("plan_type")
    wp = plan.get("win_probability", 0)
    wp_pct = round(wp * 100, 1)
    n_target = sum(1 for l in (plan.get("legs") or []) if l.get("hits_target"))
    plan["worth_score"] = round(float(worth), 4)
    plan["worth_taking"] = bool(worth_taking)
    plan["hit_probability"] = float(wp)
    plan["hit_probability_pct"] = wp_pct
    plan["worth_label"] = (
        f"{wp_pct}% to reach target · {n_target or len(plan.get('legs') or [])} route(s)"
        if wp >= 0.20
        else f"{wp_pct}% to reach target"
        if wp >= 0.08
        else f"Long shot · {wp_pct}% to reach target"
    )
    if not plan.get("path_headline"):
        plan["path_headline"] = plan.get("description", plan.get("name", ""))
    plan["path_steps"] = _path_steps(plan)
    return plan


def _path_steps(plan: dict) -> list[dict]:
    steps: list[dict] = []
    ptype = plan.get("plan_type")
    legs = plan.get("legs") or []

    if ptype == "match_card":
        for i, leg in enumerate(legs, 1):
            ret = leg.get("return_inr") or round((leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
            role = leg.get("role", "")
            is_sgm = role == "stake_combo"
            steps.append({
                "step": i,
                "title": f"{'Stake combo' if is_sgm else f'Ticket {i}'}: {leg.get('label')}",
                "detail": (
                    f"Stake combo on Stake Combos · stake {format_inr(leg.get('stake_inr', 0))} @ {leg.get('odds')}x "
                    f"→ {format_inr(ret)} if it wins"
                    if is_sgm else
                    f"Separate single · stake {format_inr(leg.get('stake_inr', 0))} @ {leg.get('odds')}x "
                    f"→ {format_inr(ret)} if it wins ({leg.get('our_probability_pct')}% chance)"
                ),
                "probability_pct": leg.get("our_probability_pct"),
            })
        steps.append({
            "step": len(legs) + 1,
            "title": "Realistic outcome",
            "detail": (
                f"Expect some to lose — ~{plan.get('hit_probability_pct')}% chance at least one line helps. "
                f"A longshot landing can cover the card."
            ),
            "probability_pct": plan.get("hit_probability_pct"),
        })
    elif ptype == "single":
        leg = legs[0] if legs else {}
        steps.append({
            "step": 1,
            "title": leg.get("label") or "Single bet",
            "detail": (
                f"Stake {format_inr(plan.get('total_stake_inr', 0))} @ {leg.get('odds')}x "
                f"→ {format_inr(plan.get('target_return_inr', 0))} if it wins"
            ),
            "probability_pct": leg.get("our_probability_pct"),
        })
        steps.append({
            "step": 2,
            "title": "Target reached",
            "detail": f"Payout {format_inr(plan.get('target_return_inr', 0))}",
            "probability_pct": plan.get("hit_probability_pct"),
        })
    elif ptype == "coverage":
        for i, leg in enumerate(legs, 1):
            ret = leg.get("return_inr") or round((leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
            steps.append({
                "step": i,
                "title": f"Route {i}: {leg.get('label')}",
                "detail": f"Stake {format_inr(leg.get('stake_inr', 0))} @ {leg.get('odds')}x → {format_inr(ret)} if it wins",
                "probability_pct": leg.get("our_probability_pct"),
            })
        steps.append({
            "step": len(steps) + 1,
            "title": "Target reached",
            "detail": f"Whichever route wins pays {format_inr(plan.get('target_return_inr', 0))}+",
            "probability_pct": plan.get("hit_probability_pct"),
        })
    elif ptype == "combo":
        for i, leg in enumerate(legs, 1):
            steps.append({
                "step": i,
                "title": f"Leg {i}: {leg.get('label')}",
                "detail": f"@ {leg.get('odds')}x ({leg.get('our_probability_pct')}% model chance)",
                "probability_pct": leg.get("our_probability_pct"),
            })
        steps.append({
            "step": len(legs) + 1,
            "title": "Custom combo",
            "detail": (
                f"Estimated same-match combo from our judgement. Stake {format_inr(plan.get('total_stake_inr', 0))} on all legs together "
                f"@ {plan.get('combined_odds')}x → {format_inr(plan.get('target_return_inr', 0))} if all hit"
            ),
            "probability_pct": plan.get("hit_probability_pct"),
        })
    elif ptype == "stake_combo":
        leg = legs[0] if legs else {}
        steps.append({
            "step": 1,
            "title": f"Stake combo: {leg.get('label') or plan.get('label')}",
            "detail": (
                f"Find under Stake Combos · "
                f"Stake {format_inr(plan.get('total_stake_inr', 0))} @ {plan.get('combined_odds')}x"
            ),
        })
        steps.append({
            "step": 2,
            "title": "Target reached",
            "detail": f"Payout {format_inr(plan.get('target_return_inr', 0))} if combo wins",
            "probability_pct": plan.get("hit_probability_pct"),
        })
    else:
        for i, leg in enumerate([l for l in legs if l.get("stake_inr", 0) > 0], 1):
            steps.append({
                "step": i,
                "title": leg.get("label"),
                "detail": (
                    f"Stake {format_inr(leg.get('stake_inr', 0))} @ {leg.get('odds')}x "
                    f"({leg.get('our_probability_pct')}% chance)"
                ),
                "probability_pct": leg.get("our_probability_pct"),
            })
        steps.append({
            "step": len(steps) + 1,
            "title": "Target reached",
            "detail": f"Payout {format_inr(plan.get('target_return_inr', 0))}",
            "probability_pct": plan.get("hit_probability_pct"),
        })
    return steps


def _feasibility(hit_prob: float, stake_ratio: float) -> str:
    if hit_prob >= 0.45 and stake_ratio <= 0.5:
        return "high"
    if hit_prob >= 0.20:
        return "medium"
    return "low"


def _pick_ranked_plans(plans: list[dict], max_n: int, ctx: dict | None = None) -> list[dict]:
    """Multi-ticket spreads first when competitive; then highest win %."""
    if not plans:
        return []
    ranked = sorted(plans, key=lambda p: _rank_key(p, ctx), reverse=True)
    multi = [p for p in ranked if _is_multi_slip_plan(p)]
    picked: list[dict] = []
    seen_sigs: set[tuple] = set()
    target_hit = bool((ctx or {}).get("target_hit_mode"))

    def _add(p: dict) -> None:
        if len(picked) >= max_n:
            return
        sig = _plan_signature(p)
        if not sig or sig in seen_sigs:
            return
        seen_sigs.add(sig)
        picked.append(p)

    best_wp = float(ranked[0].get("win_probability") or 0) if ranked else 0.0
    floor = best_wp * (0.55 if target_hit else 0.72)
    multi3 = [p for p in ranked if len([l for l in (p.get("legs") or []) if float(l.get("stake_inr") or 0) > 0]) >= 3]
    if target_hit and multi3:
        for p in sorted(multi3, key=lambda x: (
            len([l for l in (x.get("legs") or []) if float(l.get("stake_inr") or 0) > 0]),
            x.get("win_probability", 0),
        ), reverse=True)[:6]:
            _add(p)
    has_coverage = any(p.get("plan_type") == "coverage" for p in multi)
    for p in multi:
        n_tix = len([l for l in (p.get("legs") or []) if float(l.get("stake_inr") or 0) > 0])
        wp = float(p.get("win_probability") or 0)
        roles = {(l.get("role") or "") for l in (p.get("legs") or [])}
        if target_hit and has_coverage and p.get("plan_type") == "match_card" and roles & {"anchor", "target_lotto"}:
            continue
        if target_hit and n_tix >= 3 and wp >= max(0.04, floor * 0.6):
            _add(p)
        elif wp >= floor:
            _add(p)
    for p in ranked:
        _add(p)
    return picked if picked else ranked[:max_n]


def _rank_key(plan: dict, ctx: dict | None = None) -> tuple:
    wp = float(plan.get("win_probability") or 0)
    n_staked = len([l for l in (plan.get("legs") or []) if float(l.get("stake_inr") or 0) > 0])
    is_multi = _is_multi_slip_plan(plan)
    ptype = plan.get("plan_type")
    hits_goal = 1 if plan.get("hits_profit_goal") else 0
    n_target = sum(1 for l in (plan.get("legs") or []) if l.get("hits_target"))
    one_ticket = 1 if ptype in ("combo", "single", "stake_combo") else 0
    target_hit = bool((ctx or {}).get("target_hit_mode"))
    multi_boost = 0
    if target_hit:
        from bet_placer.engine.bet_portfolio import _strategy_learning_weights
        lw = _strategy_learning_weights()
        if ptype == "coverage":
            multi_boost += (float(lw.get("target_stack", 1) or 1) - 1.0) * 0.5
        if plan.get("placement_mode") == "separate_singles":
            multi_boost += (float(lw.get("target_hit", 1) or 1) - 1.0) * 0.3
            multi_boost = max(multi_boost, 3)
        elif n_staked >= 3:
            multi_boost = max(multi_boost, 2)
        elif n_staked >= 2:
            multi_boost = max(multi_boost, 0.5)
    return (multi_boost, wp, 1 if is_multi else 0, n_staked, hits_goal, n_target, -one_ticket)


def _moderate_route_tier(plan: dict) -> int:
    """Boost plans whose target route is a moderate SGM-style combo (2–8x)."""
    sgm_legs = [
        l for l in (plan.get("legs") or [])
        if l.get("verified_stake") and l.get("market") == "stake_combo"
    ]
    if len(sgm_legs) >= 2:
        return 4
    for leg in plan.get("legs") or []:
        odds = float(leg.get("odds") or 0)
        hp = float(leg.get("our_probability") or 0)
        role = leg.get("role") or ""
        if role in ("target_lotto", "stake_combo") and leg.get("verified_stake"):
            if 2.0 <= odds <= 8.0 and hp >= 0.15:
                return 3
            if 2.0 <= odds <= 10.0 and hp >= 0.12:
                return 2
            if odds > 12.0:
                return 0
    if plan.get("plan_type") == "stake_combo":
        odds = float(plan.get("combined_odds") or 0)
        hp = float(plan.get("hit_probability") or 0)
        if 2.0 <= odds <= 8.0 and hp >= 0.15:
            return 3
    if plan.get("plan_type") == "combo":
        odds = float(plan.get("combined_odds") or 0)
        hp = float(plan.get("hit_probability") or 0)
        n_legs = len(plan.get("legs") or [])
        if 2.0 <= odds <= 8.0 and hp >= 0.12 and 2 <= n_legs <= 3:
            return 3
    return 1


def _display_rank_key(plan: dict, target_hit: bool) -> tuple:
    """UI order — in target mode, coherent moderate combos should surface first."""
    wp = float(plan.get("win_probability") or 0)
    hp = float(plan.get("hit_probability") or 0)
    n_tix = plan.get("ticket_count") or len([
        l for l in (plan.get("legs") or []) if float(l.get("stake_inr") or 0) > 0
    ])
    ptype = plan.get("plan_type")
    is_parlay = 1 if ptype in ("combo",) else 0
    mod = _moderate_route_tier(plan)
    if target_hit:
        hits = 1 if plan.get("hits_profit_goal") else 0
        ticket_tier = (
            12 if n_tix >= 6 else 10 if n_tix >= 5 else 8 if n_tix >= 4
            else 6 if n_tix >= 3 else 2 if n_tix >= 2 else 0
        )
        parlay_penalty = -8 if ptype == "combo" else -4 if ptype == "single" else 0
        return (ticket_tier, max(wp, hp), hits, parlay_penalty, mod)
    return (wp, 1 if n_tix >= 2 else 0, n_tix, -is_parlay)


def _dedupe_plans(plans: list[dict]) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for p in plans:
        sig = _plan_signature(p)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(p)
    return out


def _plan_signature(plan: dict) -> tuple:
    """Dedupe by actual leg set — not stake sizing or plan labels."""
    legs = tuple(sorted(
        (l.get("market"), l.get("selection"), l.get("line"))
        for l in plan.get("legs", [])
    ))
    return legs


def _plan_win_probability(plan: dict, budget: float, target: float) -> float:
    """Chance this path actually reaches the cashout target — not 'any leg wins'."""
    from bet_placer.engine.bet_portfolio import leg_net_if_solo_win, target_profit_inr

    legs = plan.get("legs") or []
    ptype = plan.get("plan_type")
    profit_goal = target_profit_inr(budget, target)
    floor_return = target * 0.95
    floor_net = profit_goal * 0.95

    if ptype == "single" and legs:
        leg = legs[0]
        ret = float(leg.get("return_inr") or (leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
        if ret >= floor_return:
            return float(leg.get("our_probability") or 0)
        return 0.0

    if ptype in ("combo", "stake_combo", "split"):
        ret = float(plan.get("target_return_inr") or 0)
        if ret >= floor_return:
            return float(plan.get("hit_probability") or 0)
        return 0.0

    if ptype in ("match_card", "coverage"):
        win_probs: list[float] = []
        for leg in legs:
            ret = float(leg.get("return_inr") or (leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
            net = leg_net_if_solo_win(leg, legs)
            pays_target = (
                leg.get("hits_target")
                or ret >= floor_return
                or net >= floor_net
            )
            prob = float(leg.get("our_probability") or 0)
            if pays_target and prob > 0:
                win_probs.append(prob)
        if not win_probs:
            best_ret = max(
                (float(l.get("return_inr") or (l.get("stake_inr") or 0) * (l.get("odds") or 1)) for l in legs),
                default=0.0,
            )
            alt = plan.get("return_if_1_win_inr") or plan.get("best_return_inr")
            if alt is not None:
                best_ret = max(best_ret, float(alt))
            if best_ret >= floor_return:
                return float(plan.get("hit_probability") or 0)
            return 0.0
        return 1.0 - math.prod(1.0 - p for p in win_probs)

    ret = float(plan.get("target_return_inr") or 0)
    if ret >= floor_return:
        return float(plan.get("hit_probability") or 0)
    return 0.0


def _plan_profit_summary(plan: dict, budget: float, target: float) -> dict:
    """Net profit on this path — not the user's gross cashout goal."""
    from bet_placer.engine.bet_portfolio import leg_net_if_solo_win, target_profit_inr

    legs = plan.get("legs") or []
    total_stake = float(plan.get("total_stake_inr") or 0)
    ptype = plan.get("plan_type")
    profit_goal = target_profit_inr(budget, target)
    best_net = 0.0
    best_gross = float(plan.get("target_return_inr") or 0)

    if ptype == "single" and legs:
        leg = legs[0]
        best_gross = float(leg.get("return_inr") or (leg.get("stake_inr") or 0) * (leg.get("odds") or 1))
        best_net = best_gross - total_stake
    elif ptype in ("combo", "stake_combo", "split"):
        best_gross = float(plan.get("target_return_inr") or 0)
        best_net = best_gross - total_stake
    elif ptype in ("match_card", "coverage") and legs:
        route_roles = {"target_lotto", "stake_combo", "route", "main", "swing", "lottery", "lottery2"}
        route_legs = [l for l in legs if (l.get("role") or "") in route_roles]
        check = route_legs or legs
        nets = [
            leg_net_if_solo_win(l, legs)
            for l in check
            if float(l.get("stake_inr") or 0) > 0
        ]
        if nets:
            best_net = max(nets)
            idx = nets.index(best_net)
            winner = check[idx]
            best_gross = float(winner.get("return_inr") or 0)
        sc = plan.get("scenarios") or {}
        for key in ("return_if_1", "return_if_1_win_inr"):
            alt = sc.get(key) if isinstance(sc, dict) else None
            if alt is None:
                alt = plan.get(key)
            if alt is not None:
                net_alt = float(alt) - total_stake
                if net_alt > best_net:
                    best_net = net_alt
                    best_gross = float(alt)
    else:
        best_net = float(plan.get("target_profit_inr") or 0)

    win_prob = _plan_win_probability(plan, budget, target)
    return {
        "profit_goal_inr": round(profit_goal, 0),
        "target_profit_inr": round(best_net, 0),
        "best_profit_inr": round(best_net, 0),
        "best_return_inr": round(best_gross, 0),
        "hits_profit_goal": best_net >= profit_goal * 0.95,
        "win_probability": win_prob,
        "win_probability_pct": round(win_prob * 100, 1),
    }


def _annotate_plan(plan: dict, index: int, home: str, away: str, *, budget: float, target: float) -> dict:
    from bet_placer.engine.stake_sgm import build_tickets_from_plan

    feas = plan.get("feasibility", "low")
    feas_label = {"high": "Likely path", "medium": "Reachable", "low": "Long shot"}.get(feas, "Long shot")
    tickets = build_tickets_from_plan(plan, home, away)
    profit = _plan_profit_summary(plan, budget, target)
    rank_label = "Best path" if index == 1 else f"Path {index}"
    display_return = profit["best_return_inr"]
    headline = plan.get("path_headline") or ""
    n_tix = len(tickets)
    if n_tix >= 2 and plan.get("plan_type") in ("match_card", "coverage"):
        wp = profit.get("win_probability_pct", plan.get("hit_probability_pct"))
        headline = f"{n_tix} separate bets on Stake · {wp}% to target · {headline[:60]}"
        legs = plan.get("legs") or []
        if any(l.get("hits_target") for l in legs):
            headline = _target_route_headline(legs, target, profit["win_probability"])
    return {
        **plan,
        **profit,
        "path_headline": headline,
        "target_return_inr": display_return,
        "tickets": tickets,
        "ticket_count": len(tickets),
        "placement_mode": (
            "separate_singles" if plan.get("plan_type") in ("coverage", "match_card")
            else "stake_sgm" if plan.get("plan_type") == "stake_combo"
            else "parlay" if plan.get("plan_type") == "combo"
            else "single"
        ),
        "option_id": f"target_{index}",
        "option_index": index,
        "rank": index,
        "option_label": rank_label,
        "rank_label": f"#{index} · {rank_label}",
        "is_recommended_option": index == 1,
        "is_best_path": index == 1,
        "feasibility_label": feas_label,
    }


def _result(
    budget, target, plans, *, impossible, reason=None,
    max_achievable_inr=None, stake_only=False, profile=None, betting_style=None,
) -> dict:
    style = betting_style or {}
    return {
        "budget_inr": budget,
        "target_cashout_inr": target,
        "target_profit_inr": round(target - budget, 0),
        "required_multiplier": round(target / budget, 2) if budget else 0,
        "impossible": impossible,
        "impossible_reason": reason,
        "max_achievable_inr": max_achievable_inr,
        "plans": plans,
        "plan_count": len(plans),
        "stake_only": stake_only,
        "game_profile": profile or {},
        "betting_style": style,
        "engine": "target_planner_v10",
        "engine_note": "Thesis-aligned routes — favorite lean, props, and real win probability",
        "summary": (
            reason if impossible else
            (
                (
                    f"Best path ({plans[0].get('placement_mode', '').replace('_', ' ')}): "
                    f"{plans[0].get('path_headline')}"
                )
                if plans else "Could not assemble a valid plan."
            )
        ),
        "best_path": plans[0] if plans else None,
    }


def plan_hit_target_for_match(
    home: str,
    away: str,
    budget_inr: float,
    target_cashout_inr: float,
    *,
    goal: str | None = None,
    risk: str | None = None,
    structure: str | None = None,
    sport: str | None = None,
) -> dict:
    """End-to-end target planner for WC *or* open league fixtures."""
    from bet_placer.data.team_ratings import get_team_rating
    from bet_placer.data.worldcup2026 import get_all_group_matches, get_group_standings
    from bet_placer.engine.all_markets import predict_all_markets
    from bet_placer.engine.bet_builder import _find_wc_match, _resolve_league_match
    from bet_placer.engine.bettor_style import resolve_engine_style
    from bet_placer.engine.market_advisor import resolve_portfolio_options
    from bet_placer.engine.stake_odds import (
        apply_overlay_to_match,
        build_stake_overlay,
        get_cached_match_overlay,
        get_stake_overlay_map,
        match_overlay,
    )
    from bet_placer.engine.worldcup_pipeline import (
        _group_stakes_text,
        fan_read,
        wc_match_to_analysis_match,
    )

    betting_style = resolve_engine_style(
        goal, risk, structure,
        budget_inr=budget_inr,
        target_cashout_inr=target_cashout_inr,
    )

    wc = _find_wc_match(home, away, get_all_group_matches())
    match = None
    home_n = home
    away_n = away
    match_id = None
    human_context: dict = {"betting_style": betting_style}

    if wc:
        if wc.status == "completed":
            return {
                "available": False,
                "reason": "Match finished — no bets to plan.",
                "impossible": True,
                "plans": [],
                "home": wc.home,
                "away": wc.away,
            }
        match = wc_match_to_analysis_match(wc)
        home_n, away_n = wc.home, wc.away
        match_id = wc.id
        standings = get_group_standings(wc.group, get_all_group_matches())
        home_pts = next((s["pts"] for s in standings if s["team"] == wc.home), 0)
        away_pts = next((s["pts"] for s in standings if s["team"] == wc.away), 0)
        fan_take = fan_read(wc.home, wc.away, home_pts, away_pts, wc.home_must_win, wc.away_must_win)
        trending_on = (
            wc.home if wc.public_sentiment_home > 0.15
            else wc.away if wc.public_sentiment_home < -0.15 else None
        )
        human_context.update({
            "team_strength": {
                "home": get_team_rating(wc.home),
                "away": get_team_rating(wc.away),
            },
            "home_must_win": wc.home_must_win,
            "away_must_win": wc.away_must_win,
            "morale": {"home": wc.home_morale, "away": wc.away_morale},
            "narrative": wc.narrative,
            "public_sentiment_home": wc.public_sentiment_home,
            "fade_public": abs(wc.public_sentiment_home) > 0.2,
            "trending_on": trending_on,
            "fan_take": fan_take,
            "group_stakes": _group_stakes_text(wc.group, standings),
        })
    else:
        resolved = _resolve_league_match(home, away, sport=sport)
        if not resolved:
            return {
                "available": False,
                "reason": f"Couldn't find {home} vs {away} on the boards.",
                "impossible": True,
                "plans": [],
            }
        match, meta = resolved
        home_n, away_n = match.home_team, match.away_team
        match_id = getattr(match, "id", None) or f"{home_n}-{away_n}"
        if getattr(match, "status", None) == "completed":
            return {
                "available": False,
                "reason": "Match finished — no bets to plan.",
                "impossible": True,
                "plans": [],
                "home": home_n,
                "away": away_n,
            }
        human_context.update({
            "team_strength": {
                "home": get_team_rating(home_n),
                "away": get_team_rating(away_n),
            },
            "home_must_win": False,
            "away_must_win": False,
            "morale": {"home": 5, "away": 5},
            "narrative": getattr(match, "league", None) or (meta or {}).get("league"),
            "fan_take": None,
        })

    stake_priced = False
    stake_overlay = None
    try:
        overlay_map = get_stake_overlay_map(launch_browser=False)
        fixture = match_overlay(home_n, away_n, overlay_map)
        if fixture and fixture.markets:
            stake_overlay = build_stake_overlay(fixture)
            if apply_overlay_to_match(match, stake_overlay) > 0:
                stake_priced = True
    except Exception:
        pass
    if stake_overlay is None:
        cached = get_cached_match_overlay(home_n, away_n)
        if cached:
            stake_overlay = cached
            if apply_overlay_to_match(match, stake_overlay) > 0:
                stake_priced = True

    human_context["stake_priced"] = stake_priced
    human_context["stake_overlay"] = stake_overlay

    probabilities = predict_all_markets(match)
    # Build priced board BEFORE portfolio resolve — otherwise cloud (no Stake) returns []
    try:
        from bet_placer.engine.bet_builder import _match_thesis, build_match_flat_board
        from bet_placer.engine.smart_picks import build_smart_picks

        flat, board_source = build_match_flat_board(
            match, probabilities, budget_inr, human_context, home_n, away_n,
            launch_browser=False,
        )
        human_context["_flat_board"] = flat
        human_context["_board_source"] = board_source
        if board_source == "stake":
            human_context["stake_priced"] = True
        mw = {
            p.selection: p.probability
            for p in probabilities
            if getattr(p.market, "value", str(p.market)) == "match_winner"
        }
        thesis = _match_thesis(flat, home_n, away_n, model_probs=mw)
        human_context["match_thesis"] = thesis
        human_context["target_hit_mode"] = True
        picks = build_smart_picks(
            flat, home_n, away_n, match, probabilities, human_context, thesis=thesis,
        )
        human_context["unified_picks"] = picks.get("unified_picks") or []
        human_context["easy_money_picks"] = picks.get("easy_money") or []
    except Exception:
        pass

    options = resolve_portfolio_options(
        match, probabilities, budget_inr, human_context, home_n, away_n,
    )
    overlay = human_context.get("stake_overlay")
    if overlay:
        from bet_placer.engine.stake_odds import inject_goalscorer_options
        inject_goalscorer_options(options, overlay, home_n, away_n)

    result = build_target_plans(
        options, budget_inr, target_cashout_inr,
        home_n, away_n, match=match, probabilities=probabilities,
        human_context=human_context,
    )
    return {
        "available": True,
        "home": home_n,
        "away": away_n,
        "match_id": match_id,
        "stake_priced": human_context.get("stake_priced", False),
        **result,
        "betting_style": betting_style,
    }
