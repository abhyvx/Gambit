from __future__ import annotations

from bet_placer.models.types import Match, PlayerStatus


def injury_impact(players: list[PlayerStatus]) -> float:
    """0 = no impact, 1 = severe impact from missing key players."""
    if not players:
        return 0.0
    key = [p for p in players if p.is_key_player]
    if not key:
        return 0.0
    missing = sum(1 for p in key if p.injured or p.suspended)
    return min(1.0, missing / max(len(key), 1) * 1.2)


def squad_depth_score(players: list[PlayerStatus]) -> float:
    """Estimate backup quality when starters are out."""
    available = [p for p in players if not p.injured and not p.suspended]
    if not available:
        return 0.3
    avg_form = sum(p.form_rating for p in available) / len(available)
    return min(1.0, avg_form / 10.0)


def analyze_players(match: Match) -> dict[str, float]:
    return {
        "home_injury_impact": injury_impact(match.home_players),
        "away_injury_impact": injury_impact(match.away_players),
        "home_depth": squad_depth_score(match.home_players),
        "away_depth": squad_depth_score(match.away_players),
        "home_key_available": 1.0 - injury_impact(match.home_players),
        "away_key_available": 1.0 - injury_impact(match.away_players),
    }
