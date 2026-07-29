"""Per-match betting slip with loss-minimizing strategies + factor analysis."""

from __future__ import annotations

from dataclasses import dataclass

from bet_placer.engine.bet_portfolio import build_portfolios
from bet_placer.engine.factor_engine import analyze_match_factors
from bet_placer.engine.market_advisor import resolve_portfolio_options, serialize_option


@dataclass
class MatchBetSlip:
    match_id: str
    match_name: str
    home_team: str
    away_team: str
    budget_inr: float
    verdict: str
    headline: str
    human_story: list[str]
    all_options: list[dict]
    strategies: dict
    recommended_strategy: str
    active_strategy: dict
    payout_scenarios: dict
    factor_analysis: dict
    game_profile: dict
    stake_priced: bool
    stake_stats: dict
    stake_repriced_count: int
    odds_origin: str
    total_stake_inr: float
    keep_unbet_inr: float
    plain_english: str
    alternative_slips: list[dict]
    bet_slips: list[dict]
    recommended_slip_id: str
    strategy_plans: dict
    skip_recommended: bool
    skip_reason: str | None
    portfolio_engine: str
    # legacy
    recommended_singles: list[dict]
    recommended_parlay: dict | None
    curated_picks: dict | None = None
    stake_from_cache: bool = False


def build_match_slip(
    match_id: str,
    match_name: str,
    home: str,
    away: str,
    match: object,
    probabilities: list,
    budget_per_match_inr: float,
    human_context: dict,
    verdict: dict,
) -> MatchBetSlip:
    options = resolve_portfolio_options(
        match, probabilities, budget_per_match_inr, human_context, home, away,
    )
    all_serialized = [serialize_option(o) for o in options]
    stake_priced = bool(human_context.get("stake_priced"))
    stake_from_cache = bool(human_context.get("stake_from_cache"))
    stake_stats = human_context.get("stake_stats") or {}
    stake_repriced_count = int(human_context.get("stake_repriced_count") or 0)
    odds_origin = "stake" if stake_priced else "live_book"
    factors = analyze_match_factors(match, probabilities, options, human_context)
    human_story = _build_human_story(human_context, home, away)

    portfolios = build_portfolios(
        options, budget_per_match_inr, home, away,
        live_h2h_odds=True,
        match=match,
        probabilities=probabilities,
        human_context=human_context,
    )
    rec_id = portfolios.get("recommended_slip_id") or portfolios.get("recommended_strategy")
    if rec_id and "_" in str(rec_id):
        rec_id = str(rec_id).rsplit("_", 1)[0]
    if rec_id == "safe":
        rec_id = "min_loss"
    strategy_plans = portfolios.get("strategy_plans") or {}
    active = _resolve_strategy_plan(portfolios["strategies"], rec_id)
    if not active.get("legs") and portfolios.get("bet_slips"):
        active = portfolios["bet_slips"][0]
        rec_id = active.get("tab_id") or active.get("id", rec_id)
    scenarios = active.get("scenarios") or portfolios.get("payout_scenarios", {})

    total_stake = active.get("total_stake_inr", 0)
    reserve = active.get("reserve_inr", budget_per_match_inr)

    # Legacy singles from active strategy legs
    recommended_singles = [
        {**leg, "value_label": leg.get("role", "bet"), "stake_advice": leg.get("reason", "")}
        for leg in active.get("legs", [])
        if leg.get("stake_inr", 0) > 0
    ]
    parlay_plans = strategy_plans.get("smart_parlay") or []
    parlay = parlay_plans[0] if parlay_plans else portfolios["strategies"].get("smart_parlay")
    if parlay and not parlay.get("legs"):
        parlay = None

    skip_recommended = bool(portfolios.get("skip_recommended"))
    skip_reason = portfolios.get("skip_reason")

    # Prefer any strategy with legs over a blank SKIP — user asked for recs, not silence.
    if (not active.get("legs") or rec_id == "skip") and strategy_plans:
        for key in ("match_card", "min_loss", "singles_focus", "value", "smart_parlay"):
            plans = strategy_plans.get(key) or []
            if isinstance(plans, dict):
                plans = [plans] if plans.get("legs") else []
            hit = next((p for p in plans if (p.get("legs") or [])), None)
            if hit:
                active = hit
                rec_id = hit.get("tab_id") or hit.get("id") or key
                skip_recommended = False
                break

    if not active.get("legs") or rec_id == "skip":
        # Last resort: still CAUTION with empty plan rather than hard SKIP_MATCH noise
        slip_verdict = "CAUTION"
        headline = f"Thin board — {match_name}"
        plain = skip_reason or (
            f"Model markets are thin for this fixture. "
            f"Keep most of {budget_per_match_inr:,.0f} or pick from the Odds / Build tabs."
        )
        skip_recommended = True
    elif skip_recommended:
        slip_verdict = "CAUTION"
        headline = f"Thin edge — {match_name}"
        plain = (skip_reason or "Nothing here clears our bar on the typical outcome.") + " " + _plain_portfolio(active, factors, budget_per_match_inr)
    elif rec_id == "match_card":
        slip_verdict = "BET"
        headline = f"Your match card — {match_name}"
        plain = _plain_portfolio(active, factors, budget_per_match_inr)
    elif rec_id == "smart_parlay":
        slip_verdict = "CAUTION"
        headline = f"Smart parlay — {match_name}"
        plain = _plain_portfolio(active, factors, budget_per_match_inr)
    elif rec_id == "singles_focus":
        slip_verdict = "BET"
        headline = f"Best single — {match_name}"
        plain = _plain_portfolio(active, factors, budget_per_match_inr)
    else:
        slip_verdict = "BET"
        headline = f"Loss-minimizing plan — {match_name}"
        plain = _plain_portfolio(active, factors, budget_per_match_inr)

    return MatchBetSlip(
        match_id=match_id,
        match_name=match_name,
        home_team=home,
        away_team=away,
        budget_inr=budget_per_match_inr,
        verdict=slip_verdict,
        headline=headline,
        human_story=human_story,
        all_options=all_serialized,
        strategies=portfolios["strategies"],
        recommended_strategy=rec_id,
        active_strategy=active,
        payout_scenarios=scenarios,
        factor_analysis=factors,
        game_profile=portfolios.get("game_profile", {}),
        stake_priced=stake_priced,
        stake_stats=stake_stats,
        stake_repriced_count=stake_repriced_count,
        odds_origin=odds_origin,
        total_stake_inr=total_stake,
        keep_unbet_inr=reserve,
        plain_english=plain,
        alternative_slips=portfolios.get("alternative_slips", []),
        bet_slips=portfolios.get("bet_slips", []),
        recommended_slip_id=portfolios.get("recommended_slip_id", rec_id),
        strategy_plans=portfolios.get("strategy_plans", {}),
        curated_picks=portfolios.get("curated_picks"),
        skip_recommended=skip_recommended,
        skip_reason=skip_reason,
        portfolio_engine=portfolios.get("portfolio_engine", "v1"),
        recommended_singles=recommended_singles,
        recommended_parlay=parlay if parlay and parlay.get("stake_inr") else None,
        stake_from_cache=stake_from_cache,
    )


