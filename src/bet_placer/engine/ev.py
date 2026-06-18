from __future__ import annotations

from bet_placer.config import get_settings
from bet_placer.markets.odds import decimal_to_implied, remove_vig_two_way, remove_vig_three_way
from bet_placer.models.enums import MarketType
from bet_placer.models.types import MarketOdds, Match, ProbabilityEstimate, ValueBet


def compute_ev(true_prob: float, decimal_odds: float) -> float:
    """EV = (true_prob * odds) - 1"""
    return true_prob * decimal_odds - 1.0


def compute_roi(true_prob: float, decimal_odds: float) -> float:
    return compute_ev(true_prob, decimal_odds)


def kelly_criterion(true_prob: float, decimal_odds: float, fraction: float = 0.25) -> float:
    """Fractional Kelly stake as percentage of bankroll."""
    if decimal_odds <= 1.0:
        return 0.0
    b = decimal_odds - 1.0
    q = 1.0 - true_prob
    kelly = (true_prob * b - q) / b
    return max(0.0, kelly * fraction)


def risk_score(true_prob: float, confidence: float, variance: float) -> float:
    """0 = low risk, 1 = high risk."""
    edge_uncertainty = 1.0 - confidence
    return min(1.0, edge_uncertainty * 0.6 + variance * 0.4)


def find_value_bets(
    match: Match,
    probabilities: list[ProbabilityEstimate],
    factors: list[str],
) -> list[ValueBet]:
    settings = get_settings()
    value_bets: list[ValueBet] = []

    for prob_est in probabilities:
        market_odds = _find_matching_odds(match.market_odds, prob_est)
        if not market_odds:
            continue

        # Fair implied probability (vig removed when possible)
        implied = _fair_implied(match.market_odds, prob_est)
        raw_true = prob_est.probability

        # Discipline (same as the Build-slip engine): a sharp book is never off
        # by 25%+ — when our model disagrees that much, it's OUR error, not value.
        # Skip it instead of surfacing a phantom +EV. Otherwise blend our estimate
        # toward the de-vigged price so edges are real, not model noise.
        if implied is not None and 0.0 < implied < 1.0:
            if abs(raw_true - implied) > 0.25:
                continue
            true_prob = 0.62 * raw_true + 0.38 * implied
        else:
            true_prob = raw_true

        ev = compute_ev(true_prob, market_odds.best_odds)
        roi = compute_roi(true_prob, market_odds.best_odds)

        if ev < settings.min_ev_threshold:
            continue
        # A genuine edge in a liquid market is rarely >25%. Anything above that is
        # a miscalibration artefact — never recommend it.
        if ev > 0.25:
            continue
        if prob_est.confidence < settings.min_confidence:
            continue

        variance = _estimate_variance(prob_est)
        risk = risk_score(true_prob, prob_est.confidence, variance)
        kelly = min(
            kelly_criterion(true_prob, market_odds.best_odds, settings.kelly_fraction),
            settings.max_stake_pct / 100,
        )

        rank_score = _rank_score(roi, ev, prob_est.confidence, risk, market_odds)

        value_bets.append(
            ValueBet(
                match_id=match.id,
                match_label=f"{match.home_team} vs {match.away_team}",
                market=prob_est.market,
                selection=prob_est.selection,
                line=prob_est.line,
                decimal_odds=market_odds.best_odds,
                implied_probability=implied,
                true_probability=true_prob,
                expected_value=ev,
                expected_roi=roi,
                kelly_stake_pct=kelly * 100,
                confidence=prob_est.confidence,
                risk_score=risk,
                variance=variance,
                rank_score=rank_score,
                explanation="",  # filled by explainer
                factors=list(factors),
                kickoff=match.kickoff,
            )
        )

    return value_bets


def _fair_implied(odds_list: list[MarketOdds], prob_est: ProbabilityEstimate) -> float:
    """Vig-free implied probability for the same market group."""
    siblings = [
        o for o in odds_list
        if o.market == prob_est.market
        and (prob_est.line is None or o.line == prob_est.line)
    ]
    if prob_est.market == MarketType.MATCH_WINNER and len(siblings) >= 2:
        by_sel = {o.selection: decimal_to_implied(o.best_odds) for o in siblings}
        if len(by_sel) == 3:
            h = by_sel.get("home", 0.33)
            d = by_sel.get("draw", 0.33)
            a = by_sel.get("away", 0.33)
            h, d, a = remove_vig_three_way(h, d, a)
            fair = {"home": h, "draw": d, "away": a}
            return fair.get(prob_est.selection, decimal_to_implied(
                next(o.best_odds for o in siblings if o.selection == prob_est.selection)
            ))
        if len(by_sel) == 2:
            sels = list(by_sel.keys())
            p1, p2 = remove_vig_two_way(by_sel[sels[0]], by_sel[sels[1]])
            fair = {sels[0]: p1, sels[1]: p2}
            return fair.get(prob_est.selection, p1)
    return decimal_to_implied(
        next(o.best_odds for o in siblings if o.selection == prob_est.selection)
    )


def _find_matching_odds(
    odds_list: list[MarketOdds], prob: ProbabilityEstimate
) -> MarketOdds | None:
    for o in odds_list:
        if o.market != prob.market:
            continue
        if o.selection != prob.selection:
            continue
        if prob.line is not None and o.line is not None:
            if abs(o.line - prob.line) > 0.01:
                continue
        return o
    return None


def _estimate_variance(prob_est: ProbabilityEstimate) -> float:
    contribs = list(prob_est.model_contributions.values())
    if len(contribs) < 2:
        return 0.3
    import numpy as np
    return float(np.std(contribs))


def _rank_score(
    roi: float, ev: float, confidence: float, risk: float, odds: MarketOdds
) -> float:
    liquidity = min(1.0, odds.bookmaker_count / 10.0)
    efficiency_penalty = 0.0
    if odds.steam_move:
        efficiency_penalty -= 0.05  # steam can mean sharp money already took value
    if odds.reverse_line_movement:
        efficiency_penalty += 0.08  # RLM often signals hidden edge

    return (
        roi * 0.35
        + ev * 0.30
        + confidence * 0.20
        + liquidity * 0.10
        - risk * 0.15
        + efficiency_penalty
    )
