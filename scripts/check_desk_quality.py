#!/usr/bin/env python3
"""Desk keeps every container visible; no negative ROI numbers published."""
from bet_placer.ml.desk_quality import publish_clean_desk, desk_quality_report, _finite_nonneg
from bet_placer.ml.model_insights import _sanitize_insights_payload
import json
import urllib.request


def main() -> None:
    rel = json.loads(
        urllib.request.urlopen(
            "https://api.github.com/repos/abhyvx/Gambit/releases/tags/model-latest"
        ).read()
    )
    url = next(a["browser_download_url"] for a in rel["assets"] if a["name"] == "model_insights_cache.json")
    raw = json.loads(urllib.request.urlopen(url).read())
    before = len(raw.get("containers") or [])
    clean = publish_clean_desk(_sanitize_insights_payload(raw))
    after = len(clean.get("containers") or [])
    assert after >= before, (before, after)  # never hide containers
    assert after >= 20, after
    for v in _finite_nonneg((clean.get("curves") or {}).get("craft_roi")):
        assert v >= 0, v
    # All three sports present on craft grids
    for cont in clean.get("containers") or []:
        if cont.get("kind") == "sport_grid":
            sports = {s.get("sport") for s in (cont.get("sports") or [])}
            assert sports >= {"soccer", "basketball", "cricket"}, (cont.get("id"), sports)
            for s in cont.get("sports") or []:
                if s.get("roi") is not None:
                    assert float(s["roi"]) >= 0, (cont.get("id"), s)
        for row in cont.get("rows") or []:
            if isinstance(row, dict) and row.get("roi") is not None:
                assert float(row["roi"]) >= 0, (cont.get("id"), row)
    # BB + CK niches visible
    labels = []
    for cont in clean.get("containers") or []:
        if cont.get("id") in ("15a_sport_markets", "15_niche_replay"):
            labels.extend(str(r.get("market") or "").lower() for r in (cont.get("rows") or []))
    assert any("basketball" in x for x in labels), labels[:10]
    assert any("cricket" in x for x in labels), labels[:10]
    # Holdout not blank when champion exists
    craft = clean.get("craft") or {}
    assert craft.get("holdout_roi") is not None or craft.get("best_roi") is not None
    # Factors depth
    fac = clean.get("factors") or {}
    assert int(fac.get("total_nodes") or 0) >= 10000, fac.get("total_nodes")
    print(
        "check_desk_quality: ok",
        after,
        "containers",
        "factors",
        fac.get("total_nodes"),
        "holdout",
        craft.get("holdout_roi"),
    )


if __name__ == "__main__":
    main()
