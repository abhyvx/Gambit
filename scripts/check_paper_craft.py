#!/usr/bin/env python3
"""Self-check: gem spotting + paper book on ESPN boards (not World Cup)."""
from __future__ import annotations

from bet_placer.ml.gem_craft import spot_gems_from_events, spot_match_gems, update_craft_weights_from_tickets
from bet_placer.ml.paper_book import (
    _empty_book,
    apply_paper_learning,
    run_paper_walkforward,
    summarize,
)


def main() -> None:
    gems = spot_match_gems(
        unified={
            "spotlight": {
                "market": "btts", "selection": "yes", "our_probability": 0.62,
                "odds": 1.85, "edge_pct": 8,
            },
        },
        slip_data={},
        flat=[{
            "market": "over_under_goals", "selection": "over", "line": 2.5,
            "our_probability": 0.59, "odds": 1.95, "edge_pct": 6,
        }],
        craft_weights={},
    )
    assert gems
    fast = spot_gems_from_events([
        ("result", "home", 0.48),
        ("btts", "yes", 0.61),
        ("totals", "over_2.5", 0.57),
    ], craft_weights={})
    assert len(fast) >= 2
    weights = update_craft_weights_from_tickets([
        {"status": "won", "gem_kind": "niche", "market": "btts"},
        {"status": "won", "gem_kind": "niche", "market": "btts"},
        {"status": "lost", "gem_kind": "single", "market": "match_winner"},
        {"status": "lost", "gem_kind": "single", "market": "match_winner"},
        {"status": "lost", "gem_kind": "single", "market": "match_winner"},
    ])
    assert weights.get("kind:niche", 1) >= weights.get("kind:single", 1)
    assert summarize(_empty_book(1000))["bankroll"] == 1000

    rep = run_paper_walkforward(
        bankroll=5_000, match_budget=150, max_games=30, reset=True,
        full_slip=False, verbose=True,
    )
    assert rep.get("source") == "espn_boards"
    assert (rep["summary"].get("settled") or 0) >= 5, rep["summary"]
    apply_paper_learning()
    print(
        "ok", rep["summary"].get("settled"), "settled",
        "acc", rep["summary"].get("accuracy"),
        "pnl", rep["summary"].get("pnl"),
        "sports", rep["summary"].get("by_sport"),
    )


if __name__ == "__main__":
    main()
