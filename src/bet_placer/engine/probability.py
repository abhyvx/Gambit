from __future__ import annotations

from bet_placer.engine.ev import find_value_bets
from bet_placer.intuition.analyst import AnalystIntuition
from bet_placer.ml.ensemble import EnsembleModel
from bet_placer.models.types import AnalysisResult, Match, ValueBet


class ProbabilityEngine:
    """Orchestrates ensemble models + intuition layer."""

    def __init__(self):
        self.ensemble = EnsembleModel()
        self.intuition = AnalystIntuition()

    def analyze_match(self, match: Match) -> AnalysisResult:
        # No book lines → price from the sport model so EV / slips / leans always have odds.
        if not (match.market_odds or []):
            from bet_placer.engine.all_markets import generate_sport_market_odds
            match.market_odds = generate_sport_market_odds(match)
        else:
            # Thin boards (moneyline only): merge in model markets we understand.
            from bet_placer.engine.all_markets import generate_sport_market_odds
            have = {(
                o.market.value if hasattr(o.market, "value") else str(o.market),
                o.selection,
                o.line,
            ) for o in match.market_odds}
            for o in generate_sport_market_odds(match):
                key = (
                    o.market.value if hasattr(o.market, "value") else str(o.market),
                    o.selection,
                    o.line,
                )
                if key not in have:
                    match.market_odds.append(o)
                    have.add(key)

        raw_probs = self.ensemble.predict_all(match)
        adjusted_probs = self.intuition.adjust_probabilities(match, raw_probs)
        factors = self.intuition.reasoning_factors(match)
        value_bets = find_value_bets(match, adjusted_probs, factors)

        for bet in value_bets:
            from bet_placer.explain.explainer import explain_bet
            bet.explanation = explain_bet(match, bet, adjusted_probs, factors)

        value_bets.sort(key=lambda b: b.rank_score, reverse=True)
        top_bets = value_bets[:10]

        return AnalysisResult(
            match=match,
            probabilities=adjusted_probs,
            value_bets=value_bets,
            top_bets=top_bets,
            metadata={"feature_count": len(match.market_odds)},
        )


def rank_all_bets(results: list[AnalysisResult], top_n: int = 10) -> list[ValueBet]:
    all_bets: list[ValueBet] = []
    for r in results:
        all_bets.extend(r.value_bets)
    all_bets.sort(key=lambda b: b.rank_score, reverse=True)
    return all_bets[:top_n]
