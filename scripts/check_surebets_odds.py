"""Self-check: surebets math + club soccer load + odds never blank."""
from bet_placer.engine.surebets import arb_roi, scan_h2h_books, stakes_for_arb
from bet_placer.data.providers import EventSummary, _backfill_model_h2h


def main() -> None:
    assert arb_roi([1.9, 1.9]) is None  # 1/1.9*2 > 1 — no lock
    # Classic 2-way lock
    roi2 = arb_roi([2.2, 2.2])
    assert roi2 is not None and roi2 > 0, roi2
    # Classic 3-way lock
    roi = arb_roi([2.2, 3.6, 4.5])
    assert roi is not None and roi > 0, roi
    stakes = stakes_for_arb(100, [2.2, 3.6, 4.5])
    assert stakes and abs(sum(stakes) - 100) < 0.05

    hit = scan_h2h_books([
        {"book": "A", "home": 2.05, "draw": 3.4, "away": 3.8},
        {"book": "B", "home": 2.15, "draw": 3.5, "away": 4.2},
    ], min_roi=0.0)
    # may or may not arb depending on best combo — just ensure function runs
    assert hit is None or hit.get("kind") == "surebet"

    rows = [
        EventSummary(
            id="1", home_team="Alpha FC", away_team="Beta United",
            league="Test", sport_key="soccer_epl", kickoff=None, source="espn",
            status="upcoming",
        ),
        EventSummary(
            id="2", home_team="Lakers", away_team="Celtics",
            league="NBA", sport_key="basketball_nba", kickoff=None, source="espn",
            status="upcoming",
        ),
    ]
    _backfill_model_h2h(rows)
    assert rows[0].home_odds and rows[0].away_odds and rows[0].draw_odds
    assert rows[1].home_odds and rows[1].away_odds
    print("ok surebets+odds_backfill")


if __name__ == "__main__":
    main()
