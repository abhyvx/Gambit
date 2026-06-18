from __future__ import annotations

from bet_placer.models.types import Match, TacticalProfile


STYLE_MATCHUP_MATRIX = {
    ("high_press", "possession"): 0.08,
    ("high_press", "low_block"): 0.05,
    ("counter", "high_press"): 0.10,
    ("counter", "possession"): -0.03,
    ("possession", "low_block"): -0.05,
    ("low_block", "possession"): 0.06,
}


def tactical_advantage(home: TacticalProfile, away: TacticalProfile) -> float:
    """Stylistic matchup edge for home team (-0.15 to +0.15)."""
    key = (home.style, away.style)
    base = STYLE_MATCHUP_MATRIX.get(key, 0.0)
    press_diff = (home.press_intensity - away.press_intensity) / 20.0
    transition_diff = (home.transition_speed - away.transition_speed) / 20.0
    flexibility = (home.tactical_flexibility - away.tactical_flexibility) / 20.0
    return max(-0.15, min(0.15, base + press_diff * 0.3 + transition_diff * 0.2 + flexibility * 0.1))


def analyze_tactics(match: Match) -> dict[str, float]:
    adv = tactical_advantage(match.home_tactics, match.away_tactics)
    combined_possession = (match.home_tactics.avg_possession + match.away_tactics.avg_possession) / 2
    attacking_intent = (
        match.home_tactics.press_intensity
        + match.away_tactics.press_intensity
        + match.home_tactics.transition_speed
        + match.away_tactics.transition_speed
    ) / 40.0

    return {
        "tactical_advantage_home": adv,
        "combined_possession": combined_possession / 100.0,
        "attacking_intent": min(1.0, attacking_intent),
        "set_piece_edge_home": (match.home_tactics.set_piece_strength - match.away_tactics.set_piece_strength) / 10.0,
    }
