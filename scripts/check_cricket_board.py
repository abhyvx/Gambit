"""Smoke: cricket board has fixtures + logos; multi-source path doesn't crash."""
from __future__ import annotations

from bet_placer.data.espn_leagues import _filter_cricket_board, fetch_espn_events
from bet_placer.data.providers import UnifiedOddsProvider


def main() -> None:
    espn = fetch_espn_events("cricket_all")
    assert len(espn) >= 1, "ESPN cricket_all empty"
    logos = sum(1 for e in espn if e.get("home_logo") and e.get("away_logo"))
    assert logos >= 1, "no cricket logos"

    intl = _filter_cricket_board(espn, "cricket_international")
    dom = _filter_cricket_board(espn, "cricket_domestic")
    assert all(
        e.get("sport_key") in ("cricket_international", "cricket_tournaments")
        for e in intl
    )
    assert all(
        e.get("sport_key") not in ("cricket_international", "cricket_tournaments")
        for e in dom
    )
    assert len(intl) + len(dom) == len(espn)

    prov = UnifiedOddsProvider()
    result = prov.fetch_events("cricket_all")
    assert len(result.events) >= 1, result.message
    assert any(e.home_logo for e in result.events), "provider lost logos"
    print(
        "ok cricket_board",
        {
            "espn": len(espn),
            "intl": len(intl),
            "domestic": len(dom),
            "provider": len(result.events),
            "source": result.source,
            "priced": sum(1 for e in result.events if e.home_odds and e.away_odds),
        },
    )


if __name__ == "__main__":
    main()
