"""Smoke: ESPN boards return fixtures + logos + some prices."""
from __future__ import annotations

from bet_placer.data.espn_leagues import fetch_espn_events


def _check(key: str, min_events: int = 1) -> None:
    ev = fetch_espn_events(key)
    assert len(ev) >= min_events, f"{key}: expected >= {min_events}, got {len(ev)}"
    logos = sum(1 for e in ev if e.get("home_logo") and e.get("away_logo"))
    assert logos == len(ev), f"{key}: missing logos {logos}/{len(ev)}"
    live = [e for e in ev if e.get("status") in ("live", "upcoming")]
    priced = [e for e in live if e.get("bookmakers")]
    print(f"ok {key}: {len(ev)} fixtures, {len(live)} open, {len(priced)} priced")


if __name__ == "__main__":
    _check("soccer_all", 50)
    _check("basketball_all", 1)
    _check("cricket_all", 1)
    print("espn_board_ok")
