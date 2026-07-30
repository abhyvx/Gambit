#!/usr/bin/env python3
"""Real Stake account login on your laptop (Render cannot do this).

Opens visible Chrome → you sign into Stake → verifies GraphQL user session →
imports bet history → optionally pushes portfolio + odds to Render.

  PYTHONPATH=src python3 scripts/stake_login.py
  PYTHONPATH=src python3 scripts/stake_login.py --no-push
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Stake login + portfolio sync")
    parser.add_argument("--no-push", action="store_true", help="Skip Render upload")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to wait for login")
    args = parser.parse_args()

    os.environ["STAKE_USE_BROWSER"] = "true"
    os.environ["STAKE_BROWSER_HEADLESS"] = "false"
    if not (os.getenv("STAKE_RELAY_SECRET") or "").strip():
        raise SystemExit("Set STAKE_RELAY_SECRET before running Stake login sync.")
    if not (os.getenv("GAMBIT_CLOUD_URL") or "").strip():
        os.environ.setdefault("GAMBIT_CLOUD_URL", "https://gambit-yqng.onrender.com")

    print("1) Clearing stale Chrome profile locks…")
    from bet_placer.data.stake_browser import (
        browser_status,
        kill_orphan_profile_chrome,
        wait_until_logged_in,
    )

    kill_orphan_profile_chrome(force=True)
    time.sleep(1)

    print("2) Opening Stake login (Chrome). Clear Cloudflare if needed, then sign in.")
    print(f"   Waiting up to {args.timeout}s for account session…")
    login = wait_until_logged_in(timeout=args.timeout)
    print(f"   {login.get('message') or login}")
    if not login.get("logged_in"):
        print(
            "Not logged in yet. Finish sign-in in the Chrome window, then re-run.",
            file=sys.stderr,
        )
        print(f"   browser={browser_status()}", file=sys.stderr)
        return 1

    print("3) Enabling private portfolio + importing Stake bet history…")
    from bet_placer.portfolio.store import (
        portfolio_relay_export,
        refresh_portfolio_snapshot,
        update_privacy_settings,
    )

    update_privacy_settings(
        portfolio_enabled=True,
        risk_acknowledged=True,
        learning_opt_in=False,
    )
    snap = refresh_portfolio_snapshot()
    bets = len((snap.get("portfolio") or {}).get("bets") or [])
    print(f"   imported bets: {bets}")
    print(f"   sync: {(snap.get('connection') or {}).get('last_sync_message')}")

    if args.no_push:
        print("Done (local only).")
        return 0

    cloud = (os.getenv("GAMBIT_CLOUD_URL") or "").rstrip("/")
    secret = os.getenv("STAKE_RELAY_SECRET") or ""
    if not cloud or not secret:
        print("No GAMBIT_CLOUD_URL / STAKE_RELAY_SECRET — skip push.")
        return 0

    print("4) Pushing portfolio snapshot to Render…")
    export = portfolio_relay_export()
    try:
        out = _post_json(
            f"{cloud}/api/portfolio/relay",
            {"secret": secret, **export},
            timeout=60,
        )
        print(f"   portfolio relay ok: {(out.get('connection') or {}).get('last_sync_message')}")
    except urllib.error.HTTPError as exc:
        print(f"   portfolio relay failed: HTTP {exc.code} {exc.read()[:200]!r}", file=sys.stderr)
    except Exception as exc:
        print(f"   portfolio relay failed: {exc}", file=sys.stderr)

    # Durable across Render redeploys (bootstrap pulls model-latest assets).
    os.environ.setdefault("STAKE_UPLOAD_RELEASE", "1")
    try:
        from bet_placer.config import data_path
        from push_stake_cache import _upload_release

        _upload_release(data_path("portfolio_state.json"))
    except Exception as exc:
        print(f"   portfolio release upload skipped: {exc}")

    print("5) Pushing Stake odds overlay (best-effort)…")
    try:
        os.environ["STAKE_SKIP_LIVE"] = "0"
        os.environ["STAKE_SKIP_ESPN"] = "1"
        os.environ.setdefault("STAKE_UPLOAD_RELEASE", "0")
        # Reuse connect script scrape+push when browser already warm
        from bet_placer.engine.stake_odds import (
            _overlay_key,
            _save_disk_cache,
            _serialize_fixture,
            fetch_fast_stake_overlay,
            persist_match_stake_data,
        )
        from bet_placer.data.stake_scraper import StakeScraper

        scraper = StakeScraper(timeout=90, allow_browser_launch=True)
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
        try:
            _save_disk_cache()
        except Exception:
            pass
        if fixtures:
            odds_out = _post_json(
                f"{cloud}/api/stake/relay",
                {"secret": secret, "fixtures": fixtures},
                timeout=120,
            )
            print(f"   odds relay: {odds_out}")
        else:
            print("   odds scrape empty — portfolio still pushed.")
    except Exception as exc:
        print(f"   odds push skipped: {exc}")

    print("Done. Open Portfolio on Render — it should show the synced journal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
