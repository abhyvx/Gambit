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


def allocate_match_budget(
    picks: list[dict],
    match_budget_inr: float,
    *,
    spend_pct: float | None = None,
    style: object | None = None,
) -> list[dict]:
    """Split one match budget across picks. Never assign the full budget to each row.

    Returns the same pick dicts with stake_recommendation.recommended_stake filled so
    the stakes sum to roughly spend_pct * budget (rounded to ₹10).
    """
    if not picks:
        return picks
    if spend_pct is None:
        if style is not None:
            from bet_placer.engine.bettor_style import spend_pct_for_style
            spend_pct = spend_pct_for_style(style)
        else:
            spend_pct = 0.85
    budget = max(50.0, float(match_budget_inr or 200))
    pool = max(20.0, budget * float(spend_pct))
    # Style risk: shrink or stretch weights (shared once — all callers benefit)
    risk_mult = 1.0
    goal = None
    if style is not None:
        from bet_placer.engine.bettor_style import BettorStyle
        st = style if isinstance(style, BettorStyle) else BettorStyle.from_dict(style)  # type: ignore[arg-type]
        goal = st.goal
        if st.risk == "low":
            risk_mult = 0.85
        elif st.risk == "high":
            risk_mult = 1.1
    weights: list[float] = []
    for p in picks:
        prob = float(p.get("true_probability") or p.get("our_probability") or 0.45)
        w = max(0.05, prob) * risk_mult
        if p.get("is_lean"):
            w *= 0.55
        ev = float(p.get("expected_value") or 0)
        if ev > 0:
            w *= 1.0 + min(ev, 0.2) * 2
        if goal == "hit_target":
            odds = float(p.get("decimal_odds") or p.get("odds") or 1)
            if 1.4 <= odds <= 6.0:
                w *= 1.15
        elif goal == "preserve":
            w *= max(0.5, prob)
        weights.append(w)
    total_w = sum(weights) or 1.0
    remaining = pool
    out: list[dict] = []
    for i, p in enumerate(picks):
        raw = pool * (weights[i] / total_w)
        # last pick takes leftover so we don't overshoot
        if i == len(picks) - 1:
            stake = remaining
        else:
            stake = min(remaining, round(raw / 10) * 10)
            stake = max(10.0, stake)
        stake = min(remaining, max(10.0, round(stake / 10) * 10))
        remaining = max(0.0, remaining - stake)
        rec = dict(p.get("stake_recommendation") or {})
        rec["recommended_stake"] = stake
        rec["recommended_pct"] = round(100.0 * stake / budget, 1)
        rec["match_budget_inr"] = budget
        rec["plain_english"] = (
            f"₹{stake:.0f} of your ₹{budget:.0f} match budget"
            + (" (lean — keep it small)." if p.get("is_lean") else ".")
        )
        out.append({**p, "stake_recommendation": rec, "stake_inr": stake})
    return out


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
            f"If you bet ₹{stake:.0f} ({pct:.1f}% of your ₹{bankroll:.0f} budget), "
            f"you could win ₹{stake * (odds - 1):.0f} or lose ₹{loss:.0f}. "
            f"High risk — models disagree or confidence is low. "
            f"Consider skipping or betting half."
        )
    return (
        f"Bet ₹{stake:.0f} ({pct:.1f}% of budget). "
        f"If correct, profit ~₹{stake * (odds - 1):.0f}. If wrong, lose ₹{loss:.0f}. "
        f"Model chance {true_prob:.0%} vs {break_even:.0%} break-even."
    )


# ponytail: fails if allocation ever spends more than the match budget
if __name__ == "__main__":
    from bet_placer.engine.bettor_style import BettorStyle

    demo = allocate_match_budget(
        [
            {"true_probability": 0.6, "label": "A"},
            {"true_probability": 0.55, "is_lean": True, "label": "B"},
            {"true_probability": 0.5, "label": "C"},
        ],
        200,
    )
    total = sum(p["stake_inr"] for p in demo)
    assert total <= 200 + 1e-6, total
    assert all(p["stake_inr"] > 0 for p in demo)

    preserve = allocate_match_budget(
        [{"true_probability": 0.6, "label": "A", "decimal_odds": 1.8}],
        200,
        style=BettorStyle(goal="preserve", risk="low", structure="singles"),
    )
    hit = allocate_match_budget(
        [{"true_probability": 0.55, "label": "A", "decimal_odds": 2.2}],
        200,
        style=BettorStyle(goal="hit_target", risk="medium", structure="spread"),
    )
    assert preserve[0]["stake_inr"] < hit[0]["stake_inr"], (preserve[0]["stake_inr"], hit[0]["stake_inr"])
    print("ok", [p["stake_inr"] for p in demo], "sum", total, "preserve", preserve[0]["stake_inr"], "hit", hit[0]["stake_inr"])
