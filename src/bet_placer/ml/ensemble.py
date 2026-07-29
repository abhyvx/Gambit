from __future__ import annotations

import numpy as np

from bet_placer.analysis.features import build_feature_vector
from bet_placer.config import get_settings
from bet_placer.ml.elo import EloModel
from bet_placer.ml.poisson import corners_prob, match_outcome_probs
from bet_placer.math.normalize import normalize_estimates
from bet_placer.models.enums import MarketType
from bet_placer.models.types import Match, ProbabilityEstimate


class GradientBoostingModel:
    """Feature-based GBM for match outcomes. Uses heuristics until trained on historical data."""

    def predict(self, match: Match, features: dict[str, float]) -> dict[str, float]:
        base = 0.33
        home_edge = (
            features.get("form_differential", 0) * 0.15
            + features.get("xg_diff", 0) * 0.08
            + features.get("tactical_advantage_home", 0)
            + features.get("home_advantage", 0.10)
            - features.get("away_injury_impact", 0) * 0.08
            + features.get("home_injury_impact", 0) * -0.05
            + features.get("morale_diff", 0) * 0.05
        )
        home = base + home_edge
        away = base - home_edge * 0.7
        draw = 1 - home - away
        home, draw, away = _normalize_three(home, draw, away)
        attacking = features.get("attacking_intent", 0.5) + features.get("league_avg_goals", 2.6) / 5.0
        over = min(0.85, 0.45 + attacking * 0.15 + features.get("weather_attack_boost", 0))
        btts = min(0.85, 0.50 + features.get("h2h_btts", 0.5) * 0.2)
        return {
            "home": home,
            "draw": draw,
            "away": away,
            "over_2.5": over,
            "under_2.5": 1 - over,
            "btts_yes": btts,
            "btts_no": 1 - btts,
        }


class EnsembleModel:
    """Weighted ensemble of Poisson, ELO, and GBM heuristic."""

    def __init__(self):
        self.settings = get_settings()
        self.elo = EloModel()
        self.gbm = GradientBoostingModel()
        self._trained_ml: dict | None = None

    def predict_all(self, match: Match) -> list[ProbabilityEstimate]:
        from bet_placer.ml.elo import _sport_from_match

        sport = _sport_from_match(match)
        # Basketball / cricket: Elo + totals/handicap — not soccer Poisson goals.
        if sport in ("basketball", "cricket"):
            from bet_placer.engine.all_markets import predict_all_markets
            return normalize_estimates(predict_all_markets(match))

        features = build_feature_vector(match)
        poisson = match_outcome_probs(match)
        elo = self.elo.predict(match)
        gbm = self.gbm.predict(match, features)

        w = self.settings
        weights = {
            "poisson": w.ensemble_weight_poisson,
            "elo": w.ensemble_weight_elo,
            "gbm": w.ensemble_weight_gbm,
        }
        total_w = sum(weights.values())
        weights = {k: v / total_w for k, v in weights.items()}

        estimates: list[ProbabilityEstimate] = []

        for sel, key in [("home", "home"), ("draw", "draw"), ("away", "away")]:
            prob = (
                weights["poisson"] * poisson[key]
                + weights["elo"] * elo[key]
                + weights["gbm"] * gbm[key]
            )
            estimates.append(
                ProbabilityEstimate(
                    market=MarketType.MATCH_WINNER,
                    selection=sel,
                    line=None,
                    probability=prob,
                    model_contributions={
                        "poisson": poisson[key],
                        "elo": elo[key],
                        "gbm": gbm[key],
                    },
                    confidence=_model_agreement(poisson[key], elo[key], gbm[key]),
                )
            )

        for sel, key in [("over", "over_2.5"), ("under", "under_2.5")]:
            prob = weights["poisson"] * poisson[key] + weights["gbm"] * gbm[key]
            estimates.append(
                ProbabilityEstimate(
                    market=MarketType.OVER_UNDER_GOALS,
                    selection=sel,
                    line=2.5,
                    probability=prob,
                    model_contributions={"poisson": poisson[key], "gbm": gbm[key]},
                    confidence=_model_agreement(poisson[key], gbm[key]),
                )
            )

        for sel, key in [("yes", "btts_yes"), ("no", "btts_no")]:
            prob = weights["poisson"] * poisson[key] + weights["gbm"] * gbm[key]
            estimates.append(
                ProbabilityEstimate(
                    market=MarketType.BTTS,
                    selection=sel,
                    line=None,
                    probability=prob,
                    model_contributions={"poisson": poisson[key], "gbm": gbm[key]},
                    confidence=_model_agreement(poisson[key], gbm[key]),
                )
            )

        cp = corners_prob(match, line=9.5)
        for sel in ("over", "under"):
            estimates.append(
                ProbabilityEstimate(
                    market=MarketType.CORNERS,
                    selection=sel,
                    line=9.5,
                    probability=cp[sel],
                    model_contributions={"poisson_corners": cp[sel]},
                    confidence=0.6,
                )
            )

        return normalize_estimates(estimates)


def _normalize_three(h: float, d: float, a: float) -> tuple[float, float, float]:
    h, d, a = max(0.05, h), max(0.15, d), max(0.05, a)
    t = h + d + a
    return h / t, d / t, a / t


def _model_agreement(*probs: float) -> float:
    """Higher when models agree (lower variance)."""
    if len(probs) < 2:
        return 0.5
    std = float(np.std(probs))
    return max(0.4, min(0.95, 1.0 - std * 3))
