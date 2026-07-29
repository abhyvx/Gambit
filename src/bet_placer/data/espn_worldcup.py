"""Live World Cup 2026 data from ESPN — no API key required.

Scores, status (live/FT/scheduled), groups, and book odds (DraftKings via ESPN).
Stake.com is geo-blocked; these are real live payouts from a major book.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings"

_CACHE: dict[str, Any] = {"ts": 0.0, "matches": [], "groups": {}, "team_group": {}}
_CACHE_TTL = 45  # seconds — live scores refresh often enough, navigation stays snappy

# ESPN name → our canonical name
TEAM_ALIASES: dict[str, str] = {
    "United States": "USA",
    "Türkiye": "Turkey",
    "Czechia": "Czech Republic",
    "Congo DR": "DR Congo",
    "Bosnia-Herzegovina": "Bosnia",
    "Ivory Coast": "Ivory Coast",
}


@dataclass
class LiveWCMatch:
    id: str
    espn_id: str
    group: str
    matchday: int
    home: str
    away: str
    home_odds: float
    draw_odds: float
    away_odds: float
    stage: str = ""
    is_knockout: bool = False
    over_25: float = 1.90
    under_25: float = 1.90
    btts_yes: float = 1.80
    btts_no: float = 1.95
    status: str = "upcoming"
    home_score: int | None = None
    away_score: int | None = None
    kickoff: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status_detail: str = ""
    home_morale: float = 5.0
    away_morale: float = 5.0
    home_must_win: bool = False
    away_must_win: bool = False
    public_sentiment_home: float = 0.0
    narrative: str = ""
    odds_source: str = "espn_draftkings"
    data_source: str = "espn_live"
    home_logo: str | None = None
    away_logo: str | None = None


def fetch_live_worldcup(force: bool = False) -> tuple[list[LiveWCMatch], dict[str, list[str]]]:
    """Return all WC fixtures with live scores. Cached 45s."""
    now = time.time()
    if not force and _CACHE["matches"] and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["matches"], _CACHE["groups"]

    session = requests.Session()
    session.headers["User-Agent"] = "BetPlacer/0.3"

    team_group, groups = _fetch_standings(session)
    raw_events = _fetch_all_events(session)
    odds_map = _fetch_odds_batch(session, raw_events)

    # Build fixtures
    fixtures: list[dict] = []
    for ev in raw_events:
        parsed = _parse_event(ev, team_group)
        if parsed:
            fixtures.append(parsed)

    # Group stage only: 6 games per group → MD1/2/3 with 2 games each.
    # Knockout matchday is set during parse from name or kickoff date.
    by_group: dict[str, list[dict]] = {}
    for f in fixtures:
        if f.get("is_knockout"):
            continue
        by_group.setdefault(f["group"], []).append(f)
    for group, games in by_group.items():
        games.sort(key=lambda g: g["kickoff"])
        for i, g in enumerate(games):
            g["matchday"] = min(3, i // 2 + 1)

    matches: list[LiveWCMatch] = []
    for f in fixtures:
        oid = f["espn_id"]
        odds = odds_map.get(oid, {})
        grp = f["group"].replace("Group ", "")
        matches.append(LiveWCMatch(
            id=f"espn-{oid}",
            espn_id=oid,
            group=grp,
            matchday=f["matchday"],
            stage=f.get("stage") or (grp if f.get("is_knockout") else ""),
            is_knockout=bool(f.get("is_knockout")),
            home=f["home"],
            away=f["away"],
            home_odds=odds.get("home", 2.0),
            draw_odds=odds.get("draw", 3.3),
            away_odds=odds.get("away", 3.5),
            over_25=odds.get("over_25", 1.90),
            under_25=odds.get("under_25", 1.90),
            status=f["status"],
            home_score=f["home_score"],
            away_score=f["away_score"],
            kickoff=f["kickoff"],
            status_detail=f["status_detail"],
            home_logo=f.get("home_logo"),
            away_logo=f.get("away_logo"),
        ))

    _apply_context(matches, groups)
    matches.sort(key=lambda m: m.kickoff)

    _CACHE.update({"ts": now, "matches": matches, "groups": groups, "team_group": team_group})
    return matches, groups


def _fetch_standings(session: requests.Session) -> tuple[dict[str, str], dict[str, list[str]]]:
    r = session.get(ESPN_STANDINGS, timeout=15)
    r.raise_for_status()
    data = r.json()
    team_group: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    for child in data.get("children", []):
        gname = child.get("abbreviation", child.get("name", ""))
        letter = gname.replace("Group ", "").strip()
        teams = []
        for entry in child.get("standings", {}).get("entries", []):
            raw = entry.get("team", {}).get("displayName", "")
            team = _norm_team(raw)
            teams.append(team)
            team_group[team] = letter
            team_group[raw] = letter
        groups[letter] = teams
    return team_group, groups


def _fetch_all_events(session: requests.Session) -> list[dict]:
    """Full tournament + today's board merged for freshest status."""
    r = session.get(
        ESPN_SCOREBOARD,
        params={"dates": "20260611-20260731", "limit": 200},
        timeout=20,
    )
    r.raise_for_status()
    events = {str(e["id"]): e for e in r.json().get("events", [])}

    # Refresh in-play / today with default scoreboard (fresher)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        r2 = session.get(ESPN_SCOREBOARD, params={"dates": today, "limit": 50}, timeout=10)
        r2.raise_for_status()
        for e in r2.json().get("events", []):
            events[str(e["id"])] = e
    except Exception:
        pass

    try:
        r3 = session.get(ESPN_SCOREBOARD, params={"limit": 30}, timeout=10)
        r3.raise_for_status()
        for e in r3.json().get("events", []):
            events[str(e["id"])] = e
    except Exception:
        pass

    return list(events.values())


