"""One-shot Stake relay push for GitHub Actions (every 15 min, no laptop)."""
from __future__ import annotations

import os
import sys


def main() -> int:
    cloud = (os.getenv("GAMBIT_CLOUD_URL") or "").strip().rstrip("/")
    if not cloud:
        # Optional: deploy/cloud_url.txt committed with your Render URL
        p = os.path.join(os.path.dirname(__file__), "..", "deploy", "cloud_url.txt")
        if os.path.isfile(p):
            cloud = open(p, encoding="utf-8").read().strip().rstrip("/")
    secret = (os.getenv("STAKE_RELAY_SECRET") or "gambit-relay-v1-abhyvx").strip()
    if not cloud:
        print("Set GAMBIT_CLOUD_URL or deploy/cloud_url.txt", file=sys.stderr)
        return 1

    os.environ.setdefault("STAKE_USE_BROWSER", "true")
    import requests
    from bet_placer.data.stake_scraper import StakeScraper
    from bet_placer.engine.stake_odds import (
        _overlay_key,
        _serialize_fixture,
        fetch_fast_stake_overlay,
        persist_match_stake_data,
    )

    scraper = StakeScraper(timeout=120, allow_browser_launch=True)
    overlay = fetch_fast_stake_overlay(scraper)
    fixtures = {}
    for fx in overlay.values():
        if fx.markets:
            persist_match_stake_data(fx.home_team, fx.away_team, fx, None)
            fixtures[_overlay_key(fx.home_team, fx.away_team)] = _serialize_fixture(fx)

    if not fixtures:
        print("no Stake fixtures fetched (Cloudflare may block this runner)")
        return 0

    r = requests.post(
        f"{cloud}/api/stake/relay",
        json={"secret": secret, "fixtures": fixtures},
        timeout=120,
    )
    r.raise_for_status()
    print("relay OK", r.json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
