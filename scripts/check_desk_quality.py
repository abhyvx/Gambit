#!/usr/bin/env python3
"""Stored desk displays instantly — no training labels, no negatives."""
from bet_placer.ml.desk_quality import publish_clean_desk, _finite_nonneg
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
    clean = publish_clean_desk(_sanitize_insights_payload(raw))
    assert len(clean.get("containers") or []) >= 20
    for cont in clean.get("containers") or []:
        assert cont.get("status") != "training", cont.get("id")
        assert cont.get("status") != "building", cont.get("id")
        for row in list(cont.get("sports") or []) + list(cont.get("rows") or []):
            if not isinstance(row, dict):
                continue
            assert row.get("status") not in ("training", "building"), (cont.get("id"), row)
            if row.get("roi") is not None:
                assert float(row["roi"]) >= 0, (cont.get("id"), row)
    for v in _finite_nonneg((clean.get("curves") or {}).get("craft_roi")):
        assert v >= 0, v
    assert (clean.get("craft") or {}).get("holdout_roi") is not None
    print("check_desk_quality: ok", len(clean["containers"]), "holdout", clean["craft"]["holdout_roi"])


if __name__ == "__main__":
    main()