def _fetch_odds_batch(session: requests.Session, events: list[dict]) -> dict[str, dict]:
    """Pull DraftKings odds from ESPN summary for upcoming/live games.

    These per-event summary calls used to run sequentially (25 × ~0.6s ≈ 15s,
    the single biggest cause of slow page loads). We fan them out across a small
    thread pool so the whole batch finishes in ~1-2s instead.
    """
    from concurrent.futures import ThreadPoolExecutor

    odds_map: dict[str, dict] = {}
    need_odds = []
    for ev in events:
        st = ev.get("status", {}).get("type", {}).get("name", "")
        if st in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_HALFTIME"):
            need_odds.append(ev["id"])

    def _one(eid: str) -> tuple[str, dict | None]:
        try:
            r = session.get(ESPN_SUMMARY, params={"event": eid}, timeout=8)
            r.raise_for_status()
            return eid, _parse_pickcenter(r.json())
        except Exception:
            return eid, None

    # Cap requests — prioritize today/tomorrow — and run them concurrently.
    targets = need_odds[:25]
    if not targets:
        return odds_map
    with ThreadPoolExecutor(max_workers=10) as pool:
        for eid, parsed in pool.map(_one, targets):
            if parsed:
                odds_map[eid] = parsed
    return odds_map


def _parse_pickcenter(summary: dict) -> dict[str, float] | None:
    pick = (summary.get("pickcenter") or [None])[0]
    if not pick:
        odds_list = summary.get("odds") or []
        pick = odds_list[0] if odds_list else None
    if not pick:
        return None

    home_ml = pick.get("homeTeamOdds", {}).get("moneyLine")
    away_ml = pick.get("awayTeamOdds", {}).get("moneyLine")
    draw_ml = (pick.get("drawOdds") or {}).get("moneyLine")

    result: dict[str, float] = {}
    if home_ml is not None:
        result["home"] = round(_american_to_decimal(home_ml), 2)
    if away_ml is not None:
        result["away"] = round(_american_to_decimal(away_ml), 2)
    if draw_ml is not None:
        result["draw"] = round(_american_to_decimal(draw_ml), 2)

    over_odds = pick.get("overOdds")
    under_odds = pick.get("underOdds")
    if over_odds is not None:
        result["over_25"] = round(_american_to_decimal(over_odds), 2)
    if under_odds is not None:
        result["under_25"] = round(_american_to_decimal(under_odds), 2)

    return result if result else None


