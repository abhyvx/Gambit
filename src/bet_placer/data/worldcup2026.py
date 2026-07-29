"""World Cup 2026 — LIVE fixtures from ESPN (scores, status, real odds).

No fake MD1 results. No hardcoded scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from bet_placer.data.demo_events import _make_event
from bet_placer.data.espn_worldcup import LiveWCMatch, fetch_live_worldcup


@dataclass
class WCMatch:
    id: str
    group: str
    matchday: int
    home: str
    away: str
    home_odds: float
    draw_odds: float
    away_odds: float
    stage: str = ""
    is_knockout: bool = False
    over_25: float = 1.85
    under_25: float = 1.95
    btts_yes: float = 1.75
    btts_no: float = 2.05
    status: str = "upcoming"
    home_score: int | None = None
    away_score: int | None = None
    kickoff: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    home_morale: float = 5.0
    away_morale: float = 5.0
    home_must_win: bool = False
    away_must_win: bool = False
    public_sentiment_home: float = 0.0
    narrative: str = ""
    espn_id: str = ""
    status_detail: str = ""
    odds_source: str = "espn_draftkings"
    data_source: str = "espn_live"
    home_logo: str | None = None
    away_logo: str | None = None


def _live_to_wc(m: LiveWCMatch) -> WCMatch:
    return WCMatch(
        id=m.id, group=m.group, matchday=m.matchday,
        stage=m.stage, is_knockout=m.is_knockout,
        home=m.home, away=m.away,
        home_odds=m.home_odds, draw_odds=m.draw_odds, away_odds=m.away_odds,
        over_25=m.over_25, under_25=m.under_25,
        btts_yes=m.btts_yes, btts_no=m.btts_no,
        status=m.status, home_score=m.home_score, away_score=m.away_score,
        kickoff=m.kickoff, home_morale=m.home_morale, away_morale=m.away_morale,
        home_must_win=m.home_must_win, away_must_win=m.away_must_win,
        public_sentiment_home=m.public_sentiment_home, narrative=m.narrative,
        espn_id=m.espn_id, status_detail=m.status_detail,
        odds_source=m.odds_source, data_source=m.data_source,
        home_logo=m.home_logo, away_logo=m.away_logo,
    )


def get_groups() -> dict[str, list[str]]:
    _, groups = fetch_live_worldcup()
    return groups


# Lazy-loaded — call get_groups() for live ESPN groups
def GROUPS() -> dict[str, list[str]]:
    return get_groups()


def get_all_group_matches(force_refresh: bool = False) -> list[WCMatch]:
    """All tournament fixtures — group stage and knockouts from ESPN."""
    live, _ = fetch_live_worldcup(force=force_refresh)
    return [_live_to_wc(m) for m in live]


def get_all_matches(force_refresh: bool = False) -> list[WCMatch]:
    return get_all_group_matches(force_refresh=force_refresh)


def get_current_matchday_matches() -> list[WCMatch]:
    all_m = get_all_group_matches()
    md = get_current_matchday()
    return [m for m in all_m if m.matchday == md and m.status in ("upcoming", "live")]


def get_group_standings(group: str, matches: list[WCMatch] | None = None) -> list[dict]:
    matches = matches or get_all_group_matches()
    teams = get_groups().get(group, [])
    table = {t: {"team": t, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0} for t in teams}
    for m in matches:
        if m.group != group or m.status != "completed":
            continue
        if m.home_score is None or m.away_score is None:
            continue
        hs, aws = m.home_score, m.away_score
        for team, gf, ga, is_home in [
            (m.home, hs, aws, True), (m.away, aws, hs, False),
        ]:
            if team not in table:
                continue
            table[team]["played"] += 1
            table[team]["gf"] += gf
            table[team]["ga"] += ga
            if hs == aws:
                table[team]["d"] += 1
                table[team]["pts"] += 1
            elif (is_home and hs > aws) or (not is_home and aws > hs):
                table[team]["w"] += 1
                table[team]["pts"] += 3
            else:
                table[team]["l"] += 1
    return sorted(table.values(), key=lambda x: (-x["pts"], -(x["gf"] - x["ga"]), -x["gf"]))


def get_current_matchday(matches: list[WCMatch] | None = None) -> int:
    from bet_placer.data.wc_stages import STAGE_GROUP_MD3, is_displayable_fixture

    matches = matches or get_all_group_matches()
    playable = [m for m in matches if is_displayable_fixture(m)]
    open_games = [m for m in playable if m.status in ("upcoming", "live")]
    if not open_games:
        played = [m.matchday for m in playable if m.status == "completed"]
        return max(played) if played else STAGE_GROUP_MD3
    return min(m.matchday for m in open_games)


def wc_match_to_event(m: WCMatch) -> dict:
    from bet_placer.data.wc_stages import is_knockout_matchday, stage_label

    now = datetime.now(timezone.utc)
    hours = max(1, int((m.kickoff - now).total_seconds() / 3600))
    comp = stage_label(m.matchday) if is_knockout_matchday(m.matchday) else f"WC Group {m.group}"
    return _make_event(
        m.id, comp, "soccer_fifa_world_cup",
        m.home, m.away, m.home_odds, m.draw_odds, m.away_odds,
        m.over_25, m.under_25, hours_ahead=hours,
    )
