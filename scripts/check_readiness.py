"""ponytail: readiness smoke — boards, model report (no auto-train), logos."""

from __future__ import annotations

from bet_placer.data.espn_leagues import fetch_espn_events
from bet_placer.data.providers import UnifiedOddsProvider
from bet_placer.ml.tracker import get_report


def main() -> None:
    p = UnifiedOddsProvider()
    all_soccer = p.fetch_events("soccer_all")
    assert all_soccer.source in ("espn", "odds_api", "demo"), all_soccer.source
    assert len(all_soccer.events) >= 20, f"too few soccer fixtures: {len(all_soccer.events)}"
    logos = sum(1 for e in all_soccer.events if e.home_logo and e.away_logo)
    assert logos >= 10, f"too few logos: {logos}"

    epl = fetch_espn_events("soccer_epl")
    assert isinstance(epl, list)

    rep = get_report(retrain=False)
    assert rep.get("status") in ("ready", "needs_train", "empty"), rep.get("status")
    assert "learning" in rep
    # Must not hang / must not force train
    assert rep.get("status") != "training"

    print(
        f"ok readiness soccer={len(all_soccer.events)} logos={logos} "
        f"model_status={rep.get('status')} elo_teams={(rep.get('learning') or {}).get('elo_teams')}"
    )


if __name__ == "__main__":
    main()
