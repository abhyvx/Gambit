"""Cached Stake fixture data for offline / unreachable network fallback."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.models.stake_types import BettorPick, StakeFixture, StakeMarket, StakeOutcome

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "stake_cache.json"


def get_cached_fixtures() -> list[StakeFixture]:
    if CACHE_PATH.exists():
        data = json.loads(CACHE_PATH.read_text())
        return [_fixture_from_dict(f) for f in data.get("fixtures", [])]
    return _default_fixtures()


def get_cached_bets() -> tuple[list[BettorPick], list[BettorPick]]:
    if CACHE_PATH.exists():
        data = json.loads(CACHE_PATH.read_text())
        live = [_pick_from_dict(p) for p in data.get("live_bets", [])]
        hr = [_pick_from_dict(p) for p in data.get("highroller_bets", [])]
        return live, hr
    return _default_bets()


def save_cache(
    fixtures: list[StakeFixture],
    live_bets: list[BettorPick],
    highroller_bets: list[BettorPick],
) -> None:
    CACHE_PATH.write_text(json.dumps({
        "fixtures": [_fixture_to_dict(f) for f in fixtures],
        "live_bets": [_pick_to_dict(p) for p in live_bets],
        "highroller_bets": [_pick_to_dict(p) for p in highroller_bets],
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def fetch_or_cache(scraper: StakeScraper, sport: str = "soccer") -> tuple[list[StakeFixture], list[BettorPick], list[BettorPick], bool]:
    """Returns (fixtures, live_bets, highroller_bets, from_live)."""
    try:
        fixtures = scraper.fetch_trending_fixtures(sport_slug=sport)
        live = scraper.fetch_live_bets(limit=150)
        hr = scraper.fetch_highroller_bets(limit=75)
        if fixtures:
            save_cache(fixtures, live, hr)
        return fixtures, live, hr, True
    except Exception:
        # Network/Cloudflare failure — serve last-known-good cached data instead.
        logger.warning("Stake live fetch failed; serving cached fixtures", exc_info=True)
        fixtures = get_cached_fixtures()
        live, hr = get_cached_bets()
        return fixtures, live, hr, False


def _default_fixtures() -> list[StakeFixture]:
    now = datetime.now(timezone.utc)
    return [
        StakeFixture(
            id="cache-liverpool-chelsea",
            name="Liverpool - Chelsea",
            home_team="Liverpool",
            away_team="Chelsea",
            sport="Soccer",
            league="Premier League",
            status="active",
            kickoff=now,
            total_bet_value=125000,
            total_bet_count=890,
            total_user_count=412,
            markets=[
                StakeMarket("1x2", "winner", [
                    StakeOutcome("1", "Liverpool", 1.78),
                    StakeOutcome("x", "Draw", 4.10),
                    StakeOutcome("2", "Chelsea", 4.40),
                ]),
                StakeMarket("Total Goals 2.5", "totals", [
                    StakeOutcome("o", "Over 2.5", 1.70),
                    StakeOutcome("u", "Under 2.5", 2.18),
                ], line=2.5),
                StakeMarket("Both Teams to Score", "btts", [
                    StakeOutcome("y", "Yes", 1.60),
                    StakeOutcome("n", "No", 2.32),
                ]),
                StakeMarket("Total Corners 9.5", "corners", [
                    StakeOutcome("o", "Over 9.5", 1.88),
                    StakeOutcome("u", "Under 9.5", 1.92),
                ], line=9.5),
            ],
        ),
        StakeFixture(
            id="cache-arsenal-city",
            name="Arsenal - Manchester City",
            home_team="Arsenal",
            away_team="Manchester City",
            sport="Soccer",
            league="Premier League",
            status="active",
            kickoff=now,
            total_bet_value=98000,
            total_bet_count=720,
            total_user_count=380,
            markets=[
                StakeMarket("1x2", "winner", [
                    StakeOutcome("1", "Arsenal", 2.65),
                    StakeOutcome("x", "Draw", 3.55),
                    StakeOutcome("2", "Manchester City", 2.62),
                ]),
                StakeMarket("Total Goals 2.5", "totals", [
                    StakeOutcome("o", "Over 2.5", 1.78),
                    StakeOutcome("u", "Under 2.5", 2.08),
                ], line=2.5),
                StakeMarket("Both Teams to Score", "btts", [
                    StakeOutcome("y", "Yes", 1.68),
                    StakeOutcome("n", "No", 2.20),
                ]),
            ],
        ),
    ]


def _default_bets() -> tuple[list[BettorPick], list[BettorPick]]:
    live = [
        BettorPick("Liverpool - Chelsea", "Liverpool", 1.78, 250.0, "whale_crypto", False, "Soccer"),
        BettorPick("Liverpool - Chelsea", "Liverpool", 1.78, 120.0, "anon_bettor", False, "Soccer"),
        BettorPick("Liverpool - Chelsea", "Over 2.5", 1.70, 80.0, "goals_fan", False, "Soccer"),
        BettorPick("Liverpool - Chelsea", "Chelsea", 4.40, 45.0, "longshot", False, "Soccer"),
        BettorPick("Arsenal - Manchester City", "Arsenal", 2.65, 200.0, "gunner", False, "Soccer"),
        BettorPick("Arsenal - Manchester City", "Manchester City", 2.62, 180.0, "cityzen", False, "Soccer"),
    ]
    hr = [
        BettorPick("Liverpool - Chelsea", "Liverpool", 1.78, 5000.0, "highroller1", True, "Soccer"),
        BettorPick("Arsenal - Manchester City", "Over 2.5", 1.78, 3200.0, "hr_goals", True, "Soccer"),
    ]
    return live, hr


def _fixture_to_dict(f: StakeFixture) -> dict:
    return {
        "id": f.id, "name": f.name, "home_team": f.home_team, "away_team": f.away_team,
        "sport": f.sport, "league": f.league, "status": f.status,
        "kickoff": f.kickoff.isoformat() if f.kickoff else None,
        "total_bet_value": f.total_bet_value, "total_bet_count": f.total_bet_count,
        "total_user_count": f.total_user_count,
        "markets": [{
            "id": getattr(m, "id", None) or m.name,
            "name": m.name, "group": m.group, "line": m.line,
            "outcomes": [{"id": o.id, "name": o.name, "odds": o.odds} for o in m.outcomes],
        } for m in f.markets],
    }


def _fixture_from_dict(d: dict) -> StakeFixture:
    kickoff = None
    if d.get("kickoff"):
        kickoff = datetime.fromisoformat(d["kickoff"].replace("Z", "+00:00"))
    markets = [
        StakeMarket(
            id=m.get("id") or m["name"],
            name=m["name"], group=m["group"],
            line=m.get("line"),
            outcomes=[StakeOutcome(id=o["id"], name=o["name"], odds=o["odds"]) for o in m["outcomes"]],
        )
        for m in d.get("markets", [])
    ]
    return StakeFixture(
        id=d["id"], name=d["name"], home_team=d["home_team"], away_team=d["away_team"],
        sport=d["sport"], league=d["league"], status=d.get("status", "active"),
        kickoff=kickoff, markets=markets,
        total_bet_value=d.get("total_bet_value", 0),
        total_bet_count=d.get("total_bet_count", 0),
        total_user_count=d.get("total_user_count", 0),
    )


def _pick_to_dict(p: BettorPick) -> dict:
    return {
        "fixture_name": p.fixture_name, "outcome_name": p.outcome_name,
        "odds": p.odds, "amount_usd": p.amount_usd, "user_name": p.user_name,
        "is_highroller": p.is_highroller, "sport": p.sport,
    }


def _pick_from_dict(d: dict) -> BettorPick:
    return BettorPick(**d)
