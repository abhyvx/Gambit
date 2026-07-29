#!/usr/bin/env python3
"""BB/cricket must price boards + return non-SKIP recs with slip legs."""
from __future__ import annotations

from types import SimpleNamespace

from bet_placer.data.providers import EventSummary, _backfill_model_h2h
from bet_placer.engine.all_markets import generate_sport_market_odds, predict_all_markets
from bet_placer.engine.probability import ProbabilityEngine
from bet_placer.engine.verdict import MatchVerdictEngine
from bet_placer.models.types import AnalysisResult


def main() -> None:
    # Board backfill
    rows = [
        EventSummary(
            id="1", home_team="Lakers", away_team="Celtics", league="NBA",
            sport_key="basketball_nba", kickoff=None, source="espn",
        ),
        EventSummary(
            id="2", home_team="MI", away_team="CSK", league="IPL T20",
            sport_key="cricket_ipl", kickoff=None, source="espn",
        ),
    ]
    _backfill_model_h2h(rows)
    assert rows[0].home_odds and rows[0].away_odds, rows[0]
    assert rows[1].home_odds and rows[1].away_odds, rows[1]
    assert rows[0].draw_odds is None

    # Sport markets + odds
    m = SimpleNamespace(
        id="basketball_nba_x", home_team="Lakers", away_team="Celtics",
        league="NBA", market_odds=[],
    )
    # probability engine needs a real Match-like; use generate + predict only
    odds = generate_sport_market_odds(m)
    assert len(odds) >= 4
    probs = predict_all_markets(m)
    assert any(getattr(p.market, "value", p.market) == "match_winner" for p in probs)

    # Verdict must not hard-SKIP when probs exist but value_bets empty
    engine = MatchVerdictEngine()
    empty = AnalysisResult(
        match=m,  # type: ignore[arg-type]
        probabilities=probs,
        value_bets=[],
        top_bets=[],
        metadata={},
    )
    v = engine.evaluate(empty, None, None, stake_markets_scanned=len(odds))
    assert v.verdict.value != "skip", v.headline
    print("ok", rows[0].home_odds, rows[0].away_odds, v.verdict.value, v.headline)


if __name__ == "__main__":
    main()
