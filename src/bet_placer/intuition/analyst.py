from __future__ import annotations

from bet_placer.analysis.features import build_feature_vector
from bet_placer.config import get_settings
from bet_placer.models.enums import MarketType
from bet_placer.models.types import Match, ProbabilityEstimate


class AnalystIntuition:
    """
    Simulates experienced analyst reasoning to adjust model probabilities.
    Answers: unlucky recently? morale? stylistic edge? public inefficiency?
    """

    def __init__(self):
        self.settings = get_settings()

    def score_match(self, match: Match) -> dict[str, float]:
        features = build_feature_vector(match)
        signals: dict[str, float] = {}

        # Form vs xG: unlucky or lucky?
        home_underperformance = features.get("home_form", 0.5) - (match.home_stats.xg / 3.0)
        away_underperformance = features.get("away_form", 0.5) - (match.away_stats.xg / 3.0)
        signals["home_unlucky_boost"] = max(0, -home_underperformance * 0.05)
        signals["away_unlucky_boost"] = max(0, -away_underperformance * 0.05)

        # Morale and momentum
        signals["morale_edge"] = features.get("morale_diff", 0) * 0.04
        signals["momentum_edge"] = features.get("momentum_diff", 0) * 0.03

        # Stylistic matchup
        signals["tactical_edge"] = features.get("tactical_advantage_home", 0)

        # Injury narrative
        signals["injury_narrative_home"] = -features.get("home_injury_impact", 0) * 0.06
        signals["injury_narrative_away"] = -features.get("away_injury_impact", 0) * 0.06

        # Motivation from context
        signals["motivation_home"] = features.get("motivation_home", 0)
        signals["motivation_away"] = features.get("motivation_away", 0)

        # Sentiment divergence from market
        signals["sentiment_home"] = match.sentiment_score_home * 0.03
        signals["sentiment_away"] = match.sentiment_score_away * 0.03

        # Chemistry notes qualitative boost
        if any("unbeaten" in n.lower() for n in match.chemistry.notes):
            signals["home_hype"] = 0.02
        else:
            signals["home_hype"] = 0.0

        if any("missing" in n.lower() or "ruled out" in n.lower() for n in match.chemistry.notes):
            signals["away_weakness"] = 0.03
        else:
            signals["away_weakness"] = 0.0

        # Manager tenure / new coach bounce
        if match.home_tactics.manager_tenure_matches < 10:
            signals["new_manager_home"] = 0.04
        else:
            signals["new_manager_home"] = 0.0

        return signals

    def adjust_probabilities(
        self, match: Match, estimates: list[ProbabilityEstimate]
    ) -> list[ProbabilityEstimate]:
        signals = self.score_match(match)
        cap = self.settings.intuition_max_adjustment

        home_adj = (
            signals.get("home_unlucky_boost", 0)
            + signals.get("morale_edge", 0)
            + signals.get("momentum_edge", 0)
            + signals.get("tactical_edge", 0)
            + signals.get("injury_narrative_home", 0)
            + signals.get("motivation_home", 0)
            + signals.get("sentiment_home", 0)
            + signals.get("home_hype", 0)
            + signals.get("new_manager_home", 0)
            - signals.get("away_weakness", 0)
        )
        home_adj = max(-cap, min(cap, home_adj))

        attacking_boost = (
            signals.get("motivation_home", 0)
            + signals.get("motivation_away", 0)
            + match.chemistry.momentum_home / 100
            + match.chemistry.momentum_away / 100
        )
        attacking_boost = max(-cap / 2, min(cap / 2, attacking_boost))

        adjusted: list[ProbabilityEstimate] = []
        for est in estimates:
            prob = est.probability
            adj = 0.0

            if est.market == MarketType.MATCH_WINNER:
                if est.selection == "home":
                    adj = home_adj
                elif est.selection == "away":
                    adj = -home_adj * 0.8
                elif est.selection == "draw":
                    adj = -abs(home_adj) * 0.3

            elif est.market == MarketType.OVER_UNDER_GOALS:
                if est.selection == "over":
                    adj = attacking_boost
                else:
                    adj = -attacking_boost

            elif est.market == MarketType.BTTS:
                if est.selection == "yes":
                    adj = attacking_boost * 0.8
                else:
                    adj = -attacking_boost * 0.8

            new_prob = max(0.02, min(0.98, prob + adj))
            adjusted.append(
                ProbabilityEstimate(
                    market=est.market,
                    selection=est.selection,
                    line=est.line,
                    probability=new_prob,
                    model_contributions=est.model_contributions,
                    intuition_adjustment=adj,
                    confidence=min(0.95, est.confidence + abs(adj) * 0.5),
                )
            )

        return self._renormalize_pairs(
            self._renormalize_match_winner(adjusted),
            MarketType.OVER_UNDER_GOALS,
            MarketType.BTTS,
        )

    def _renormalize_pairs(
        self,
        estimates: list[ProbabilityEstimate],
        *markets: MarketType,
    ) -> list[ProbabilityEstimate]:
        result = list(estimates)
        for market in markets:
            pair = [e for e in result if e.market == market]
            if len(pair) != 2:
                continue
            total = sum(e.probability for e in pair)
            if total <= 0:
                continue
            for i, e in enumerate(result):
                if e.market == market:
                    idx = pair.index(e)
                    result[i] = ProbabilityEstimate(
                        market=e.market,
                        selection=e.selection,
                        line=e.line,
                        probability=pair[idx].probability / total,
                        model_contributions=e.model_contributions,
                        intuition_adjustment=e.intuition_adjustment,
                        confidence=e.confidence,
                    )
        return result

    def reasoning_factors(self, match: Match) -> list[str]:
        """Human-readable intuition factors for explainability."""
        signals = self.score_match(match)
        factors = []

        if signals.get("home_unlucky_boost", 0) > 0.01:
            factors.append("Home side may be undervalued — results worse than underlying xG suggests")
        if signals.get("tactical_edge", 0) > 0.03:
            factors.append("Stylistic matchup favors the home team's pressing approach")
        if signals.get("tactical_edge", 0) < -0.03:
            factors.append("Away team's style may counter the home setup effectively")
        if match.chemistry.morale_home > 7.5:
            factors.append("Strong locker room morale reported for home team")
        if match.chemistry.media_pressure_away > 7:
            factors.append("Elevated media pressure on away side could affect performance")
        for note in match.chemistry.notes:
            factors.append(note)
        if match.external.weather in ("rain", "light_rain"):
            factors.append("Wet conditions historically increase goal variance and attacking errors")
        if match.context.value != "normal":
            factors.append(f"Match context: {match.context.value.replace('_', ' ')}")

        return factors

    def _renormalize_match_winner(
        self, estimates: list[ProbabilityEstimate]
    ) -> list[ProbabilityEstimate]:
        mw = [e for e in estimates if e.market == MarketType.MATCH_WINNER]
        if len(mw) != 3:
            return estimates
        total = sum(e.probability for e in mw)
        if total <= 0:
            return estimates
        result = []
        for e in estimates:
            if e.market == MarketType.MATCH_WINNER:
                result.append(
                    ProbabilityEstimate(
                        market=e.market,
                        selection=e.selection,
                        line=e.line,
                        probability=e.probability / total,
                        model_contributions=e.model_contributions,
                        intuition_adjustment=e.intuition_adjustment,
                        confidence=e.confidence,
                    )
                )
            else:
                result.append(e)
        return result