def _plain_portfolio(strategy: dict, factors: dict, budget: float) -> str:
    parts = [strategy.get("description", ""), strategy.get("why", "")]
    sc = strategy.get("scenarios", {})
    if sc.get("worst_case"):
        parts.append(f"Worst: {sc['worst_case']['description']}")
    if sc.get("likely_case"):
        parts.append(f"Likely: {sc['likely_case']['description']}")
    if sc.get("best_case"):
        parts.append(f"Best: {sc['best_case']['description']}")
    parts.append(f"Based on {factors['factors_analyzed']:,} factor checks.")
    return " ".join(p for p in parts if p)


def _resolve_strategy_plan(strategies: dict, key: str) -> dict:
    raw = strategies.get(key, {})
    if isinstance(raw, list):
        return raw[0] if raw else {}
    return raw if isinstance(raw, dict) else {}


def _build_human_story(ctx: dict, home: str, away: str) -> list[str]:
    story = []
    if ctx.get("fan_take"):
        story.append(f"🗣️ {ctx['fan_take']}")
    if ctx.get("narrative"):
        story.append(f"📰 {ctx['narrative']}")
    if ctx.get("home_must_win"):
        story.append(f"⚡ {home} MUST WIN")
    if ctx.get("away_must_win"):
        story.append(f"⚡ {away} MUST WIN")
    morale = ctx.get("morale", {})
    if morale.get("home"):
        story.append(f"💪 {home} morale: {morale['home']}/10")
    if morale.get("away"):
        story.append(f"💪 {away} morale: {morale['away']}/10")
    if ctx.get("group_stakes"):
        story.append(f"🏆 {ctx['group_stakes']}")
    read = ctx.get("analyst_read") or {}
    if read.get("summary"):
        story.append(f"📊 {read['summary'][:220]}")
    if read.get("tags"):
        story.append(" · ".join(read["tags"][:4]))
    st = ctx.get("stake_stats") or {}
    if ctx.get("stake_priced") and st.get("total_bets"):
        story.append(
            f"💸 Priced from Stake — {st['total_bets']:,} bets / "
            f"${st.get('total_bet_value_usd', 0):,.0f} staked on this game"
        )
    return story


def serialize_slip(slip: MatchBetSlip) -> dict:
    return {
        "match_id": slip.match_id,
        "match_name": slip.match_name,
        "budget_inr": slip.budget_inr,
        "verdict": slip.verdict,
        "headline": slip.headline,
        "human_story": slip.human_story,
        "all_options": slip.all_options,
        "strategies": slip.strategies,
        "recommended_strategy": slip.recommended_strategy,
        "active_strategy": slip.active_strategy,
        "payout_scenarios": slip.payout_scenarios,
        "factor_analysis": slip.factor_analysis,
        "game_profile": slip.game_profile,
        "stake_priced": slip.stake_priced,
        "stake_from_cache": slip.stake_from_cache,
        "stake_stats": slip.stake_stats,
        "stake_repriced_count": slip.stake_repriced_count,
        "odds_origin": slip.odds_origin,
        "recommended_singles": slip.recommended_singles,
        "recommended_parlay": slip.recommended_parlay,
        "skip_all_others": True,
        "total_stake_inr": slip.total_stake_inr,
        "keep_unbet_inr": slip.keep_unbet_inr,
        "plain_english": slip.plain_english,
        "alternative_slips": slip.alternative_slips,
        "bet_slips": slip.bet_slips,
        "recommended_slip_id": slip.recommended_slip_id,
        "strategy_plans": slip.strategy_plans,
        "curated_picks": slip.curated_picks,
        "portfolio_engine": getattr(slip, "portfolio_engine", None),
        "skip_recommended": slip.skip_recommended,
        "skip_reason": slip.skip_reason,
        "options_by_category": _group_by_category(slip.all_options),
    }


def _group_by_category(options: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for o in options:
        grouped.setdefault(o["category"], []).append(o)
    return grouped
