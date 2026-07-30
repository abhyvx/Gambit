#!/usr/bin/env python3
"""Desk must never publish negative ROI / building containers."""
from bet_placer.ml.desk_quality import publish_clean_desk, desk_quality_report, _finite_nonneg
from bet_placer.ml.model_insights import ensure_insights_cache_on_disk, _sanitize_insights_payload
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
    clean = publish_clean_desk(_sanitize_insights_payload(raw))
    assert len(clean.get("containers") or []) >= 8, len(clean.get("containers") or [])
    for v in _finite_nonneg((clean.get("curves") or {}).get("craft_roi")):
        assert v >= 0, v
    for cont in clean.get("containers") or []:
        assert cont.get("status") != "building", cont.get("id")
        for row in list(cont.get("sports") or []) + list(cont.get("rows") or []):
            if not isinstance(row, dict):
                continue
            assert row.get("status") != "building", (cont.get("id"), row)
            if row.get("roi") is not None:
                assert float(row["roi"]) >= 0, (cont.get("id"), row)
    q = desk_quality_report(clean)
    assert q["fail_count"] == 0, q
    print("check_desk_quality: ok", q["ok_count"], "containers")


if __name__ == "__main__":
    main()
