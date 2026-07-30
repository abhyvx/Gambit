"""The Odds API client — multi-sport odds with aggressive disk cache.

Free quotas are tiny (~100–500 / month). Default path:
  • serve from disk cache (hours) without spending a credit
  • only hit the network when cache miss / force=True / expired
Boards should prefer ESPN + Stake + model; Odds API is a sparse enricher.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from bet_placer.config import data_path, get_settings
from bet_placer.data.catalog import SPORT_CATALOG
from bet_placer.markets.odds import decimal_to_implied
from bet_placer.models.enums import MarketType
from bet_placer.models.types import LeagueProfile, MarketOdds, Match, TacticalProfile, TeamStats

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
CACHE_DIR = data_path("odds_api_cache")
# ponytail: 6h disk TTL — upgrade to shorter only when credits are plentiful
DEFAULT_TTL_S = 6 * 3600

# League-average priors — models use these, NOT bookmaker odds
LEAGUE_PRIORS: dict[str, dict] = {
    "soccer": {"avg_goals": 2.65, "home_xg": 1.45, "away_xg": 1.20, "home_adv": 0.11},
    "basketball": {"avg_goals": 2.65, "home_xg": 1.4, "away_xg": 1.3, "home_adv": 0.04},
    "cricket": {"avg_goals": 2.65, "home_xg": 1.35, "away_xg": 1.3, "home_adv": 0.02},
    "americanfootball": {"avg_goals": 44, "home_xg": 23, "away_xg": 21, "home_adv": 0.03},
    "baseball": {"avg_goals": 8.5, "home_xg": 4.5, "away_xg": 4.0, "home_adv": 0.04},
    "default": {"avg_goals": 2.5, "home_xg": 1.3, "away_xg": 1.2, "home_adv": 0.08},
}


def _cache_path(sport_key: str, markets: str, regions: str) -> Path:
    dig = hashlib.sha1(f"{sport_key}|{markets}|{regions}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{sport_key}_{dig}.json"


class OddsAPIClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_settings().odds_api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "BetPlacer/0.2"
        self.last_remaining: int | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def list_sports(self) -> list[dict]:
        if not self.is_configured:
            return [{"key": s.key, "title": s.name, "active": True} for s in SPORT_CATALOG]
        # Cache sports list 24h — cheap but still a credit on some plans
        path = CACHE_DIR / "sports_list.json"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if path.exists() and time.time() - path.stat().st_mtime < 24 * 3600:
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        r = self.session.get(f"{BASE_URL}/sports", params={"apiKey": self.api_key}, timeout=15)
        r.raise_for_status()
        data = r.json()
        try:
            path.write_text(json.dumps(data))
        except Exception:
            pass
        return data

    def fetch_odds(
        self,
        sport_key: str,
        markets: str = "h2h,spreads,totals",
        regions: str = "uk,eu,us",
        *,
        force: bool = False,
        ttl_s: float = DEFAULT_TTL_S,
    ) -> list[dict]:
        """Return odds events.

        force=False (default): disk cache ONLY — never spends a credit on miss.
        force=True: network refresh (use sparingly; logs remaining quota).
        """
        if not self.is_configured:
            from bet_placer.data.demo_events import get_demo_events
            return get_demo_events(sport_key)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(sport_key, markets, regions)
        now = time.time()
        if path.exists() and now - path.stat().st_mtime < ttl_s:
            try:
                blob = json.loads(path.read_text())
                events = blob.get("events") if isinstance(blob, dict) else blob
                if isinstance(events, list):
                    logger.debug("Odds API cache hit %s (%d events)", sport_key, len(events))
                    return events
            except Exception:
                pass

        if not force:
            # ponytail: protect the free quota — board path must not network on cold cache
            return []

        # Hard stop when credits are nearly gone (user budget ~100 left)
        if self.last_remaining is not None and self.last_remaining < 15:
            logger.warning(
                "Odds API force blocked — remaining=%s (floor 15)", self.last_remaining,
            )
            return []

        r = self.session.get(
            f"{BASE_URL}/sports/{sport_key}/odds",
            params={
                "apiKey": self.api_key,
                "regions": regions,
                "markets": markets,
                "oddsFormat": "decimal",
            },
            timeout=20,
        )
        r.raise_for_status()
        try:
            rem = r.headers.get("x-requests-remaining")
            used = r.headers.get("x-requests-used")
            if rem is not None:
                self.last_remaining = int(rem)
            logger.info(
                "Odds API credit spend sport=%s remaining=%s used=%s",
                sport_key, rem, used,
            )
        except Exception:
            pass
        data = r.json()
        try:
            path.write_text(json.dumps({
                "ts": now,
                "sport_key": sport_key,
                "markets": markets,
                "events": data,
            }))
        except Exception:
            pass
        return data if isinstance(data, list) else []


def event_to_match(event: dict, sport_key: str) -> Match:
    """Convert Odds API event to Match. Stats from league priors — independent of odds."""
    home = event["home_team"]
    away = event["away_team"]
    sport_cat = sport_key.split("_")[0] if "_" in sport_key else "soccer"
    priors = LEAGUE_PRIORS.get(sport_cat, LEAGUE_PRIORS["default"])

    home_stats = TeamStats(
        name=home,
        goals_scored=priors["home_xg"],
        goals_conceded=priors["away_xg"],
        xg=priors["home_xg"],
        xga=priors["away_xg"],
    )
    away_stats = TeamStats(
        name=away,
        goals_scored=priors["away_xg"],
        goals_conceded=priors["home_xg"],
        xg=priors["away_xg"],
        xga=priors["home_xg"],
    )

    kickoff = datetime.now(timezone.utc)
    if ct := event.get("commence_time"):
        kickoff = datetime.fromisoformat(ct.replace("Z", "+00:00"))

    market_odds = _parse_bookmaker_odds(event, home, away, sport_cat)
    league_name = event.get("sport_title") or sport_key.replace("_", " ").title()

    return Match(
        id=str(event.get("id") or f"{home}-{away}"),
        home_team=home,
        away_team=away,
        league=league_name,
        kickoff=kickoff,
        home_stats=home_stats,
        away_stats=away_stats,
        home_tactics=TacticalProfile(),
        away_tactics=TacticalProfile(),
        league_profile=LeagueProfile(name=league_name),
        market_odds=market_odds,
        sentiment_score_home=0.0,
        sentiment_score_away=0.0,
        sport_key=sport_key,
    )


def _parse_bookmaker_odds(event: dict, home: str, away: str, sport_cat: str) -> list[MarketOdds]:
    """Best price across bookmakers for h2h / spreads / totals."""
    best: dict[tuple, dict[str, Any]] = {}
    for bm in event.get("bookmakers") or []:
        for mkt in bm.get("markets") or []:
            key = mkt.get("key")
            for o in mkt.get("outcomes") or []:
                name = (o.get("name") or "").strip()
                price = o.get("price")
                if not price or float(price) <= 1.01:
                    continue
                line = o.get("point")
                if key == "h2h":
                    if name == home:
                        sel = "home"
                    elif name == away:
                        sel = "away"
                    elif name.lower() == "draw":
                        sel = "draw"
                    else:
                        continue
                    mtype = MarketType.MATCH_WINNER
                elif key in ("spreads", "alternate_spreads"):
                    if name == home:
                        sel = "home"
                    elif name == away:
                        sel = "away"
                    else:
                        continue
                    mtype = MarketType.ASIAN_HANDICAP
                elif key in ("totals", "alternate_totals"):
                    sel = "over" if name.lower().startswith("over") else "under"
                    mtype = MarketType.OVER_UNDER_GOALS
                else:
                    continue
                slot = (mtype, sel, line)
                cur = best.get(slot)
                if cur is None or float(price) > float(cur["price"]):
                    best[slot] = {"price": float(price), "book": bm.get("title")}
    out: list[MarketOdds] = []
    for (mtype, sel, line), info in best.items():
        price = float(info["price"])
        out.append(MarketOdds(
            market=mtype, selection=sel, line=line,
            best_odds=price, avg_odds=price,
            implied_probability=decimal_to_implied(price),
            bookmaker_count=1,
        ))
    return out
