from __future__ import annotations

from abc import ABC, abstractmethod

from bet_placer.models.types import Match


class BaseCollector(ABC):
    @abstractmethod
    def fetch_matches(self, league_id: str | None = None, date: str | None = None) -> list[Match]:
        pass


class DemoCollector(BaseCollector):
    def fetch_matches(self, league_id: str | None = None, date: str | None = None) -> list[Match]:
        from bet_placer.data.demo import get_demo_matches

        return get_demo_matches()


class APIFootballCollector(BaseCollector):
    """Collector for API-Football. Requires API_FOOTBALL_KEY in .env."""

    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_matches(self, league_id: str | None = None, date: str | None = None) -> list[Match]:
        if not self.api_key:
            raise ValueError("API_FOOTBALL_KEY not configured")
        # Extension point: wire to /fixtures, /teams/statistics, /injuries, etc.
        raise NotImplementedError("Live API-Football integration — add API key and implement endpoints")


class OddsAPICollector:
    """Collector for The Odds API. Requires ODDS_API_KEY in .env."""

    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_odds(self, sport: str = "soccer_epl") -> list[dict]:
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not configured")
        raise NotImplementedError("Live Odds API integration — add API key and implement endpoints")
