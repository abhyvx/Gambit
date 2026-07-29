#!/usr/bin/env python3
"""Offline equal-depth rebuild: factors + betting evolution + optional craft.

Does NOT call Odds API network — cache / free corpora only.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    verbose = "--quiet" not in sys.argv
    do_craft = "--craft" in sys.argv
    do_train = "--train" in sys.argv

    if do_train:
        from bet_placer.ml.tracker import train
        print("[depth] full train (sport history + boards + report persist)…")
        rep = train(verbose=verbose)
        print("[depth] trained_on", rep.get("trained_on"), "factors", (rep.get("factors") or {}).get("total_nodes"))
        print("[depth] betting", (rep.get("betting") or {}).get("paired_by_sport"))
        return 0

    # Fast path: rebuild stores from existing params + corpora
    from bet_placer.ml.factor_store import rebuild as rebuild_factors
    from bet_placer.ml.betting_evolution import rebuild_from_corpora

    print("[depth] factor_store…")
    factors = rebuild_factors()
    print(json.dumps({"factors": factors}, indent=2)[:800])

    print("[depth] betting_evolution…")
    betting = rebuild_from_corpora(verbose=verbose)
    print(json.dumps({"betting": {
        "paired_by_sport": betting.get("paired_by_sport"),
        "by_sport": betting.get("by_sport"),
        "n_months": betting.get("n_months"),
    }}, indent=2))

    assert factors.get("total_nodes", 0) > 500, factors
    paired = betting.get("paired_by_sport") or {}
    for sport in ("soccer", "basketball", "cricket"):
        assert paired.get(sport, 0) > 0, f"no pairs for {sport}: {paired}"

    if do_craft:
        from bet_placer.ml.craft_train import train_until_roi
        print("[depth] craft until ROI…")
        out = train_until_roi(target_roi=0.25, max_epochs=40, bankroll=10_000, match_budget=200, verbose=verbose)
        print("[depth] craft", {k: out.get(k) for k in ("hit_target", "n_epochs", "best") if k in out or True})

    print("[depth] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
