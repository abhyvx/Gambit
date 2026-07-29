#!/usr/bin/env python3
"""Push Stake odds to Render — scrape when possible, else push last good disk cache.

Never wipes local cache on a failed scrape. Cloudflare must be cleared once in the
Stake Chrome window on this machine; after that, headless reuse usually works.

  PYTHONPATH=src python3 scripts/push_stake_cache.py
  # or: ./scripts/start_stake_relay.sh

Set STAKE_UPLOAD_RELEASE=1 to also upload stake_overlay_cache.json to model-latest
so Render bootstrap survives redeploys.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _cloud_url() -> str:
    cloud = (os.getenv("GAMBIT_CLOUD_URL") or "").strip().rstrip("/")
    if cloud:
        return cloud
    p = Path(__file__).resolve().parent.parent / "deploy" / "cloud_url.txt"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("https://") and "YOUR-SERVICE" not in line:
                return line.rstrip("/")
    return ""


def _disk_path():
    from bet_placer.config import data_path

    return data_path("stake_overlay_cache.json")


def _disk_fixtures() -> dict:
    path = _disk_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for key, fx in (raw.get("fixtures") or {}).items():
        if fx and fx.get("markets"):
            out[key] = fx
    return out


def _scrub_empty_disk() -> None:
    """Drop poisoned 0-market shells so they don't look like a real cache."""
    path = _disk_path()
    if not path.is_file():
        return
    good = _disk_fixtures()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    total = len(raw.get("fixtures") or {})
    if total and not good:
        path.unlink(missing_ok=True)
        print(f"scrubbed empty Stake cache ({total} shells, 0 markets)")


def _post(cloud: str, secret: str, fixtures: dict) -> dict:
    import requests

    r = requests.post(
        f"{cloud}/api/stake/relay",
        json={"secret": secret, "fixtures": fixtures},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _upload_release(path: Path) -> None:
    if os.getenv("STAKE_UPLOAD_RELEASE", "").strip().lower() not in ("1", "true", "yes"):
        return
    if not path.is_file():
        return
    repo = os.getenv("GAMBIT_REPO", "abhyvx/Gambit")
    tag = os.getenv("GAMBIT_MODEL_TAG", "model-latest")
    try:
        subprocess.run(
            ["gh", "release", "upload", tag, str(path), "--repo", repo, "--clobber"],
            check=True,
            timeout=120,
        )
        print(f"uploaded {path.name} → {repo}@{tag}")
    except Exception as exc:
        print(f"release upload skipped: {exc}")


def main() -> int:
    cloud = _cloud_url()
    secret = (os.getenv("STAKE_RELAY_SECRET") or "gambit-relay-v1-abhyvx").strip()
    if not cloud:
        print("Set GAMBIT_CLOUD_URL or deploy/cloud_url.txt", file=sys.stderr)
        return 1

    os.environ.setdefault("STAKE_USE_BROWSER", "true")
    _scrub_empty_disk()

    fixtures: dict = {}
    source = "none"

    # 1) Try live scrape (laptop / self-hosted runner with CF cleared)
    try:
        from bet_placer.data.stake_scraper import StakeScraper
        from bet_placer.engine.stake_odds import (
            _overlay_key,
            _serialize_fixture,
            fetch_fast_stake_overlay,
            persist_match_stake_data,
        )

        scraper = StakeScraper(timeout=120, allow_browser_launch=True)
        overlay = fetch_fast_stake_overlay(scraper)
        for fx in overlay.values():
            if not fx.markets:
                continue
            try:
                persist_match_stake_data(fx.home_team, fx.away_team, fx, None)
            except Exception:
                pass
            fixtures[_overlay_key(fx.home_team, fx.away_team)] = _serialize_fixture(fx)
        if fixtures:
            source = "live_scrape"
    except Exception as exc:
        print(f"live scrape skipped: {exc}")

    # 2) Fall back to last good disk cache — never invent empty
    if not fixtures:
        fixtures = _disk_fixtures()
        if fixtures:
            source = "disk_cache"
            print(f"using disk cache ({len(fixtures)} fixtures)")

    if not fixtures:
        print(
            "No Stake fixtures to push. Open Stake Chrome, finish Cloudflare, "
            "then re-run. App stays on ESPN/model until then."
        )
        return 0

    try:
        out = _post(cloud, secret, fixtures)
        print(f"OK source={source} ingested={out.get('ingested')} status={out.get('status')}")
        _upload_release(_disk_path())
        return 0
    except Exception as exc:
        print(f"relay POST failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
