#!/usr/bin/env python3
"""Open visible Stake Chrome, clear Cloudflare, scrape markets, push to Render.

This is the only reliable path for live Stake on cloud (Render/GHA are CF-blocked).

  PYTHONPATH=src python3 scripts/connect_stake_and_push.py
"""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    os.environ["STAKE_USE_BROWSER"] = "true"
    os.environ["STAKE_BROWSER_HEADLESS"] = "false"  # must be visible for CF
    os.environ.setdefault("STAKE_UPLOAD_RELEASE", "1")
    os.environ.setdefault("STAKE_RELAY_SECRET", "gambit-relay-v1-abhyvx")
    if not (os.getenv("GAMBIT_CLOUD_URL") or "").strip():
        os.environ.setdefault("GAMBIT_CLOUD_URL", "https://gambit-yqng.onrender.com")

    print("1) Killing stale Stake Chrome locks…")
    from bet_placer.data.stake_browser import kill_orphan_profile_chrome, warmup_visible, browser_status

    kill_orphan_profile_chrome(force=True)
    time.sleep(1)

    print("2) Opening visible Stake Chrome — finish 'Just a moment…' if it appears.")
    print("   Leave that window open. Waiting up to 5 minutes…")
    ok = warmup_visible(timeout=300)
    st = browser_status()
    print(f"   browser ready={ok} status={st}")
    if not ok and not st.get("ready"):
        print(
            "Cloudflare/session not ready. Complete the check in the Chrome window, then re-run.",
            file=sys.stderr,
        )
        return 1

    print("3) Scraping Stake trending markets…")
    from bet_placer.data.stake_scraper import StakeScraper
    from bet_placer.engine.stake_odds import (
        _overlay_key,
        _serialize_fixture,
        fetch_fast_stake_overlay,
        persist_match_stake_data,
        _save_disk_cache,
    )

    scraper = StakeScraper(timeout=120, allow_browser_launch=True)
    overlay = fetch_fast_stake_overlay(scraper)
    fixtures = {}
    for fx in overlay.values():
        if not fx.markets:
            continue
        try:
            persist_match_stake_data(fx.home_team, fx.away_team, fx, None)
        except Exception:
            pass
        fixtures[_overlay_key(fx.home_team, fx.away_team)] = _serialize_fixture(fx)

    print(f"   priced fixtures: {len(fixtures)}")
    if not fixtures:
        print("Scrape returned 0 markets — CF may still be blocking. Re-run after clearing.", file=sys.stderr)
        return 1

    try:
        _save_disk_cache()
    except Exception:
        pass

    print("4) Pushing to Render…")
    # Reuse push without re-scraping
    os.environ["STAKE_SKIP_LIVE"] = "1"
    os.environ["STAKE_SKIP_ESPN"] = "1"
    from push_stake_cache import main as push_main

    # Ensure disk has what we just scraped
    from bet_placer.config import data_path
    import json
    path = data_path("stake_overlay_cache.json")
    path.write_text(
        json.dumps({"updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "fixtures": fixtures, "overlays": {}}, indent=0),
        encoding="utf-8",
    )
    rc = push_main()
    if rc == 0:
        print("Done. Install the background agent with: ./scripts/install_stake_relay_agent.sh")
    return rc


if __name__ == "__main__":
    # scripts/ on path for push_stake_cache import
    sys.path.insert(0, os.path.dirname(__file__))
    raise SystemExit(main())
