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
