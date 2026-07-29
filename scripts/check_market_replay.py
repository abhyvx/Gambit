#!/usr/bin/env python3
"""Self-check: multi-market replay picks several bets and grades them."""
from __future__ import annotations

from bet_placer.ml.market_replay import _pick_bets, apply_market_replay, replay_multi_markets


def main() -> None:
    # Unit: picker keeps multiple market groups, not just 1X2
    events = [
        ("result", "home", 0.48),
        ("result", "draw", 0.28),
        ("result", "away", 0.24),
        ("btts", "yes", 0.61),
        ("btts", "no", 0.39),
        ("totals", "over_2.5", 0.57),
        ("totals", "under_2.5", 0.43),
    ]
    picks = _pick_bets(events)
    groups = {g for g, _, _ in picks}
    assert len(picks) >= 2, picks
    assert "result" in groups and ("btts" in groups or "totals" in groups), picks

    # Soft apply never drops params
    params = apply_market_replay(
        {"calibration": {"result": {"a": 1.0, "b": 0.0}}},
        {"accuracy_by_market": {"result": 0.62}, "n_matches": 1, "n_bets": 3, "accuracy": 0.62,
         "by_market": {}, "avg_bets_per_match": 3, "rules": "test", "sample_matches": []},
    )
    assert "market_replay" in params
    assert params["calibration"]["result"]["a"] != 1.0

    # Live replay (may be empty if no finished WC fixtures offline)
    rep = replay_multi_markets(verbose=True)
    assert "n_bets" in rep and "by_market" in rep
    if rep["n_bets"]:
        assert rep["avg_bets_per_match"] >= 1
        assert set(rep["by_market"]) >= {"result"}
    print("ok", rep.get("n_matches"), "matches", rep.get("n_bets"), "bets", rep.get("accuracy"))


if __name__ == "__main__":
    main()
