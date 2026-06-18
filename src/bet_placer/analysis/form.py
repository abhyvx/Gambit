from __future__ import annotations

from bet_placer.models.types import Match, TeamStats


def form_score(results: list[str], weights: list[float] | None = None) -> float:
    """Convert W/D/L sequence to 0-1 score with recency weighting."""
    if not results:
        return 0.5
    points = {"W": 1.0, "D": 0.4, "L": 0.0}
    if weights is None:
        n = len(results)
        weights = [(i + 1) / n for i in range(n)]
    total_w = sum(weights[: len(results)])
    if total_w == 0:
        return 0.5
    score = sum(points.get(r, 0.4) * w for r, w in zip(results, weights))
    return score / total_w


def analyze_form(match: Match) -> dict[str, float]:
    """Weighted form across 5/10/20 game windows."""
    home = match.home_stats
    away = match.away_stats

    h5 = form_score(home.form_last_5)
    h10 = form_score(home.form_last_10) if home.form_last_10 else h5
    h20 = form_score(home.form_last_20) if home.form_last_20 else h10

    a5 = form_score(away.form_last_5)
    a10 = form_score(away.form_last_10) if away.form_last_10 else a5
    a20 = form_score(away.form_last_20) if away.form_last_20 else a10

    home_composite = 0.5 * h5 + 0.3 * h10 + 0.2 * h20
    away_composite = 0.5 * a5 + 0.3 * a10 + 0.2 * a20

    home_trend = h5 - h20  # positive = improving
    away_trend = a5 - a20

    return {
        "home_form": home_composite,
        "away_form": away_composite,
        "home_trend": home_trend,
        "away_trend": away_trend,
        "form_differential": home_composite - away_composite,
    }


def xg_differential(stats_home: TeamStats, stats_away: TeamStats) -> float:
    """Net xG advantage for home team."""
    home_attack = stats_home.xg or stats_home.goals_scored
    home_defense = stats_home.xga or stats_home.goals_conceded
    away_attack = stats_away.xg or stats_away.goals_scored
    away_defense = stats_away.xga or stats_away.goals_conceded
    home_expected = (home_attack + away_defense) / 2
    away_expected = (away_attack + home_defense) / 2
    return home_expected - away_expected
