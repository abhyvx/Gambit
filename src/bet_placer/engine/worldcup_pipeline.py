"""World Cup 2026 full analysis pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bet_placer.api.serializers import serialize_value_bet
from bet_placer.consensus.web import WebConsensusFetcher
from bet_placer.data.odds_api import event_to_match
from bet_placer.data.team_ratings import (
    blended_strength,
    fan_read,
    get_team_rating,
    rating_to_xg,
)
from bet_placer.data.worldcup2026 import (
    get_all_group_matches,
    get_current_matchday,
    get_group_standings,
    get_groups,
    wc_match_to_event,
)
from bet_placer.data.wc_stages import (
    FILTER_ALL,
    build_stage_tabs,
    is_displayable_fixture,
    is_knockout_matchday,
    stage_label,
    stage_short,
)
from bet_placer.engine.all_markets import generate_all_market_odds, predict_all_markets
from bet_placer.models.enums import MarketType
from bet_placer.engine.bankroll import recommend_stake
from bet_placer.engine.budget_planner import build_betting_plan
from bet_placer.engine.ev import find_value_bets
from bet_placer.engine.match_slip import build_match_slip, serialize_slip
from bet_placer.engine.stake_odds import (
    apply_overlay_to_match,
    build_stake_overlay,
    get_stake_overlay_map,
    match_overlay,
)
from bet_placer.engine.verdict import MatchVerdictEngine
from bet_placer.explain.explainer import explain_bet
from bet_placer.intuition.analyst import AnalystIntuition
from bet_placer.markets.catalog import MARKET_COUNT, STAKE_SOCCER_MARKETS
from bet_placer.markets.odds import decimal_to_implied, remove_vig_three_way
from bet_placer.math.normalize import normalize_estimates
from bet_placer.models.stake_types import WebConsensus
from bet_placer.models.types import (
    AnalysisResult,
    ChemistrySignals,
    LeagueProfile,
    Match,
    TeamStats,
)
from bet_placer.portfolio.store import get_portfolio_profile

if TYPE_CHECKING:
    from bet_placer.data.worldcup2026 import WCMatch

logger = logging.getLogger(__name__)


def wc_match_to_analysis_match(wc: WCMatch) -> Match:
    event = wc_match_to_event(wc)
    match = event_to_match(event, "soccer_fifa_world_cup")

    standings_pts: dict[str, int] = {}
    if not wc.is_knockout and wc.matchday > 1:
        for s in get_group_standings(wc.group, get_all_group_matches()):
            standings_pts[s["team"]] = s["pts"]

    home_str = blended_strength(wc.home, standings_pts.get(wc.home, 0), wc.home_morale)
    away_str = blended_strength(wc.away, standings_pts.get(wc.away, 0), wc.away_morale)

    match.home_stats = TeamStats(
        name=wc.home,
        xg=rating_to_xg(home_str),
        xga=rating_to_xg(away_str) * 0.85,
        goals_scored=rating_to_xg(home_str),
        goals_conceded=rating_to_xg(away_str) * 0.85,
    )
    match.away_stats = TeamStats(
        name=wc.away,
        xg=rating_to_xg(away_str),
        xga=rating_to_xg(home_str) * 0.85,
        goals_scored=rating_to_xg(away_str),
        goals_conceded=rating_to_xg(home_str) * 0.85,
    )
    comp_name = (
        f"WC 2026 {stage_label(wc.matchday)}"
        if wc.is_knockout
        else f"WC 2026 Group {wc.group}"
    )
    match.league_profile = LeagueProfile(
        name=comp_name,
        avg_goals_per_match=2.45 if wc.is_knockout else 2.55,
        home_advantage_factor=0.05 if wc.is_knockout else 0.08,
    )
    match.chemistry = ChemistrySignals(
        morale_home=wc.home_morale,
        morale_away=wc.away_morale,
        notes=[wc.narrative] if wc.narrative else [],
    )
    match.sentiment_score_home = wc.public_sentiment_home
    match.kickoff = wc.kickoff

    # ALL Stake markets with WC-specific h2h odds blended in
    hi, di, ai = remove_vig_three_way(
        decimal_to_implied(wc.home_odds),
        decimal_to_implied(wc.draw_odds),
        decimal_to_implied(wc.away_odds),
    )
    match.market_odds = generate_all_market_odds(match, base_h2h=(hi, di, ai))

    # Overlay real O/U and BTTS from WC data
    for o in match.market_odds:
        if o.market.value == "over_under_goals" and o.line == 2.5:
            if o.selection == "over":
                o.best_odds = wc.over_25
            else:
                o.best_odds = wc.under_25
            o.implied_probability = 1 / o.best_odds
        if o.market.value == "btts":
            if o.selection == "yes":
                o.best_odds = wc.btts_yes
            else:
                o.best_odds = wc.btts_no
            o.implied_probability = 1 / o.best_odds

    return match


def analyze_worldcup(
    matchday: int | None = None,
    event_id: str | None = None,
    budget_inr: float = 2000.0,
    budget_per_match_inr: float | None = None,
    fast: bool = True,
    include_completed: bool = False,
    force_refresh: bool = False,
) -> dict:
    per_match = budget_per_match_inr if budget_per_match_inr is not None else max(100, budget_inr / 12)
    all_wc = get_all_group_matches(force_refresh=force_refresh)
    all_wc = [m for m in all_wc if is_displayable_fixture(m)]
    active_md = get_current_matchday(all_wc) if not matchday else matchday
    if event_id:
        wc_matches = [m for m in all_wc if m.id == event_id]
    elif matchday == FILTER_ALL:
        wc_matches = all_wc
        if not include_completed:
            wc_matches = [m for m in wc_matches if m.status in ("upcoming", "live")]
    elif matchday:
        wc_matches = [m for m in all_wc if m.matchday == matchday]
        if not include_completed:
            wc_matches = [m for m in wc_matches if m.status in ("upcoming", "live")]
    else:
        wc_matches = [m for m in all_wc if m.matchday == active_md]
        if not include_completed:
            wc_matches = [m for m in wc_matches if m.status in ("upcoming", "live")]

    intuition = AnalystIntuition()
    verdict_engine = MatchVerdictEngine()
    web_fetcher = WebConsensusFetcher()

    # Stake overlay: cache only on page load — never block the World Cup API on
    # a browser fetch (Cloudflare can hang 240s+). Stake prices load when you
    # open a match's Stake odds tab or the bet builder.
    stake_overlay_map = get_stake_overlay_map(
        force_refresh=force_refresh,
        launch_browser=False,
    )

    match_analyses = []
    slate_usage: dict[str, int] = {}
    for wc in wc_matches:
        match = wc_match_to_analysis_match(wc)

        # Re-price with Stake's real odds where we can confidently match.
        stake_priced = False
        stake_stats: dict = {}
        stake_repriced = 0
        stake_overlay: dict | None = None
        if stake_overlay_map and wc.status in ("upcoming", "live"):
            sfx = match_overlay(wc.home, wc.away, stake_overlay_map)
            if sfx is not None:
                try:
                    stake_overlay = build_stake_overlay(sfx)
                    stake_repriced = apply_overlay_to_match(match, stake_overlay)
                    stake_priced = stake_repriced > 0
                    stake_stats = stake_overlay.get("stats", {})
                except Exception as exc:
                    logger.warning(
                        "Stake overlay failed for %s vs %s: %s",
                        wc.home, wc.away, exc,
                    )
        raw_probs = predict_all_markets(match)
        adjusted = intuition.adjust_probabilities(match, raw_probs)
        adjusted = normalize_estimates(adjusted)
        factors = intuition.reasoning_factors(match)
        if wc.narrative:
            factors.append(wc.narrative)
        if wc.home_must_win:
            factors.append(f"{wc.home} MUST WIN — desperation raises variance")
        if wc.away_must_win:
            factors.append(f"{wc.away} MUST WIN — high motivation but risky")

        value_bets = find_value_bets(match, adjusted, factors)
        for bet in value_bets:
            bet.explanation = explain_bet(match, bet, adjusted, factors)

        if fast:
            web = WebConsensus(
                fixture_name=f"{wc.home} vs {wc.away}",
                home_pick_pct=0.4 + wc.public_sentiment_home,
                draw_pick_pct=0.25,
                away_pick_pct=0.35 - wc.public_sentiment_home,
                over_25_pct=0.52,
                btts_yes_pct=0.50,
                source_count=0,
                confidence=0.3,
                dominant_narrative=wc.narrative or (
                    f"{stage_label(wc.matchday)} — win-or-go-home"
                    if wc.is_knockout
                    else "Group stage — check team morale and must-win pressure"
                ),
                fade_public=abs(wc.public_sentiment_home) > 0.2,
            )
        else:
            web = web_fetcher.fetch(wc.home, wc.away, f"Group {wc.group}")
        analysis_obj = AnalysisResult(
            match=match,
            probabilities=adjusted,
            value_bets=value_bets,
            top_bets=sorted(value_bets, key=lambda b: b.rank_score, reverse=True)[:10],
        )
        verdict = verdict_engine.evaluate(analysis_obj, None, web, len(match.market_odds))

        enriched = []
        for bet in value_bets:
            rec = recommend_stake(bet.true_probability, bet.decimal_odds, bet.confidence, bet.risk_score, budget_inr)
            b = serialize_value_bet(bet)
            b["stake_recommendation"] = {
                "recommended_stake_inr": rec.recommended_stake,
                "recommended_pct": rec.recommended_pct,
                "risk_level": rec.risk_level,
                "plain_english": rec.plain_english.replace("$", "₹"),
                "expected_profit_inr": rec.expected_profit,
            }
            enriched.append(b)

        standings = [] if wc.is_knockout else get_group_standings(wc.group, all_wc)
        home_pts = next((s["pts"] for s in standings if s["team"] == wc.home), 0)
        away_pts = next((s["pts"] for s in standings if s["team"] == wc.away), 0)

        fan_take = fan_read(wc.home, wc.away, home_pts, away_pts, wc.home_must_win, wc.away_must_win)
        trending_on = wc.home if wc.public_sentiment_home > 0.15 else (wc.away if wc.public_sentiment_home < -0.15 else None)

        human_ctx = {
            "narrative": wc.narrative,
            "home_must_win": wc.home_must_win,
            "away_must_win": wc.away_must_win,
            "morale": {"home": wc.home_morale, "away": wc.away_morale},
            "web_narrative": web.dominant_narrative,
            "fade_public": web.fade_public,
            "group_stakes": (
                _knockout_stakes_text(wc)
                if wc.is_knockout
                else _group_stakes_text(wc.group, standings)
            ),
            "team_strength": {
                "home": blended_strength(wc.home, home_pts, wc.home_morale),
                "away": blended_strength(wc.away, away_pts, wc.away_morale),
            },
            "fan_take": fan_take,
            "trending_on": trending_on,
            "stake_priced": stake_priced,
            "stake_stats": stake_stats,
            "stake_repriced_count": stake_repriced,
            "stake_overlay": stake_overlay if stake_priced else None,
            "is_knockout": wc.is_knockout,
        }

        slip = None
        slip_data = None
        unified_picks: dict = {}
        if wc.status in ("upcoming", "live"):
            from bet_placer.engine.market_advisor import analyze_all_options
            from bet_placer.engine.smart_picks import (
                align_slip_with_picks, build_smart_picks, options_to_flat,
            )
            from bet_placer.engine.bet_builder import _match_thesis

            slip = build_match_slip(
                wc.id,
                f"{wc.home} vs {wc.away}",
                wc.home,
                wc.away,
                match,
                adjusted,
                per_match,
                human_ctx,
                {"verdict": verdict.verdict.value},
            )
            opts = analyze_all_options(match, adjusted, per_match, human_ctx)
            flat = options_to_flat(opts)
            mw = {p.selection: p.probability for p in adjusted if p.market == MarketType.MATCH_WINNER}
            thesis = _match_thesis(flat, wc.home, wc.away, model_probs=mw)
            unified_picks = build_smart_picks(
                flat, wc.home, wc.away, match, adjusted, human_ctx,
                thesis=thesis, matchday=wc.matchday, slate_usage=slate_usage,
            )
            slip_data = align_slip_with_picks(serialize_slip(slip), unified_picks)
        else:
            slip_data = serialize_slip(slip) if slip else None
        match_analyses.append({
            "fixture_id": wc.id,
            "group": wc.group,
            "matchday": wc.matchday,
            "stage": wc.stage or stage_short(wc.matchday),
            "stage_label": stage_label(wc.matchday),
            "is_knockout": wc.is_knockout,
            "name": f"{wc.home} vs {wc.away}",
            "home_team": wc.home,
            "away_team": wc.away,
            "kickoff": wc.kickoff.isoformat(),
            "status": wc.status,
            "status_detail": wc.status_detail,
            "score": f"{wc.home_score}-{wc.away_score}" if wc.status in ("completed", "live") and wc.home_score is not None else None,
            "home_score": wc.home_score,
            "away_score": wc.away_score,
            "team_ratings": {"home": get_team_rating(wc.home), "away": get_team_rating(wc.away)},
            "fan_prediction": fan_take,
            "group_standings": standings,
            "narrative": wc.narrative,
            "home_must_win": wc.home_must_win,
            "away_must_win": wc.away_must_win,
            "morale": {"home": wc.home_morale, "away": wc.away_morale},
            "markets_scanned": len(match.market_odds),
            "market_types": len(STAKE_SOCCER_MARKETS),
            "bet_slip": slip_data,
            "unified_picks": unified_picks.get("unified_picks", []),
            "situational_picks": unified_picks.get("situational_picks", []),
            "easy_money": unified_picks.get("easy_money", []),
            "parlay_suggestion": unified_picks.get("parlay_suggestion"),
            "odds_source": "stake" if stake_priced else wc.odds_source,
            "stake_priced": stake_priced,
            "stake_repriced_count": stake_repriced,
            "data_source": wc.data_source,
            "verdict": {
                "verdict": verdict.verdict.value,
                "headline": verdict.headline,
                "reasoning": verdict.reasoning,
                "best_bet": verdict.best_bet,
                "risk_flags": verdict.risk_flags,
            },
            "web_consensus": {
                "narrative": web.dominant_narrative,
                "home_pct": web.home_pick_pct,
                "away_pct": web.away_pick_pct,
                "fade_public": web.fade_public,
                "sources": web.source_count,
            },
            "value_bets": enriched,
            "top_bets": _top_bets_from_unified(unified_picks, enriched),
            "all_markets_sample": [
                {"market": o.market.value, "selection": o.selection, "line": o.line, "odds": o.best_odds}
                for o in match.market_odds[:30]
            ],
        })

    plan = build_betting_plan(match_analyses, per_match * len(match_analyses))

    groups_dict = get_groups()
    groups_summary = {
        g: {"teams": teams, "standings": get_group_standings(g, all_wc)}
        for g, teams in groups_dict.items()
    }

    live_count = sum(1 for m in all_wc if m.status == "live")
    completed_count = sum(1 for m in all_wc if m.status == "completed")
    knockout_count = sum(1 for m in all_wc if m.is_knockout)
    stage_counts = {
        stage_label(md): sum(1 for m in all_wc if m.matchday == md)
        for md in sorted({m.matchday for m in all_wc})
    }

    active_label = stage_label(active_md) if is_knockout_matchday(active_md) else f"Matchday {active_md}"
    portfolio_profile = get_portfolio_profile()

    return {
        "tournament": "FIFA World Cup 2026",
        "matchday": matchday if matchday is not None else active_md,
        "active_matchday": active_md,
        "active_stage_label": active_label,
        "match_count": len(match_analyses),
        "live_match_count": live_count,
        "completed_match_count": completed_count,
        "knockout_match_count": knockout_count,
        "stage_counts": stage_counts,
        "stage_tabs": build_stage_tabs(all_wc),
        "markets_per_match": MARKET_COUNT,
        "currency": "INR",
        "budget_per_match_inr": per_match,
        "budget_inr": budget_inr,
        "data_source": "espn_live",
        "odds_source": "espn_draftkings",
        "odds_note": "Live scores from ESPN. Payouts from DraftKings (via ESPN) — check Stake for your exact prices.",
        "groups": groups_summary,
        "matches": match_analyses,
        "betting_plan": _serialize_plan(plan),
        "personalization": {
            "enabled": bool(portfolio_profile),
            "profile": portfolio_profile,
        },
        "source": "espn_live",
        "message": (
            f"LIVE from ESPN — {live_count} in progress, {completed_count} finished, "
            f"{knockout_count} knockout fixtures in feed. "
            f"{active_label} active. Real book payouts (DraftKings)."
        ),
        "knockout_data_note": None,
    }


def _top_bets_from_unified(unified_picks: dict, enriched: list) -> list:
    """Main-page top bets = same brain as build slip (easy money first)."""
    out = []
    for p in (unified_picks.get("easy_money") or []) + (unified_picks.get("unified_picks") or []):
        out.append({
            "selection": p.get("label"),
            "market": p.get("market"),
            "decimal_odds": p.get("odds"),
            "true_probability": p.get("our_probability"),
            "edge_pct": p.get("edge_pct"),
            "tag": p.get("tag"),
            "explanation": p.get("why") or p.get("reason"),
            "rank_score": (p.get("our_probability") or 0) * 100,
        })
        if len(out) >= 5:
            return out
    return out or enriched[:5]


def _knockout_stakes_text(wc) -> str:
    return f"{stage_label(wc.matchday)} — elimination game, no second chances"


def _group_stakes_text(group: str, standings: list[dict]) -> str:
    if not standings:
        return f"Group {group} — check standings"
    top = standings[0]["team"]
    pts = standings[0]["pts"]
    return f"Group {group}: {top} leads with {pts} pts — qualification race affects motivation"


def _serialize_plan(plan) -> dict:
    return {
        "budget_inr": plan.budget_inr,
        "currency": "INR",
        "verdict_overall": plan.verdict_overall,
        "summary": plan.summary,
        "total_staked_inr": plan.total_staked_inr,
        "total_remaining_inr": plan.total_remaining_inr,
        "rules": plan.rules,
        "singles": [
            {
                "match": s.match, "market": s.market, "selection": s.selection,
                "line": s.line, "odds": s.odds, "stake_inr": s.stake_inr,
                "ev_pct": round(s.ev_pct, 1), "risk": s.risk, "reason": s.reason,
            }
            for s in plan.singles
        ],
        "parlays": [
            {
                "legs": [{"match": l.match, "market": l.market, "selection": l.selection, "odds": l.odds} for l in p.legs],
                "combined_odds": p.combined_odds,
                "stake_inr": p.stake_inr,
                "potential_return_inr": p.potential_return_inr,
                "true_prob": round(p.true_prob, 3),
                "ev_pct": round(p.ev_pct, 1),
                "risk": p.risk,
                "reason": p.reason,
            }
            for p in plan.parlays
        ],
        "skip_matches": plan.skip_matches,
    }
