"""Probability normalization — ensures coherent math across markets."""

from __future__ import annotations

from bet_placer.models.enums import MarketType
from bet_placer.models.types import ProbabilityEstimate


def normalize_estimates(estimates: list[ProbabilityEstimate]) -> list[ProbabilityEstimate]:
    """Renormalize 1X2 and all two-way market pairs to sum to 1."""
    result = list(estimates)
    result = _renorm_group(result, MarketType.MATCH_WINNER, 3)
    for market in (MarketType.OVER_UNDER_GOALS, MarketType.BTTS, MarketType.CORNERS, MarketType.CARDS):
        result = _renorm_group(result, market, 2, line_specific=True)
    return result


def _renorm_group(
    estimates: list[ProbabilityEstimate],
    market: MarketType,
    expected: int,
    line_specific: bool = False,
) -> list[ProbabilityEstimate]:
    if line_specific:
        lines = {e.line for e in estimates if e.market == market}
        for line in lines:
            estimates = _renorm_subset(estimates, market, expected, line)
        return estimates
    return _renorm_subset(estimates, market, expected, None)


def _renorm_subset(
    estimates: list[ProbabilityEstimate],
    market: MarketType,
    expected: int,
    line: float | None,
) -> list[ProbabilityEstimate]:
    subset = [
        e for e in estimates
        if e.market == market and (line is None or e.line == line)
    ]
    if len(subset) != expected:
        return estimates
    total = sum(e.probability for e in subset)
    if total <= 0:
        return estimates
    out = []
    for e in estimates:
        if e.market == market and (line is None or e.line == line):
            out.append(ProbabilityEstimate(
                market=e.market,
                selection=e.selection,
                line=e.line,
                probability=e.probability / total,
                model_contributions=e.model_contributions,
                intuition_adjustment=e.intuition_adjustment,
                confidence=e.confidence,
            ))
        else:
            out.append(e)
    return out
