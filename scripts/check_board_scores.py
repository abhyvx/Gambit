#!/usr/bin/env python3
"""Self-check: cricket scores parse without dropping fixtures; display fields set."""
from __future__ import annotations

from bet_placer.data.espn_leagues import _cricket_score, _parse_event, _safe_int_score


def main() -> None:
    assert _cricket_score("125/7") == 125
    assert _cricket_score("125/7 & 40/1") == 125
    assert _safe_int_score("98") == 98
    assert _safe_int_score("125/7") == 125

    ev = {
        "id": "ck-1",
        "date": "2026-07-24T10:00:00Z",
        "status": {"type": {"name": "STATUS_IN_PROGRESS", "state": "in", "detail": "2nd innings"}},
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "score": "187/4", "team": {"id": "1", "displayName": "India"}},
                {"homeAway": "away", "score": "120/3", "team": {"id": "2", "displayName": "Australia"}},
            ],
        }],
    }
    parsed = _parse_event(ev, "cricket_all", "Test", "cricket")
    assert parsed is not None, "cricket event dropped on slash score"
    assert parsed["home_score"] == 187
    assert parsed["away_score"] == 120
    assert parsed["home_score_display"] == "187/4"
    assert parsed["away_score_display"] == "120/3"
    assert parsed["status"] == "live"
    assert "innings" in (parsed.get("status_detail") or "").lower()
    assert "/" in (parsed.get("score") or "")
    print("ok board scores")


if __name__ == "__main__":
    main()
