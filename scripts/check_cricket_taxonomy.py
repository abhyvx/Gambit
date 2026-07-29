"""Spot-check cricket taxonomy + board filters (All / International / Domestic)."""
from __future__ import annotations

from collections import Counter

from bet_placer.data.espn_leagues import _filter_cricket_board, _tag_cricket_event, fetch_espn_events


def main() -> None:
    assert _tag_cricket_event("Indian Premier League", "MI", "CSK")[0] == "cricket_ipl"
    assert _tag_cricket_event("Big Bash League", "Stars", "Heat")[0] == "cricket_bbl"
    assert _tag_cricket_event("The Hundred Men's Competition", "Spirit", "Fire")[0] == "cricket_hundred"
    assert _tag_cricket_event("Pakistan Super League", "Zalmi", "Qalandars")[0] == "cricket_psl"
    assert _tag_cricket_event("ICC Champions Trophy", "India", "Australia")[0] == "cricket_tournaments"
    assert _tag_cricket_event("India tour of Zimbabwe 2026", "India", "Zimbabwe")[0] == "cricket_international"

    ev = fetch_espn_events("cricket_all")
    assert len(ev) >= 1
    keys = Counter(e.get("sport_key") for e in ev)
    intl = _filter_cricket_board(ev, "cricket_international")
    domestic = _filter_cricket_board(ev, "cricket_domestic")
    assert all(
        e["sport_key"] in ("cricket_international", "cricket_tournaments") for e in intl
    )
    assert all(
        e["sport_key"] not in ("cricket_international", "cricket_tournaments") for e in domestic
    )
    assert len(intl) + len(domestic) == len(ev)
    print("ok cricket_taxonomy", dict(keys), f"intl={len(intl)} domestic={len(domestic)}")


if __name__ == "__main__":
    main()
