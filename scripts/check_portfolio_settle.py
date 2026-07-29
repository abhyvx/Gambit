#!/usr/bin/env python3
"""Assert portfolio auto-settle grades a finished 1X2 single correctly."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from bet_placer.ml.rec_grading import grade_leg
    from bet_placer.portfolio.store import _grade_portfolio_leg, _parse_fixture_sides

    assert _parse_fixture_sides("Arsenal vs Chelsea") == ("Arsenal", "Chelsea")
    row = {"home": "Arsenal", "away": "Chelsea", "hs": 2, "aws": 1}
    hit = grade_leg(
        {"market": "match_winner", "selection": "home", "label": "Arsenal to win"},
        home="Arsenal",
        away="Chelsea",
        hs=2,
        aws=1,
    )
    assert hit is True, hit
    miss = grade_leg(
        {"market": "match_winner", "selection": "away", "label": "Chelsea to win"},
        home="Arsenal",
        away="Chelsea",
        hs=2,
        aws=1,
    )
    assert miss is False, miss
    assert _grade_portfolio_leg(
        {"market": "match_winner", "raw_selection": "home", "selection": "Arsenal to win"},
        row,
    ) is True
    print("ok portfolio settle grade")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
