"""Map Stake fixtures and markets into internal Match / MarketOdds types."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from bet_placer.markets.odds import decimal_to_implied
from bet_placer.models.enums import MarketType
from bet_placer.models.stake_types import StakeFixture, StakeMarket
from bet_placer.models.types import (
    LeagueProfile,
    MarketOdds,
    Match,
    TacticalProfile,
    TeamStats,
)


def stake_fixture_to_match(fixture: StakeFixture) -> Match:
    """Build Match from Stake. Team stats use league priors — NOT bookmaker odds."""
    from bet_placer.data.odds_api import LEAGUE_PRIORS

    priors = LEAGUE_PRIORS["soccer"]
    home_stats = TeamStats(
        name=fixture.home_team,
        goals_scored=priors["home_xg"],
        goals_conceded=priors["away_xg"],
        xg=priors["home_xg"],
        xga=priors["away_xg"],
    )
    away_stats = TeamStats(
        name=fixture.away_team,
        goals_scored=priors["away_xg"],
        goals_conceded=priors["home_xg"],
        xg=priors["away_xg"],
        xga=priors["home_xg"],
    )
    kickoff = fixture.kickoff or datetime.now(timezone.utc)
    market_odds = parse_stake_markets(fixture)

    return Match(
        id=f"stake-{fixture.id}",
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        league=fixture.league,
        kickoff=kickoff,
        home_stats=home_stats,
        away_stats=away_stats,
        home_tactics=TacticalProfile(),
        away_tactics=TacticalProfile(),
        league_profile=LeagueProfile(name=fixture.league),
        market_odds=market_odds,
        sentiment_score_home=0.0,
        sentiment_score_away=0.0,
    )


def parse_stake_markets(fixture: StakeFixture) -> list[MarketOdds]:
    odds_list: list[MarketOdds] = []
    seen: set[tuple] = set()

    for market in fixture.markets:
        parsed = _classify_market(market, fixture.home_team, fixture.away_team)
        if not parsed:
            continue
        market_type, selections = parsed
        for sel, outcome in selections:
            key = (market_type, sel, outcome.get("line"))
            if key in seen:
                continue
            seen.add(key)
            decimal = outcome["odds"]
            odds_list.append(MarketOdds(
                market=market_type,
                selection=sel,
                line=outcome.get("line"),
                best_odds=decimal,
                avg_odds=decimal,
                implied_probability=decimal_to_implied(decimal),
                bookmaker_count=1,
            ))
    return odds_list


def _classify_market(
    market: StakeMarket,
    home: str,
    away: str,
) -> tuple[MarketType, list[tuple[str, dict]]] | None:
    name = market.name.lower()
    group = market.group.lower()
    results: list[tuple[str, dict]] = []

    # Match winner / 1X2
    if any(k in name or k in group for k in ("winner", "threeway", "1x2", "match result")):
        for oc in market.outcomes:
            sel = _map_team_selection(oc.name, home, away)
            if sel:
                results.append((sel, {"odds": oc.odds, "line": market.line}))
        if results:
            return MarketType.MATCH_WINNER, results

    # Over/Under goals
    if "total" in name or "over" in name or "under" in name or "goals" in group:
        line = market.line or _parse_total_line(name)
        for oc in market.outcomes:
            oc_name = oc.name.lower()
            if "over" in oc_name:
                results.append(("over", {"odds": oc.odds, "line": line}))
            elif "under" in oc_name:
                results.append(("under", {"odds": oc.odds, "line": line}))
        if results and line:
            return MarketType.OVER_UNDER_GOALS, results

    # BTTS
    if "both teams" in name or "btts" in name or "btts" in group:
        for oc in market.outcomes:
            oc_name = oc.name.lower()
            if oc_name in ("yes", "y"):
                results.append(("yes", {"odds": oc.odds, "line": None}))
            elif oc_name in ("no", "n"):
                results.append(("no", {"odds": oc.odds, "line": None}))
        if results:
            return MarketType.BTTS, results

    # Corners
    if "corner" in name or "corner" in group:
        line = market.line or _parse_total_line(name)
        for oc in market.outcomes:
            oc_name = oc.name.lower()
            if "over" in oc_name:
                results.append(("over", {"odds": oc.odds, "line": line}))
            elif "under" in oc_name:
                results.append(("under", {"odds": oc.odds, "line": line}))
        if results:
            return MarketType.CORNERS, results

    # Cards
    if "card" in name or "booking" in name:
        line = market.line or _parse_total_line(name)
        for oc in market.outcomes:
            oc_name = oc.name.lower()
            if "over" in oc_name:
                results.append(("over", {"odds": oc.odds, "line": line}))
            elif "under" in oc_name:
                results.append(("under", {"odds": oc.odds, "line": line}))
        if results:
            return MarketType.CARDS, results

    # Asian handicap
    if "handicap" in name or "handicap" in group:
        for oc in market.outcomes:
            sel = _map_team_selection(oc.name, home, away)
            if sel:
                results.append((sel, {"odds": oc.odds, "line": market.line}))
        if results:
            return MarketType.ASIAN_HANDICAP, results

    return None


def _map_team_selection(outcome_name: str, home: str, away: str) -> str | None:
    n = outcome_name.lower().strip()
    if n in ("draw", "x", "tie"):
        return "draw"
    if home.lower() in n or n in ("1", "home"):
        return "home"
    if away.lower() in n or n in ("2", "away"):
        return "away"
    # Partial match on team name words
    home_words = [w for w in home.lower().split() if len(w) > 3]
    away_words = [w for w in away.lower().split() if len(w) > 3]
    if any(w in n for w in home_words):
        return "home"
    if any(w in n for w in away_words):
        return "away"
    return None


def _parse_total_line(name: str) -> float | None:
    m = re.search(r"(\d+\.?\d*)", name)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 2.5


def _estimate_stats_from_odds(fixture: StakeFixture) -> tuple[TeamStats, TeamStats]:
    """Weak prior for team stats derived from Stake winner market odds."""
    home_odds = away_odds = draw_odds = None
    for market in fixture.markets:
        name = market.name.lower()
        if "winner" in name or "1x2" in name or market.group.lower() in ("winner", "threeway"):
            for oc in market.outcomes:
                sel = _map_team_selection(oc.name, fixture.home_team, fixture.away_team)
                if sel == "home":
                    home_odds = oc.odds
                elif sel == "away":
                    away_odds = oc.odds
                elif sel == "draw":
                    draw_odds = oc.odds

    if not home_odds:
        return (
            TeamStats(name=fixture.home_team, xg=1.4, xga=1.2, goals_scored=1.4, goals_conceded=1.2),
            TeamStats(name=fixture.away_team, xg=1.2, xga=1.3, goals_scored=1.2, goals_conceded=1.3),
        )

    from bet_placer.markets.odds import remove_vig_three_way

    hi = 1 / home_odds
    ai = 1 / away_odds if away_odds else 0.25
    di = 1 / draw_odds if draw_odds else 0.25
    hp, _, ap = remove_vig_three_way(hi, di, ai)

    home_xg = 0.8 + hp * 2.0
    away_xg = 0.8 + ap * 2.0
    return (
        TeamStats(name=fixture.home_team, xg=home_xg, xga=away_xg * 0.9, goals_scored=home_xg, goals_conceded=away_xg * 0.9),
        TeamStats(name=fixture.away_team, xg=away_xg, xga=home_xg * 0.9, goals_scored=away_xg, goals_conceded=home_xg * 0.9),
    )
