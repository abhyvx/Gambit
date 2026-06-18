from __future__ import annotations

from bet_placer.analysis.context import analyze_external, analyze_h2h, home_advantage
from bet_placer.analysis.form import analyze_form, xg_differential
from bet_placer.analysis.players import analyze_players
from bet_placer.analysis.tactical import analyze_tactics
from bet_placer.models.types import Match


def build_feature_vector(match: Match) -> dict[str, float]:
    """Aggregate all contextual features for ML models and intuition."""
    features: dict[str, float] = {}
    features.update(analyze_form(match))
    features.update(analyze_players(match))
    features.update(analyze_tactics(match))
    features.update(analyze_external(match))
    features.update(analyze_h2h(match.h2h))
    features["home_advantage"] = home_advantage(match.league_profile)
    features["xg_diff"] = xg_differential(match.home_stats, match.away_stats)
    features["league_avg_goals"] = match.league_profile.avg_goals_per_match if match.league_profile else 2.6
    features["morale_diff"] = (match.chemistry.morale_home - match.chemistry.morale_away) / 10.0
    features["momentum_diff"] = (match.chemistry.momentum_home - match.chemistry.momentum_away) / 10.0
    features["sentiment_diff"] = match.sentiment_score_home - match.sentiment_score_away
    if match.referee:
        features["referee_cards"] = match.referee.avg_cards_per_match / 6.0
        features["referee_penalties"] = match.referee.avg_penalties_per_match
        features["referee_home_bias"] = match.referee.home_bias
    return features
