from __future__ import annotations

from bet_placer.models.types import ExternalFactors, HeadToHead, LeagueProfile, Match
from bet_placer.models.enums import MatchContext


def analyze_external(match: Match) -> dict[str, float]:
    ext = match.external
    weather_attack_boost = 0.0
    if ext.weather in ("rain", "light_rain", "snow"):
        weather_attack_boost = 0.03  # more errors, more goals historically
    if ext.wind_speed_kmh > 25:
        weather_attack_boost -= 0.02

    rest_edge = (ext.rest_days_home - ext.rest_days_away) / 14.0
    congestion_penalty_home = ext.fixture_congestion_home * 0.05
    congestion_penalty_away = ext.fixture_congestion_away * 0.05

    motivation_home = 0.0
    motivation_away = 0.0
    if match.context == MatchContext.TITLE_RACE:
        motivation_home = motivation_away = 0.04
    elif match.context == MatchContext.RELEGATION:
        motivation_home = motivation_away = 0.05
    elif match.context == MatchContext.DERBY:
        motivation_home = 0.03
    elif match.context == MatchContext.MUST_WIN:
        motivation_home = 0.04
    elif match.context == MatchContext.DEAD_RUBBER:
        motivation_home = motivation_away = -0.03

    return {
        "weather_attack_boost": weather_attack_boost,
        "rest_edge_home": max(-0.1, min(0.1, rest_edge)),
        "congestion_penalty_home": congestion_penalty_home,
        "congestion_penalty_away": congestion_penalty_away,
        "motivation_home": motivation_home,
        "motivation_away": motivation_away,
        "crowd_boost": (ext.crowd_intensity - 5) / 50.0,
    }


def analyze_h2h(h2h: HeadToHead) -> dict[str, float]:
    total = h2h.home_wins + h2h.draws + h2h.away_wins
    if total == 0:
        return {"h2h_home_edge": 0.0, "h2h_btts": 0.5, "h2h_over_25": 0.5}
    return {
        "h2h_home_edge": (h2h.home_wins - h2h.away_wins) / total,
        "h2h_btts": h2h.btts_rate,
        "h2h_over_25": h2h.over_25_rate,
        "h2h_avg_goals": h2h.avg_goals,
    }


def home_advantage(league: LeagueProfile | None) -> float:
    return league.home_advantage_factor if league else 0.10
