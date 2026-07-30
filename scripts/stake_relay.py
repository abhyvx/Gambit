#!/usr/bin/env python3
"""On-demand Stake odds relay (laptop → Render).

Cloud IPs get 403 from stake.com. Run this on your Mac while you use Admin:

  ./scripts/start_stake_relay.sh

It stays idle (heartbeat only — no Chrome) until Admin → Sync Stake odds now.
Then it scrapes once (reuses the Stake profile; opens a window only if Cloudflare
needs a click), POSTs to /api/stake/relay, and goes idle again.

Legacy every-N-minutes scrape:
  STAKE_RELAY_MODE=interval ./scripts/start_stake_relay.sh
"""
from __future__ import annotations

import os
import sys
import time

import requests


def _cloud() -> str:
    return (os.getenv("GAMBIT_CLOUD_URL") or "").strip().rstrip("/")


def _secret() -> str:
    return (os.getenv("STAKE_RELAY_SECRET") or "").strip()


def _poll_tasks(cloud: str, secret: str) -> dict:
    r = requests.get(
        f"{cloud}/api/relay/tasks",
        params={"secret": secret},
        timeout=30,
    )
    r.raise_for_status()
    return r.json() or {}


def _push_odds(cloud: str, secret: str) -> dict:
    os.environ.setdefault("STAKE_USE_BROWSER", "true")
    from bet_placer.data.stake_scraper import StakeScraper
    from bet_placer.engine.stake_odds import (
        _overlay_key,
        _serialize_fixture,
        fetch_fast_stake_overlay,
        persist_match_stake_data,
    )

    scraper = StakeScraper(timeout=90, allow_browser_launch=True)
    overlay = fetch_fast_stake_overlay(scraper)
    for fx in overlay.values():
        if fx.markets:
            persist_match_stake_data(fx.home_team, fx.away_team, fx, None)
    fixtures = {
        _overlay_key(fx.home_team, fx.away_team): _serialize_fixture(fx)
        for fx in overlay.values()
        if fx.markets
    }
    if not fixtures:
        print("no Stake fixtures (finish Cloudflare in the Stake window if it opened)")
        return {"ingested": 0}
    r = requests.post(
        f"{cloud}/api/stake/relay",
        json={"secret": secret, "fixtures": fixtures},
        timeout=120,
    )
    r.raise_for_status()
    out = r.json()
    print("OK", out.get("ingested"), "fixtures", out.get("status", {}))
    return out


def _drain_portfolio_jobs(cloud: str, secret: str) -> None:
    """Reuse push_stake_cache job drainer when Admin/users queue token imports."""
    sys.path.insert(0, os.path.dirname(__file__))
    from push_stake_cache import _process_portfolio_sync_jobs

    _process_portfolio_sync_jobs(cloud, secret)


def main() -> None:
    cloud = _cloud()
    secret = _secret()
    if not secret:
        raise SystemExit("Set STAKE_RELAY_SECRET before running the Stake relay.")
    if not cloud:
        print("Set GAMBIT_CLOUD_URL in .env (your Render app URL)", file=sys.stderr)
        sys.exit(1)

    mode = (os.getenv("STAKE_RELAY_MODE") or "on_demand").strip().lower()
    if mode in ("ondemand", "demand", "admin"):
        mode = "on_demand"
    poll_s = max(5, int(os.getenv("STAKE_RELAY_POLL_SECONDS", "15")))
    interval = max(60, int(os.getenv("STAKE_RELAY_INTERVAL", "300")))

    # Prefer quiet reuse of the cleared profile; visible only if CF blocks.
    os.environ.setdefault("STAKE_BROWSER_HEADLESS", "true")

    if mode == "on_demand":
        print(f"Stake relay on-demand → {cloud}")
        print(f"Idle poll every {poll_s}s (no Chrome until Admin → Sync Stake odds now). Ctrl+C to stop.")
    else:
        print(f"Stake relay interval → {cloud} every {interval}s (Ctrl+C to stop)")

    while True:
        try:
            tasks = {}
            try:
                tasks = _poll_tasks(cloud, secret)
            except Exception as exc:
                print("tasks poll:", exc)
                time.sleep(min(60, poll_s if mode == "on_demand" else interval))
                continue

            force = bool(tasks.get("odds_push_requested"))
            jobs = tasks.get("portfolio_jobs") or []
            if jobs:
                print(f"{len(jobs)} pending portfolio sync job(s)")
            if force:
                print("admin requested odds push — scraping now")

            should_push = mode == "interval" or force or bool(jobs)
            if should_push:
                if force or mode == "interval":
                    _push_odds(cloud, secret)
                if jobs:
                    try:
                        _drain_portfolio_jobs(cloud, secret)
                    except Exception as exc:
                        print("portfolio sync jobs:", exc)
                time.sleep(20 if force else (poll_s if mode == "on_demand" else interval))
            else:
                # Heartbeat already recorded by /api/relay/tasks — stay quiet.
                time.sleep(poll_s)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as exc:
            print("relay error:", exc)
            time.sleep(min(60, poll_s if mode == "on_demand" else interval))


if __name__ == "__main__":
    main()
