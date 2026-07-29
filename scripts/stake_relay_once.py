"""One-shot Stake relay push for GitHub Actions (every 15 min, no laptop).

Render cannot scrape stake.com (403). This job runs Playwright on GitHub,
then POSTs fixtures to the cloud app. If Cloudflare blocks the runner,
exit 0 so the app keeps serving ESPN/model prices instead of failing the workflow.
"""
from __future__ import annotations

import os
import sys


def _cloud_url() -> str:
    cloud = (os.getenv("GAMBIT_CLOUD_URL") or "").strip().rstrip("/")
    if cloud:
        return cloud
    p = os.path.join(os.path.dirname(__file__), "..", "deploy", "cloud_url.txt")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line.startswith("https://") and "YOUR-SERVICE" not in line:
                return line.rstrip("/")
    return ""


def main() -> int:
    cloud = _cloud_url()
    secret = (os.getenv("STAKE_RELAY_SECRET") or "gambit-relay-v1-abhyvx").strip()
    if not cloud:
        print("Skip: set GAMBIT_CLOUD_URL or deploy/cloud_url.txt with your Render URL")
        return 0

    os.environ.setdefault("STAKE_USE_BROWSER", "true")
    try:
        import requests
        from bet_placer.data.stake_scraper import StakeScraper
        from bet_placer.engine.stake_odds import (
            _overlay_key,
            _serialize_fixture,
            fetch_fast_stake_overlay,
            persist_match_stake_data,
        )
    except Exception as exc:
        print(f"Skip: import failed ({exc})")
        return 0

    try:
        scraper = StakeScraper(timeout=120, allow_browser_launch=True)
        overlay = fetch_fast_stake_overlay(scraper)
    except Exception as exc:
        print(f"Skip: Stake fetch failed ({exc}). App will use ESPN/model prices.")
        return 0

    fixtures = {}
    for fx in overlay.values():
        if fx.markets:
            try:
                persist_match_stake_data(fx.home_team, fx.away_team, fx, None)
            except Exception:
                pass
            fixtures[_overlay_key(fx.home_team, fx.away_team)] = _serialize_fixture(fx)

    if not fixtures:
        print("Skip: no Stake fixtures (Cloudflare may block this runner). App stays on ESPN/model prices.")
        return 0

    try:
        r = requests.post(
            f"{cloud}/api/stake/relay",
            json={"secret": secret, "fixtures": fixtures},
            timeout=120,
        )
        r.raise_for_status()
        print("relay OK", r.json())
    except Exception as exc:
        print(f"Skip: relay POST failed ({exc})")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
