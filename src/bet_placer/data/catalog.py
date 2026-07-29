"""Sport catalog for navigation — Odds API keys + product categories."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SportInfo:
    key: str
    name: str
    category: str
    featured: bool = False
    description: str = ""
    model: str = "generic"  # soccer | basketball | cricket | generic


# Curated navigation — keys match The Odds API sport_key values
SPORT_CATALOG: list[SportInfo] = [
    SportInfo(
        "soccer_all", "Soccer", "soccer", True,
        "All live soccer boards from ESPN", model="soccer",
    ),
    SportInfo(
        "soccer_epl", "Premier League", "soccer", True,
        "English top flight", model="soccer",
    ),
    SportInfo(
        "soccer_uefa_champs_league", "Champions League", "soccer", True,
        "UCL", model="soccer",
    ),
    SportInfo(
        "soccer_spain_la_liga", "La Liga", "soccer", True,
        "Spanish top flight", model="soccer",
    ),
    SportInfo(
        "soccer_germany_bundesliga", "Bundesliga", "soccer", False,
        "German top flight", model="soccer",
    ),
    SportInfo(
        "soccer_italy_serie_a", "Serie A", "soccer", False,
        "Italian top flight", model="soccer",
    ),
    SportInfo(
        "soccer_usa_mls", "MLS", "soccer", False,
        "US Major League Soccer", model="soccer",
    ),
    SportInfo(
        "soccer_fifa_world_cup", "World Cup", "soccer", True,
        "Tournament fixtures with deep slips", model="soccer",
    ),
    SportInfo(
        "basketball_all", "Basketball", "basketball", True,
        "NBA + WNBA + NCAA boards", model="basketball",
    ),
    SportInfo(
        "basketball_nba", "NBA", "basketball", True,
        "NBA scoreboard", model="basketball",
    ),
    SportInfo(
        "basketball_wnba", "WNBA", "basketball", False,
        "WNBA scoreboard", model="basketball",
    ),
    SportInfo(
        "basketball_ncaab", "NCAA Basketball", "basketball", False,
        "College basketball", model="basketball",
    ),
    SportInfo(
        "basketball_fiba", "FIBA / International", "basketball", False,
        "FIBA and national-team basketball", model="basketball",
    ),
    SportInfo(
        "basketball_nbl", "NBL", "basketball", False,
        "Australian NBL", model="basketball",
    ),
    SportInfo(
        "cricket_all", "Cricket", "cricket", True,
        "All live cricket boards from ESPN", model="cricket",
    ),
    SportInfo(
        "cricket_icc_world_cup", "Cricket World Cup", "cricket", False,
        "ICC tournaments", model="cricket",
    ),
]

CATEGORIES = [
    {"id": "featured", "name": "Featured"},
    {"id": "soccer", "name": "Soccer"},
    {"id": "basketball", "name": "Basketball"},
    {"id": "cricket", "name": "Cricket"},
]


def get_sport(key: str) -> SportInfo | None:
    return next((s for s in SPORT_CATALOG if s.key == key), None)


def list_sports(category: str | None = None, featured_only: bool = False) -> list[SportInfo]:
    sports = SPORT_CATALOG
    if featured_only:
        sports = [s for s in sports if s.featured]
    if category and category != "featured":
        sports = [s for s in sports if s.category == category]
    return sports
