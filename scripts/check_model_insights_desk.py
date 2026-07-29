#!/usr/bin/env python3
"""ponytail: insights must paint charts without hanging / empty containers."""
from bet_placer.ml.model_insights import build_model_insights, craft_fallback_desk, load_insights_cache


def main() -> None:
    fb = craft_fallback_desk()
    assert len(fb.get("containers") or []) >= 5, fb
    assert (fb.get("curves") or {}).get("betting_trends") is not None
    charts = [c for c in fb["containers"] if c.get("kind") == "chart"]
    assert charts, "fallback must include chart containers"

    d = build_model_insights()
    assert int(d.get("total_corpus") or 0) > 1000, d.get("total_corpus")
    assert len(d.get("containers") or []) >= 20
    factor = next(c for c in d["containers"] if c["id"] == "18_factor_graph")
    assert int(factor.get("total_nodes") or 0) >= 10, factor

    cached = load_insights_cache(max_age_s=120)
    assert cached and cached.get("containers"), "disk cache missing after build"
    print("check_model_insights_desk: ok")


if __name__ == "__main__":
    main()
