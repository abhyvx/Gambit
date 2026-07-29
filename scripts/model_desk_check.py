#!/usr/bin/env python3
"""Self-check: monthly gates + insights cache version."""
from __future__ import annotations

from bet_placer.ml.craft_train import _monthly_nonneg
from bet_placer.ml.model_insights import INSIGHTS_CACHE_VERSION, _fresh_craft_gates


def main() -> None:
    ok, detail = _monthly_nonneg()
    assert detail.get("source") == "betting_evolution" or ok
    sports = detail.get("sports") or {}
    assert set(sports) >= {"soccer", "basketball", "cricket"}
    # When betting trends exist, all three should be non-negative windows
    if detail.get("source") == "betting_evolution":
        assert ok and all(g.get("ok") for g in sports.values()), detail
    gates = _fresh_craft_gates({}, {})
    assert (gates.get("monthly") or {}).get("all_ok") is True
    assert INSIGHTS_CACHE_VERSION >= 3
    print("model_desk_check ok")


if __name__ == "__main__":
    main()
