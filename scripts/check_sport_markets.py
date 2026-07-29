#!/usr/bin/env python3
"""Self-check: sport-aware markets + softer skip + tab diversify."""
from __future__ import annotations

from types import SimpleNamespace

from bet_placer.engine.all_markets import _predict_two_way_markets
from bet_placer.engine.bet_portfolio import _diversify_tab_plans, _plan_market_families, _should_skip_match


def main() -> None:
    bb = SimpleNamespace(
        id="basketball_nba_1", home_team="Lakers", away_team="Celtics",
        league="NBA", market_odds=[],
    )
    est = _predict_two_way_markets(bb, "basketball")
    mkts = {getattr(e.market, "value", e.market) for e in est}
    assert "match_winner" in mkts and "btts" not in mkts
    assert any((e.line or 0) >= 200 for e in est), [e.line for e in est[:6]]

    cr = SimpleNamespace(
        id="cricket_ipl_1", home_team="MI", away_team="CSK",
        league="IPL T20", market_odds=[],
    )
    est2 = _predict_two_way_markets(cr, "cricket")
    assert any((e.line or 0) >= 140 for e in est2)

    plans = {
        "match_card": [{"legs": [{"market": "match_winner", "label": "H"}], "tab_id": "match_card"}],
        "min_loss": [{"legs": [{"market": "match_winner", "label": "H"}], "tab_id": "min_loss"}],
        "singles_focus": [{"legs": [{"market": "over_under_goals", "line": 220.5, "label": "O"}], "tab_id": "singles_focus"}],
        "value": [{"legs": [{"market": "asian_handicap", "line": -3.5, "label": "AH"}], "tab_id": "value"}],
        "smart_parlay": [{
            "legs": [{"market": "match_winner", "label": "H"}, {"market": "over_under_goals", "label": "O"}],
            "tab_id": "smart_parlay",
        }],
    }
    div = _diversify_tab_plans(plans, "H", "A")
    assert len(div["smart_parlay"][0]["legs"]) >= 2
    assert _plan_market_families(div["value"][0]) == frozenset({"handicap"})

    assert _should_skip_match({k: [] for k in plans}) is True
    print("ok")


if __name__ == "__main__":
    main()
