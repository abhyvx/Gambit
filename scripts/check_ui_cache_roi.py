#!/usr/bin/env python3
"""ponytail: Layout must not remount on query changes; soccer evolution ROI >= 0."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    layout = (ROOT / "frontend/src/components/Layout.jsx").read_text(encoding="utf-8")
    assert "location.pathname + location.search" not in layout, "Layout remounts on ?focus= — kills boards"
    assert "location.pathname" in layout

    model = (ROOT / "frontend/src/pages/ModelPage.jsx").read_text(encoding="utf-8")
    assert "finished_without_hit" in model and "Missed target" in model
    assert "trainGateLabel" in model and "deskRoi" in model

    bits = (ROOT / "frontend/src/components/BoardBits.jsx").read_text(encoding="utf-8")
    assert "ft-odd-chip" in bits

    from bet_placer.ml.betting_evolution import snapshot

    snap = snapshot()
    soc = (snap.get("by_sport") or {}).get("soccer") or {}
    assert float(soc.get("roi") or -1) >= 0, soc
    bad = [
        t["ym"]
        for t in (snap.get("trends") or [])
        if t.get("sport") == "soccer" and str(t.get("ym", "")).startswith("209")
    ]
    assert not bad, bad
    print("check_ui_cache_roi: ok")


if __name__ == "__main__":
    main()
