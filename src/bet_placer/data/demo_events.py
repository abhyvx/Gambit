"""Rich demo events when no API keys — includes World Cup 2026 fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def get_demo_events(sport_key: str) -> list[dict]:
    generators = {
        "soccer_fifa_world_cup": _world_cup_events,
        "soccer_epl": _epl_events,
        "basketball_nba": _nba_events,
        "americanfootball_nfl": _nfl_events,
        "baseball_mlb": _mlb_events,
    }
    gen = generators.get(sport_key, _generic_soccer_events)
    return gen()


def _world_cup_events() -> list[dict]:
    """FIFA World Cup 2026 — realistic demo odds from multiple bookmakers."""
    fixtures = [
        ("USA", "Mexico", 2.45, 3.30, 2.90),
        ("Brazil", "Argentina", 2.55, 3.20, 2.75),
        ("France", "Germany", 2.30, 3.40, 3.00),
        ("England", "Spain", 2.80, 3.25, 2.55),
        ("Portugal", "Netherlands", 2.60, 3.30, 2.70),
        ("Japan", "South Korea", 2.50, 3.15, 2.85),
    ]
    events = []
    for i, (home, away, h, d, a) in enumerate(fixtures):
        events.append(_make_event(
            f"wc-2026-{i+1}",
            "FIFA World Cup",
            "soccer_fifa_world_cup",
            home, away,
            h, d, a,
            over_25=1.82 if i % 2 == 0 else 1.95,
            under_25=2.00 if i % 2 == 0 else 1.88,
            hours_ahead=24 + i * 48,
        ))
    return events


def _epl_events() -> list[dict]:
    return [
        _make_event("epl-1", "EPL", "soccer_epl", "Liverpool", "Chelsea", 1.78, 4.00, 4.40, 1.72, 2.15, 12),
        _make_event("epl-2", "EPL", "soccer_epl", "Arsenal", "Man City", 2.65, 3.50, 2.62, 1.78, 2.05, 36),
    ]


def _nba_events() -> list[dict]:
    return [
        _make_event("nba-1", "NBA", "basketball_nba", "Lakers", "Celtics", 2.10, None, 1.75, None, None, 8, spread_line=4.5),
        _make_event("nba-2", "NBA", "basketball_nba", "Warriors", "Nuggets", 1.95, None, 1.90, None, None, 20, spread_line=3.5),
    ]


def _nfl_events() -> list[dict]:
    return [
        _make_event("nfl-1", "NFL", "americanfootball_nfl", "Chiefs", "Eagles", 1.85, None, 2.00, None, None, 48, spread_line=3.0),
    ]


def _mlb_events() -> list[dict]:
    return [
        _make_event("mlb-1", "MLB", "baseball_mlb", "Yankees", "Red Sox", 1.90, None, 1.95, None, None, 16, spread_line=1.5),
    ]


def _generic_soccer_events() -> list[dict]:
    return _epl_events()


def _make_event(
    eid: str,
    sport_title: str,
    sport_key: str,
    home: str,
    away: str,
    home_odds: float,
    draw_odds: float | None,
    away_odds: float,
    over_25: float | None = None,
    under_25: float | None = None,
    hours_ahead: int = 24,
    spread_line: float | None = None,
) -> dict:
    """Build Odds API-shaped event with multiple bookmakers for realistic aggregation."""
    commence = (NOW + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
    bookmakers = []

    # Simulate 5-8 bookmakers with slight odds variation
    bm_names = ["pinnacle", "betfair", "williamhill", "draftkings", "fanduel", "bet365", "stake"]
    for j, bm in enumerate(bm_names[:7]):
        jitter = 1 + (j - 3) * 0.015
        markets = [{
            "key": "h2h",
            "outcomes": [
                {"name": home, "price": round(home_odds * jitter, 2)},
                {"name": away, "price": round(away_odds * (2 - jitter), 2)},
            ],
        }]
        if draw_odds:
            markets[0]["outcomes"].insert(1, {"name": "Draw", "price": round(draw_odds * jitter, 2)})

        if over_25 and under_25:
            markets.append({
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": round(over_25 * jitter, 2), "point": 2.5},
                    {"name": "Under", "price": round(under_25 * (2 - jitter), 2), "point": 2.5},
                ],
            })

        bookmakers.append({"key": bm, "title": bm.title(), "markets": markets})

    return {
        "id": eid,
        "sport_key": sport_key,
        "sport_title": sport_title,
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": bookmakers,
    }
