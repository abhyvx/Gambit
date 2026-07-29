"""ponytail: ESPN boards must return crests; upgrade = Odds API + Stake logos."""

from bet_placer.data.espn_leagues import fetch_espn_events


def main() -> None:
    events = fetch_espn_events("soccer_all")
    assert len(events) >= 1, "soccer_all empty"
    with_logo = sum(1 for e in events if e.get("home_logo") and e.get("away_logo"))
    assert with_logo >= 1, "no team logos on soccer_all"
    titled = sum(1 for e in events if e.get("sport_title") and e["sport_title"] != "all")
    assert titled >= 1, "league titles missing"
    print(f"ok espn soccer_all n={len(events)} logos={with_logo} titled={titled}")


if __name__ == "__main__":
    main()
