"""Convert between odds formats and compute implied probabilities."""

from __future__ import annotations


def decimal_to_implied(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        raise ValueError(f"Invalid decimal odds: {decimal_odds}")
    return 1.0 / decimal_odds


def american_to_decimal(american: float) -> float:
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def fractional_to_decimal(numerator: float, denominator: float) -> float:
    return 1.0 + numerator / denominator


def remove_vig_two_way(prob_a: float, prob_b: float) -> tuple[float, float]:
    total = prob_a + prob_b
    if total <= 0:
        return 0.5, 0.5
    return prob_a / total, prob_b / total


def remove_vig_three_way(home: float, draw: float, away: float) -> tuple[float, float, float]:
    total = home + draw + away
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return home / total, draw / total, away / total


def detect_steam_move(opening: float, current: float, threshold_pct: float = 0.03) -> bool:
    """Sharp money steam: odds shorten significantly on a selection."""
    if opening <= 0:
        return False
    change = (current - opening) / opening
    return change < -threshold_pct


def detect_reverse_line_movement(
    public_side_pct: float, opening: float, current: float
) -> bool:
    """Public on one side but line moves the other way."""
    public_heavy = public_side_pct > 0.65
    odds_shortened = current < opening
    return public_heavy and not odds_shortened and current > opening
