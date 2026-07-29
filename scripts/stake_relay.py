#!/usr/bin/env python3
"""Push live Stake odds from your laptop to cloud Gambit (Render).

Cloud servers get 403 from stake.com. This script runs locally with Playwright,
then POSTs the overlay to your deployed API every few minutes.

Setup:
  1. Render env: STAKE_RELAY_SECRET=pick-a-long-random-string
  2. Local .env:
       STAKE_USE_BROWSER=true
       STAKE_RELAY_SECRET=same-string
       GAMBIT_CLOUD_URL=https://your-app.onrender.com
  3. Run: PYTHONPATH=src python3 scripts/stake_relay.py

Keep this terminal open while you use the cloud app.
"""
from __future__ import annotations

import os
import sys
import time

import requests


def main() -> None:
    cloud = (os.getenv("GAMBIT_CLOUD_URL") or "").strip().rstrip("/")
    secret = (os.getenv("STAKE_RELAY_SECRET") or "gambit-relay-v1-abhyvx").strip()
    interval = int(os.getenv("STAKE_RELAY_INTERVAL", "300"))
    if not cloud:
        print("Set GAMBIT_CLOUD_URL in .env (your Render app URL)", file=sys.stderr)
        sys.exit(1)

    os.environ.setdefault("STAKE_USE_BROWSER", "true")
    from bet_placer.data.stake_scraper import StakeScraper
    from bet_placer.engine.stake_odds import fetch_fast_stake_overlay, persist_match_stake_data

    print(f"Stake relay -> {cloud}/api/stake/relay every {interval}s (Ctrl+C to stop)")
    while True:
        try:
            scraper = StakeScraper(timeout=90, allow_browser_launch=True)
            overlay = fetch_fast_stake_overlay(scraper)
            for fx in overlay.values():
                if fx.markets:
                    persist_match_stake_data(fx.home_team, fx.away_team, fx, None)
            from bet_placer.engine.stake_odds import _overlay_key, _serialize_fixture
            fixtures = {
                _overlay_key(fx.home_team, fx.away_team): _serialize_fixture(fx)
                for fx in overlay.values()
                if fx.markets
            }
            if not fixtures:
                print("no Stake fixtures (open Chrome / complete Cloudflare if prompted)")
                time.sleep(interval)
                continue
            r = requests.post(
                f"{cloud}/api/stake/relay",
                json={"secret": secret, "fixtures": fixtures},
                timeout=120,
            )
            r.raise_for_status()
            out = r.json()
            print("OK", out.get("ingested"), "fixtures", out.get("status", {}))
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as exc:
            print("relay error:", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
