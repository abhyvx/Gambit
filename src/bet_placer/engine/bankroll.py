"""Bankroll management — protect users from losing money via oversizing."""

from __future__ import annotations

from dataclasses import dataclass

from bet_placer.config import get_settings


@dataclass
class StakeRecommendation:
    bankroll: float
    recommended_stake: float
    recommended_pct: float
    max_stake: float
    risk_level: str  # low | medium | high
    plain_english: str
    expected_profit: float
    expected_loss_if_wrong: float
    break_even_probability: float


def recommend_stake(
    true_prob: float,
    decimal_odds: float,
    confidence: float,
    risk_score: float,
    bankroll: float = 1000.0,
) -> StakeRecommendation:
    settings = get_settings()
    b = decimal_odds - 1.0
    q = 1.0 - true_prob
    raw_kelly = max(0.0, (true_prob * b - q) / b) if b > 0 else 0.0
    fractional = raw_kelly * settings.kelly_fraction

    # Hard caps to protect bankroll
    max_pct = settings.max_stake_pct / 100  # e.g. 3%
    if risk_score > 0.7:
        max_pct = min(max_pct, 0.01)  # 1% max on high risk
    elif risk_score > 0.5:
        max_pct = min(max_pct, 0.02)

    if confidence < 0.6:
        fractional *= 0.5

    recommended_pct = min(fractional, max_pct)
    recommended_stake = round(bankroll * recommended_pct, 2)
    max_stake = round(bankroll * max_pct, 2)

    ev = true_prob * decimal_odds - 1.0
    expected_profit = round(recommended_stake * ev, 2)
    expected_loss = round(recommended_stake, 2)
    break_even = 1.0 / decimal_odds

    if risk_score < 0.4 and confidence >= 0.7 and recommended_pct > 0:
        risk_level = "low"
    elif risk_score < 0.65:
        risk_level = "medium"
    else:
        risk_level = "high"

    plain = _plain_english(
        recommended_stake, bankroll, expected_profit, expected_loss,
        break_even, true_prob, decimal_odds, risk_level, recommended_pct,
    )

    return StakeRecommendation(
        bankroll=bankroll,
        recommended_stake=recommended_stake,
        recommended_pct=round(recommended_pct * 100, 2),
        max_stake=max_stake,
        risk_level=risk_level,
        plain_english=plain,
        expected_profit=expected_profit,
        expected_loss_if_wrong=expected_loss,
        break_even_probability=break_even,
    )


def recommend_match_stake(
    true_prob: float,
    decimal_odds: float,
    confidence: float,
    risk_score: float,
    match_budget_inr: float,
) -> StakeRecommendation:
    """Stake sizing when the user allocates a fixed budget to ONE match only."""
    settings = get_settings()
    b = decimal_odds - 1.0
    q = 1.0 - true_prob
    raw_kelly = max(0.0, (true_prob * b - q) / b) if b > 0 else 0.0
    fractional = raw_kelly * settings.kelly_fraction

    max_pct = settings.match_max_stake_pct / 100
    if risk_score > 0.7:
        max_pct = min(max_pct, 0.15)
    elif risk_score > 0.5:
        max_pct = min(max_pct, 0.25)
    if confidence < 0.6:
        fractional *= 0.6

    recommended_pct = min(fractional, max_pct)
    recommended_stake = round(match_budget_inr * recommended_pct, 2)
    max_stake = round(match_budget_inr * max_pct, 2)

    ev = true_prob * decimal_odds - 1.0
    expected_profit = round(recommended_stake * ev, 2)
    expected_loss = round(recommended_stake, 2)
    break_even = 1.0 / decimal_odds

    if risk_score < 0.4 and confidence >= 0.7 and recommended_pct > 0:
        risk_level = "low"
    elif risk_score < 0.65:
        risk_level = "medium"
    else:
        risk_level = "high"

    plain = _plain_english(
        recommended_stake, match_budget_inr, expected_profit, expected_loss,
        break_even, true_prob, decimal_odds, risk_level, recommended_pct,
    )

    return StakeRecommendation(
        bankroll=match_budget_inr,
        recommended_stake=recommended_stake,
        recommended_pct=round(recommended_pct * 100, 2),
        max_stake=max_stake,
        risk_level=risk_level,
        plain_english=plain,
        expected_profit=expected_profit,
        expected_loss_if_wrong=expected_loss,
        break_even_probability=break_even,
    )


def _plain_english(
    stake, bankroll, profit, loss, break_even, true_prob, odds, risk, pct,
) -> str:
    if stake <= 0:
        return (
            "Do not bet — edge is too small or risk is too high. "
            "Betting here is more likely to lose money long-term."
        )
    if risk == "high":
        return (
            f"If you bet ${stake:.0f} ({pct:.1f}% of your ${bankroll:.0f} bankroll), "
            f"you could win ${stake * (odds - 1):.0f} or lose ${loss:.0f}. "
            f"This is a HIGH RISK bet — models disagree or confidence is low. "
            f"Consider skipping or betting half this amount."
        )
    return (
        f"Bet ${stake:.0f} ({pct:.1f}% of bankroll). "
        f"If correct, profit ~${stake * (odds - 1):.0f}. If wrong, lose ${loss:.0f}. "
        f"Our model says {true_prob:.0%} chance vs {break_even:.0%} needed to break even. "
        f"Long-term expected profit on this bet: ~${profit:.2f}."
    )
