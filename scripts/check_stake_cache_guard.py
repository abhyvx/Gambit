#!/usr/bin/env python3
"""ponytail: empty Stake shells must not replace priced overlay / wipe disk."""
from __future__ import annotations

from bet_placer.engine import stake_odds as so
from bet_placer.models.stake_types import StakeFixture, StakeMarket, StakeOutcome


def _fx(home: str, away: str, priced: bool) -> StakeFixture:
    markets = []
    if priced:
        markets = [
            StakeMarket(
                id="m1",
                name="Match Odds",
                group="winner",
                outcomes=[
                    StakeOutcome(id="o1", name=home, odds=1.8),
                    StakeOutcome(id="o2", name=away, odds=4.2),
                ],
            )
        ]
    return StakeFixture(
        id=f"{home}-{away}",
        name=f"{home} vs {away}",
        home_team=home,
        away_team=away,
        sport="soccer",
        league="Test",
        kickoff=None,
        status="upcoming",
        markets=markets,
    )


def main() -> None:
    with so._overlay_cache_lock:
        so._overlay_cache.clear()
        so._overlay_disk_overlays.clear()
        so._disk_loaded = True  # skip disk warm for unit check
        key = so._overlay_key("Alpha", "Beta")
        so._overlay_cache[key] = _fx("Alpha", "Beta", priced=True)

    # Simulate a bad fetch of empty shells for the same match + a new one
    fetched = {
        so._overlay_key("Alpha", "Beta"): _fx("Alpha", "Beta", priced=False),
        so._overlay_key("Gamma", "Delta"): _fx("Gamma", "Delta", priced=False),
    }
    priced = {k: fx for k, fx in fetched.items() if fx and fx.markets}
    with so._overlay_cache_lock:
        if priced:
            so._overlay_cache.update(priced)
        kept = so._overlay_cache.get(so._overlay_key("Alpha", "Beta"))
        assert kept and kept.markets, "priced fixture must survive empty-shell fetch"
        assert so._overlay_key("Gamma", "Delta") not in so._overlay_cache

    print("check_stake_cache_guard: ok")


if __name__ == "__main__":
    main()