def _parse_event(ev: dict, team_group: dict[str, str]) -> dict | None:
    from bet_placer.data.wc_stages import (
        infer_stage_from_placeholder_teams,
        is_bracket_placeholder,
        stage_from_espn_event,
        stage_from_espn_type,
    )

    comp = (ev.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
    home = _norm_team(home_c.get("team", {}).get("displayName", ""))
    away = _norm_team(away_c.get("team", {}).get("displayName", ""))

    kickoff = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
    event_name = ev.get("name", "") or f"{away} at {home}"

    season_type = (ev.get("season") or {}).get("type")
    typed = stage_from_espn_type(season_type)
    if typed is not None:
        matchday, stage_code, is_knockout = typed
    else:
        matchday, stage_code, is_knockout = stage_from_espn_event(event_name, kickoff)

    placeholder_stage = infer_stage_from_placeholder_teams(home, away, kickoff)
    if is_knockout and is_bracket_placeholder(home, away) and placeholder_stage is not None:
        matchday, stage_code = placeholder_stage

    if is_knockout:
        group = f"Group {stage_code}"
    else:
        group = team_group.get(home) or team_group.get(away) or "?"
        if group == "?":
            return None
        group = f"Group {group}"

    st_type = ev.get("status", {}).get("type", {})
    st_name = st_type.get("name", "")
    st_desc = st_type.get("description", "")
    st_completed = st_type.get("completed", False)
    status = _map_status(st_name, st_desc, st_completed)

    def _score(c: dict) -> int | None:
        s = c.get("score")
        if s is None or s == "":
            return None
        try:
            return int(s)
        except (TypeError, ValueError):
            return None

    hs, aws = _score(home_c), _score(away_c)
    if status == "completed" and hs is not None and aws is not None:
        pass
    elif status == "live":
        hs = hs or 0
        aws = aws or 0

    ht = home_c.get("team") or {}
    at = away_c.get("team") or {}
    return {
        "espn_id": str(ev["id"]),
        "home": home,
        "away": away,
        "group": group,
        "status": status,
        "status_detail": st_desc,
        "home_score": hs,
        "away_score": aws,
        "kickoff": kickoff,
        "matchday": matchday if is_knockout else 1,
        "stage": stage_code if is_knockout else "",
        "is_knockout": is_knockout,
        "event_name": event_name,
        "home_logo": ht.get("logo"),
        "away_logo": at.get("logo"),
    }


def _map_status(espn_name: str, description: str = "", completed: bool = False) -> str:
    if completed or espn_name in ("STATUS_FINAL", "STATUS_FULL_TIME"):
        return "completed"
    if description in ("Full Time", "Final", "FT"):
        return "completed"
    if espn_name in (
        "STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_END_PERIOD",
        "STATUS_FIRST_HALF", "STATUS_SECOND_HALF",
    ) or description in ("First Half", "Second Half", "Halftime", "In Progress"):
        return "live"
    return "upcoming"


def _norm_team(name: str) -> str:
    return TEAM_ALIASES.get(name, name)


def _american_to_decimal(american: float | int | str) -> float:
    a = float(american)
    if a >= 0:
        return 1 + a / 100
    return 1 + 100 / abs(a)


def _apply_context(matches: list[LiveWCMatch], groups: dict[str, list[str]]) -> None:
    """Morale/must-win from REAL standings — not fake MD1 dict."""
    from bet_placer.data.team_ratings import get_team_rating

    # Points from completed games only
    pts: dict[str, int] = {t: 0 for teams in groups.values() for t in teams}
    played: dict[str, int] = {t: 0 for teams in groups.values() for t in teams}
    for m in matches:
        if m.status != "completed" or m.home_score is None:
            continue
        for team, gf, ga in [(m.home, m.home_score, m.away_score), (m.away, m.away_score, m.home_score)]:
            if team not in pts:
                continue
            played[team] += 1
            if m.home_score == m.away_score:
                pts[team] += 1
            elif gf > ga:
                pts[team] += 3

    for m in matches:
        if m.status != "upcoming" and m.status != "live":
            continue
        hp, ap = pts.get(m.home, 0), pts.get(m.away, 0)
        narratives = []

        if m.status == "live":
            narratives.append(f"🔴 LIVE — {m.status_detail}")

        if hp == 0 and played.get(m.home, 0) > 0:
            m.home_must_win = True
            m.home_morale = 4.0
            narratives.append(f"{m.home} need points — MD1 didn't go well")
        elif hp >= 3:
            m.home_morale = 7.5
            narratives.append(f"{m.home} flying after winning")

        if ap == 0 and played.get(m.away, 0) > 0:
            m.away_must_win = True
            m.away_morale = 4.5
            narratives.append(f"{m.away} desperate for a result")
        elif ap >= 3:
            m.away_morale = 7.0
            narratives.append(f"{m.away} confident with 3 points")

        bigs = {"Argentina", "Brazil", "France", "England", "Germany", "Spain", "Portugal"}
        if m.home in bigs:
            m.public_sentiment_home = 0.2
            narratives.append(f"Fans and bettors love {m.home}")
        if m.away in bigs:
            m.public_sentiment_home = -0.1

        if get_team_rating(m.home) > get_team_rating(m.away) + 12:
            narratives.append(f"{m.home} are the stronger team on paper")
        elif get_team_rating(m.away) > get_team_rating(m.home) + 12:
            narratives.append(f"{m.away} have more quality in the squad")

        m.narrative = ". ".join(narratives) if narratives else ""


def get_current_matchday(matches: list[LiveWCMatch] | None = None) -> int:
    """Which stage/matchday is active based on confirmed fixtures left to play."""
    from bet_placer.data.wc_stages import STAGE_GROUP_MD3, STAGE_MAX, is_displayable_fixture

    matches = matches or fetch_live_worldcup()[0]
    playable = [m for m in matches if is_displayable_fixture(m)]
    upcoming = [m for m in playable if m.status in ("upcoming", "live")]
    if not upcoming:
        played = [m.matchday for m in playable if m.status == "completed"]
        return max(played) if played else STAGE_GROUP_MD3
    return min(m.matchday for m in upcoming)


def knockout_counts(matches: list[LiveWCMatch] | None = None) -> dict[str, int]:
    """How many knockout fixtures ESPN currently lists per round."""
    from bet_placer.data.wc_stages import STAGE_SHORT

    matches = matches or fetch_live_worldcup()[0]
    counts: dict[str, int] = {}
    for m in matches:
        if not m.is_knockout:
            continue
        code = m.stage or STAGE_SHORT.get(m.matchday, "?")
        counts[code] = counts.get(code, 0) + 1
    return counts
