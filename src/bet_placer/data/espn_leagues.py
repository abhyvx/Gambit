"""Live fixtures from ESPN scoreboards — no API key required.

Soccer/all is capped by ESPN (~500/window); we merge major-league boards +
extra date windows so the product board is close to “every match” in-window.
Cricket uses the ESPN header feed (logos included). Missing 1X2 on the
scoreboard is backfilled from the event summary endpoint (live/upcoming only).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bet_placer.config import data_path

# Odds API / product sport_key → ESPN path (or special handlers below)
ESPN_LEAGUES: dict[str, tuple[str, str]] = {
    "soccer_all": ("soccer", "all"),
    "soccer_epl": ("soccer", "eng.1"),
    "soccer_uefa_champs_league": ("soccer", "uefa.champions"),
    "soccer_spain_la_liga": ("soccer", "esp.1"),
    "soccer_germany_bundesliga": ("soccer", "ger.1"),
    "soccer_italy_serie_a": ("soccer", "ita.1"),
    "soccer_usa_mls": ("soccer", "usa.1"),
    "basketball_nba": ("basketball", "nba"),
    "basketball_wnba": ("basketball", "wnba"),
    "basketball_ncaab": ("basketball", "mens-college-basketball"),
    "basketball_ncaaw": ("basketball", "womens-college-basketball"),
    "basketball_fiba": ("basketball", "fiba"),
    "basketball_nbl": ("basketball", "nbl"),
    "basketball_all": ("basketball", "nba"),  # merged in fetch
}

# Fast first paint: core boards. Extras also run sync when core is thin.
_SOCCER_CORE: tuple[str, ...] = (
    "eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "usa.1",
    "uefa.champions", "uefa.europa", "uefa.europa.conf",
    "fifa.world", "fifa.friendly", "uefa.nations",
    "bra.1", "arg.1", "mex.1", "ned.1", "por.1",
)
_SOCCER_EXTRA: tuple[str, ...] = (
    "eng.2", "eng.3", "eng.4", "tur.1", "sco.1", "bel.1", "sui.1", "aut.1", "den.1", "gre.1",
    "jpn.1", "aus.1", "chi.1", "col.1", "uru.1", "rus.1", "pol.1", "swe.1", "nor.1",
    "fra.2", "esp.2", "ger.2", "ita.2", "ned.2",
    "uefa.europa.qual", "conmebol.libertadores", "conmebol.sudamericana",
    "uefa.euroq", "conmebol.america", "caf.nations", "afc.asian.cup",
    "fifa.worldq.uefa", "fifa.worldq.conmebol", "fifa.worldq.caf", "fifa.worldq.afc",
)

_LEAGUE_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "soccer_epl": ("premier league", "eng.1", "english premier"),
    # Exact-ish — never match "Women's Champions League"
    "soccer_uefa_champs_league": ("uefa champions league", "uefa.champions"),
    "soccer_spain_la_liga": ("laliga", "la liga", "spanish primera", "esp.1"),
    "soccer_germany_bundesliga": ("bundesliga", "ger.1"),
    "soccer_italy_serie_a": ("serie a", "ita.1"),
    "soccer_usa_mls": ("mls", "major league soccer", "usa.1"),
    "cricket_icc_world_cup": ("world cup", "icc", "mcwc", "champions trophy"),
}

_WOMEN_MARKERS = ("women", "women's", "womens", "feminine", "femenina")


def _is_womens_comp(title: str) -> bool:
    t = (title or "").lower()
    return any(m in t for m in _WOMEN_MARKERS)

_CACHE: dict[str, dict[str, Any]] = {}
_TTL = 180
_DISK_TTL = 3600  # serve disk boards up to 1h — Stake-style instant paint after restart
_DISK_PATH = data_path("espn_board_cache.json")
_SESSION: requests.Session | None = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers["User-Agent"] = "Gambit/1.0"
    return _SESSION


def _disk_get(cache_key: str) -> list[dict] | None:
    try:
        if not _DISK_PATH.exists():
            return None
        blob = json.loads(_DISK_PATH.read_text())
        row = (blob or {}).get(cache_key)
        if not row:
            return None
        if time.time() - float(row.get("ts") or 0) > _DISK_TTL:
            return None
        events = row.get("events")
        return events if isinstance(events, list) else None
    except Exception:
        return None


def _disk_put(cache_key: str, events: list[dict]) -> None:
    try:
        _DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
        blob: dict = {}
        if _DISK_PATH.exists():
            try:
                blob = json.loads(_DISK_PATH.read_text()) or {}
            except Exception:
                blob = {}
        blob[cache_key] = {"ts": time.time(), "events": events}
        # Keep file bounded — drop oldest if huge
        if len(blob) > 40:
            oldest = sorted(blob.items(), key=lambda kv: float((kv[1] or {}).get("ts") or 0))
            for k, _ in oldest[: len(blob) - 40]:
                blob.pop(k, None)
        _DISK_PATH.write_text(json.dumps(blob))
    except Exception:
        pass


def _cache_put(cache_key: str, events: list[dict]) -> None:
    _CACHE[cache_key] = {"ts": time.time(), "events": events}
    _disk_put(cache_key, events)


def espn_supports(sport_key: str) -> bool:
    if sport_key in ESPN_LEAGUES:
        return True
    if sport_key.startswith("cricket"):
        return True
    return False


def fetch_espn_events(sport_key: str, *, enrich: bool = False) -> list[dict]:
    """Return Odds-API-shaped events with logos and h2h odds when present.

    enrich=False (default) skips summary odds fan-out so boards load fast.
    """
    if not espn_supports(sport_key):
        return []
    now = time.time()
    # Cricket tabs share one scrape — filter after cache
    base_key = "cricket_all" if sport_key.startswith("cricket") else sport_key
    cache_key = f"{base_key}:{'e' if enrich else 'f'}"
    cached = _CACHE.get(cache_key)
    if cached and now - cached["ts"] < _TTL:
        events = cached["events"]
    else:
        disk = _disk_get(cache_key)
        if disk is not None:
            events = disk
            _CACHE[cache_key] = {"ts": now, "events": events}
        elif sport_key.startswith("cricket") or base_key == "cricket_all":
            events = _fetch_cricket("cricket_all")
            if enrich:
                _enrich_missing_odds(events)
            _ensure_fair_books(events)
            events.sort(key=lambda e: e.get("commence_time") or "")
            _cache_put(cache_key, events)
        elif sport_key == "basketball_all":
            events = _merge_boards([
                _fetch_scoreboard("basketball", "nba", "basketball_nba", "NBA"),
                _fetch_scoreboard("basketball", "wnba", "basketball_wnba", "WNBA"),
                _fetch_scoreboard(
                    "basketball", "mens-college-basketball", "basketball_ncaab", "NCAA M",
                ),
                _fetch_scoreboard(
                    "basketball", "womens-college-basketball", "basketball_ncaaw", "NCAA W",
                ),
                _fetch_scoreboard("basketball", "fiba", "basketball_fiba", "FIBA"),
                _fetch_scoreboard("basketball", "nbl", "basketball_nbl", "NBL"),
            ])
            if enrich:
                _enrich_missing_odds(events)
            _ensure_fair_books(events)
            events.sort(key=lambda e: e.get("commence_time") or "")
            _cache_put(cache_key, events)
        elif sport_key == "soccer_all":
            events = _fetch_soccer_all()
            if enrich:
                _enrich_missing_odds(events)
            events.sort(key=lambda e: e.get("commence_time") or "")
            _cache_put(cache_key, events)
        else:
            sport, league = ESPN_LEAGUES[sport_key]
            board = {
                "soccer_epl": "Premier League",
                "soccer_uefa_champs_league": "Champions League",
                "soccer_spain_la_liga": "La Liga",
                "soccer_germany_bundesliga": "Bundesliga",
                "soccer_italy_serie_a": "Serie A",
                "soccer_usa_mls": "MLS",
                "basketball_nba": "NBA",
                "basketball_wnba": "WNBA",
                "basketball_ncaab": "NCAA M",
                "basketball_ncaaw": "NCAA W",
                "basketball_fiba": "FIBA",
                "basketball_nbl": "NBL",
            }.get(sport_key, sport_key.replace("_", " ").title())
            # Cup boards: ESPN season calendars mix Women's comps into uefa.champions —
            # use a wide near-term window instead of Aug→May.
            cup = sport_key in {
                "soccer_uefa_champs_league",
            }
            season = sport_key.startswith("soccer_") and sport_key != "soccer_all" and not cup
            events = _fetch_scoreboard(
                sport, league, sport_key, board, season=season, wide=cup,
            )
            if sport_key.startswith("soccer_") and sport_key != "soccer_all":
                events = [
                    e for e in events
                    if not _is_womens_comp(e.get("sport_title") or "")
                ]
            if sport == "soccer" and len(events) < 40:
                events = _backfill_soccer_league(sport_key, events)
            if enrich:
                _enrich_missing_odds(events)
            events.sort(key=lambda e: e.get("commence_time") or "")
            _cache_put(cache_key, events)

    if sport_key.startswith("cricket") and sport_key != "cricket_all":
        return _filter_cricket_board(events, sport_key)
    return list(events)


def _merge_boards(boards: list[list[dict]]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for board in boards:
        for e in board:
            by_id[str(e["id"])] = e
    return list(by_id.values())


def _date_windows() -> list[str]:
    """ESPN truncates per window — stitch enough so mid/far fixtures aren't dropped."""
    today = date.today()
    windows = [
        (today - timedelta(days=3), today + timedelta(days=4)),
        (today + timedelta(days=5), today + timedelta(days=14)),
        (today + timedelta(days=15), today + timedelta(days=28)),
        (today + timedelta(days=29), today + timedelta(days=45)),
        (today - timedelta(days=10), today - timedelta(days=4)),
    ]
    out = []
    for a, b in windows:
        out.append(f"{a.strftime('%Y%m%d')}-{b.strftime('%Y%m%d')}")
    return out


def _fetch_soccer_all() -> list[dict]:
    by_id: dict[str, dict] = {}
    sess = _session()
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"

    def pull_all(dates: str | None) -> list[dict]:
        params: dict[str, Any] = {"limit": 500}
        if dates:
            params["dates"] = dates
        try:
            r = sess.get(url, params=params, timeout=18)
            r.raise_for_status()
            out = []
            for ev in (r.json() or {}).get("events") or []:
                parsed = _parse_event(ev, "soccer_all", "Soccer", "soccer")
                if parsed:
                    out.append(parsed)
            return out
        except Exception:
            return []

    def pull_league(lg: str) -> list[dict]:
        try:
            u = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard"
            today = date.today()
            dates = f"{(today - timedelta(2)).strftime('%Y%m%d')}-{(today + timedelta(35)).strftime('%Y%m%d')}"
            r = sess.get(u, params={"dates": dates, "limit": 200}, timeout=14)
            if not r.ok:
                return []
            data = r.json() or {}
            board = ((data.get("leagues") or [{}])[0].get("name")) or lg
            out = []
            for ev in data.get("events") or []:
                parsed = _parse_event(ev, "soccer_all", board, "soccer")
                if parsed:
                    out.append(parsed)
            return out
        except Exception:
            return []

    jobs = [None, *_date_windows()]  # None = default today board
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(pull_all, d) for d in jobs]
        futs += [pool.submit(pull_league, lg) for lg in _SOCCER_CORE]
        for fut in as_completed(futs):
            try:
                for e in fut.result() or []:
                    by_id[e["id"]] = e
            except Exception:
                continue
    # Sync extras when the core board is thin; otherwise fill in background
    if len(by_id) < 100:
        _pull_soccer_extra_into(by_id)
    else:
        _schedule_soccer_extra(by_id)
    return list(by_id.values())


_EXTRA_LOCK = None
_EXTRA_SCHEDULED = False


def _pull_soccer_extra_into(by_id: dict[str, dict]) -> None:
    """Merge secondary leagues into by_id (sync)."""
    sess = _session()
    today = date.today()
    dates = f"{(today - timedelta(2)).strftime('%Y%m%d')}-{(today + timedelta(35)).strftime('%Y%m%d')}"
    for lg in _SOCCER_EXTRA:
        try:
            u = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard"
            r = sess.get(u, params={"dates": dates, "limit": 200}, timeout=12)
            if not r.ok:
                continue
            data = r.json() or {}
            board = ((data.get("leagues") or [{}])[0].get("name")) or lg
            for ev in data.get("events") or []:
                parsed = _parse_event(ev, "soccer_all", board, "soccer")
                if parsed:
                    by_id[parsed["id"]] = parsed
        except Exception:
            continue


def _schedule_soccer_extra(seed: dict[str, dict]) -> None:
    """ponytail: one background merge of secondary leagues into soccer_all cache."""
    global _EXTRA_LOCK, _EXTRA_SCHEDULED
    import threading
    if _EXTRA_LOCK is None:
        _EXTRA_LOCK = threading.Lock()
    with _EXTRA_LOCK:
        if _EXTRA_SCHEDULED:
            return
        _EXTRA_SCHEDULED = True

    def _go() -> None:
        global _EXTRA_SCHEDULED
        try:
            by_id = dict(seed)
            _pull_soccer_extra_into(by_id)
            events = list(by_id.values())
            events.sort(key=lambda e: e.get("commence_time") or "")
            for suffix in ("f", "e"):
                _cache_put(f"soccer_all:{suffix}", events)
        finally:
            with _EXTRA_LOCK:
                _EXTRA_SCHEDULED = False

    threading.Thread(target=_go, daemon=True, name="soccer-extra").start()


def _basketball_date_windows() -> list[str | None]:
    """ESPN caps ~100/window — stitch deep past (boards to grade) + future schedule.

    Past windows are required: NBA offseason otherwise leaves only WNBA/FIBA scraps
    and board_n stays near zero.
    """
    today = date.today()
    chunks = [
        (-200, -151), (-150, -101), (-100, -61), (-60, -31), (-30, -11), (-10, -1),
        (0, 4), (5, 18), (19, 32), (33, 55), (56, 100),
    ]
    out: list[str | None] = []
    for a, b in chunks:
        start = today + timedelta(days=a)
        end = today + timedelta(days=b)
        out.append(f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}")
    out.append(None)
    return out


def _fetch_basketball_calendar_days(
    sport: str, league: str, sport_key: str, board_name: str,
) -> list[dict]:
    """College (and other) boards: ESPN returns 404 on date *ranges* — stitch single days."""
    sess = _session()
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
    by_id: dict[str, dict] = {}
    days: list[str | None] = [None]
    try:
        r = sess.get(url, timeout=20)
        if r.ok:
            data = r.json() or {}
            cal = ((data.get("leagues") or [{}])[0].get("calendar") or [])
            for raw in cal:
                try:
                    days.append(str(raw)[:10].replace("-", ""))
                except Exception:
                    continue
            for ev in data.get("events") or []:
                parsed = _parse_event(ev, sport_key, board_name, sport)
                if parsed:
                    by_id[str(parsed["id"])] = parsed
    except Exception:
        pass
    # Cap day pulls — full season ~140 days; every day is too slow on cold cache
    # Prefer denser months: take all unique days but parallelize
    uniq = []
    seen = set()
    for d in days:
        if d in seen:
            continue
        seen.add(d)
        uniq.append(d)

    def pull_day(day: str | None) -> list[dict]:
        try:
            params = {"dates": day, "limit": 200} if day else {"limit": 200}
            rr = sess.get(url, params=params, timeout=12)
            if not rr.ok:
                return []
            name = (((rr.json() or {}).get("leagues") or [{}])[0].get("name")) or board_name
            out = []
            for ev in (rr.json() or {}).get("events") or []:
                parsed = _parse_event(ev, sport_key, name, sport)
                if parsed:
                    out.append(parsed)
            return out
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(pull_day, d) for d in uniq]
        for fut in as_completed(futs):
            try:
                for e in fut.result() or []:
                    by_id[str(e["id"])] = e
            except Exception:
                continue
    return list(by_id.values())


def _fetch_scoreboard(
    sport: str,
    league: str,
    sport_key: str,
    board_name: str,
    *,
    season: bool = False,
    wide: bool = False,
) -> list[dict]:
    sess = _session()
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

    def pull(dates: str | None) -> list[dict]:
        params: dict[str, Any] = {"limit": 500 if season else 200}
        if dates:
            params["dates"] = dates
        try:
            r = sess.get(url, params=params, timeout=25 if season else 16)
            if not r.ok:
                return []
            data = r.json() or {}
        except Exception:
            return []
        name = ((data.get("leagues") or [{}])[0].get("name")) or board_name
        out = []
        for ev in data.get("events") or []:
            parsed = _parse_event(ev, sport_key, name, sport)
            if parsed:
                out.append(parsed)
        return out

    if sport == "basketball":
        # NCAA rejects date ranges (404) — calendar-day stitch like cricket
        if league in ("mens-college-basketball", "womens-college-basketball", "fiba"):
            return _fetch_basketball_calendar_days(sport, league, sport_key, board_name)
        by_id: dict[str, dict] = {}
        for window in _basketball_date_windows():
            for e in pull(window):
                by_id[str(e["id"])] = e
        return list(by_id.values())

    params_dates: str | None = None
    if sport == "soccer":
        today = date.today()
        if season:
            start = date(today.year if today.month >= 7 else today.year - 1, 8, 1)
            end = date(start.year + 1, 5, 31)
            params_dates = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
        elif wide:
            # Cups between seasons: look back 30d / ahead 120d
            params_dates = (
                f"{(today - timedelta(30)).strftime('%Y%m%d')}-"
                f"{(today + timedelta(120)).strftime('%Y%m%d')}"
            )
        else:
            params_dates = (
                f"{(today - timedelta(2)).strftime('%Y%m%d')}-"
                f"{(today + timedelta(35)).strftime('%Y%m%d')}"
            )
    # Always also pull the undated default board (recent finals / TBD kickoffs)
    by_id: dict[str, dict] = {}
    for e in pull(params_dates):
        by_id[str(e["id"])] = e
    for e in pull(None):
        by_id[str(e["id"])] = e
    return list(by_id.values())


def _backfill_soccer_league(sport_key: str, events: list[dict]) -> list[dict]:
    hints = _LEAGUE_NAME_HINTS.get(sport_key) or ()
    if not hints:
        return events
    pool = fetch_espn_events("soccer_all")
    seen = {e["id"] for e in events}
    for e in pool:
        title = f"{e.get('sport_title', '')}"
        blob = f"{title} {e.get('home_team', '')}".lower()
        if _is_womens_comp(title):
            continue
        if any(h in blob for h in hints) and e["id"] not in seen:
            events.append({**e, "sport_key": sport_key})
            seen.add(e["id"])
    return events


# Known ESPN cricket series IDs (fallback when header is thin)
_CRICKET_SERIES: tuple[tuple[str, str], ...] = (
    ("8048", "Indian Premier League"),
    ("8044", "Big Bash League"),
    ("8604", "ICC Men's T20 World Cup"),
    ("8052", "County Championship"),
    ("8204", "County Championship Div 2"),
    ("8335", "Royal London One-Day Cup"),
    ("19439", "ICC Men's Cricket World Cup League 2"),
    ("19943", "Lanka Premier League"),
    ("19601", "The Hundred Men"),
    ("21376", "The Hundred Women"),
    ("23077", "Global Super League"),
    ("24301", "India tour of Zimbabwe"),
    ("24546", "India U19 tour of Sri Lanka"),
    ("24509", "Pakistan Women tour of Sri Lanka"),
    ("24582", "South Africa Women U19 tour of Pakistan"),
    ("11083", "Ireland Inter-Provincial"),
    # Broader intl / franchise coverage
    ("8083", "Pakistan Super League"),
    ("8177", "Caribbean Premier League"),
    ("8179", "SA20"),
    ("8356", "Women's Big Bash League"),
    ("8527", "ICC Cricket World Cup"),
    ("8491", "Asia Cup"),
    ("19238", "ICC Champions Trophy"),
    ("23376", "Major League Cricket"),
)

_CRICKET_TOURNAMENT_HINTS = (
    "world cup", "champions trophy", "asia cup", "t20 world", "icc men's",
    "icc women's", "world cup league", "mcwc", "qualifier",
)

_CRICKET_LEAGUE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cricket_ipl", ("indian premier", "ipl")),
    ("cricket_bbl", ("big bash", "bbl")),
    ("cricket_hundred", ("the hundred", "hundred men", "hundred women")),
    ("cricket_psl", ("pakistan super", "psl")),
    ("cricket_cpl", ("caribbean premier", "cpl")),
)

_CRICKET_INTL_HINTS = (
    "tour of", "tour of", "test series", "odi series",
    "t20i", "tri-nation", "bilateral",
    "under-19", "women under",
)


def _is_nation_side(n: str) -> bool:
    s = (n or "").lower().strip()
    if not s or "(" in s:  # "London Spirit (Men)" etc.
        return False
    franchise = (
        "kings", "riders", "super", "warrior", "lightning", "spirit",
        "giant", "phoenix", "scorchers", "qalandars", "amazon", "unicorns",
        "nottingham", "warwick", "yorkshire", "surrey", "lancashire",
        "gallants", "jaffna", "galle", "mumbai", "chennai", "kolkata",
    )
    if any(f in s for f in franchise):
        return False
    countries = (
        "india", "australia", "england", "pakistan", "new zealand",
        "south africa", "west indies", "sri lanka", "bangladesh",
        "afghanistan", "ireland", "scotland", "zimbabwe", "netherlands",
        "nepal", "namibia", "oman", "uae", "united arab", "usa",
        "united states", "canada", "hong kong", "papua",
    )
    return any(s == c or s.startswith(c + " ") for c in countries)


def _is_intl_cricket(title: str, home: str, away: str) -> bool:
    blob = f"{title} {home} {away}".lower()
    if any(h in blob for h in _CRICKET_INTL_HINTS):
        return True
    return _is_nation_side(home) and _is_nation_side(away)


def _tag_cricket_event(title: str, home: str, away: str) -> tuple[str, str]:
    """Return (sport_key, board) for cricket taxonomy tabs."""
    blob = f"{title} {home} {away}".lower()
    for key, hints in _CRICKET_LEAGUE_HINTS:
        if any(h in blob for h in hints):
            return key, "league"
    if any(h in blob for h in _CRICKET_TOURNAMENT_HINTS):
        return "cricket_tournaments", "tournament"
    if _is_intl_cricket(title, home, away):
        return "cricket_international", "international"
    return "cricket_other", "other"


def _filter_cricket_board(events: list[dict], sport_key: str) -> list[dict]:
    if sport_key in ("cricket_icc_world_cup",):
        return [e for e in events if e.get("sport_key") == "cricket_tournaments"]
    if sport_key == "cricket_international":
        return [
            e for e in events
            if e.get("sport_key") in ("cricket_international", "cricket_tournaments")
        ]
    if sport_key == "cricket_domestic":
        # Franchise / county / other — anything that isn't intl / ICC cups
        return [
            e for e in events
            if e.get("sport_key") not in ("cricket_international", "cricket_tournaments")
        ]
    if sport_key.startswith("cricket_") and sport_key != "cricket_all":
        return [e for e in events if e.get("sport_key") == sport_key]
    return list(events)


def _fetch_cricket(sport_key: str) -> list[dict]:
    """Header + per-series scoreboards. ESPN cricket rejects date *ranges* (404);
    stitch single calendar days instead so intl fixtures stay visible."""
    sess = _session()
    by_id: dict[str, dict] = {}
    series: dict[str, str] = {lid: title for lid, title in _CRICKET_SERIES}

    try:
        r = sess.get(
            "https://site.web.api.espn.com/apis/v2/scoreboard/header",
            params={"sport": "cricket"},
            timeout=20,
        )
        r.raise_for_status()
        sports = (r.json() or {}).get("sports") or []
        cr = next((s for s in sports if (s.get("slug") or "") == "cricket"), None)
        if cr:
            for lg in cr.get("leagues") or []:
                lid = str(lg.get("id") or "").strip()
                league_name = lg.get("name") or lg.get("abbreviation") or "Cricket"
                if lid:
                    series[lid] = league_name
                for ev in lg.get("events") or []:
                    parsed = _parse_cricket_header_event(ev, league_name, sport_key)
                    if parsed:
                        by_id[parsed["id"]] = parsed
    except Exception:
        pass

    def pull_series(lid: str, title: str) -> list[dict]:
        url = f"https://site.api.espn.com/apis/site/v2/sports/cricket/{lid}/scoreboard"
        out: list[dict] = []
        try:
            r = sess.get(url, timeout=12)
            if not r.ok:
                return []
            data = r.json() or {}
        except Exception:
            return []
        board = ((data.get("leagues") or [{}])[0].get("name")) or title
        cal = ((data.get("leagues") or [{}])[0].get("calendar") or [])
        days: list[str | None] = [None]  # default board
        for raw in cal[:48]:
            try:
                days.append(str(raw)[:10].replace("-", ""))
            except Exception:
                continue
        seen_days = set()
        for day in days:
            if day in seen_days:
                continue
            seen_days.add(day)
            try:
                params = {"dates": day} if day else {}
                rr = sess.get(url, params=params, timeout=10) if day else r
                if day:
                    if not rr.ok:
                        continue
                    payload = rr.json() or {}
                else:
                    payload = data
                for ev in payload.get("events") or []:
                    parsed = _parse_event(ev, sport_key, board, "cricket")
                    if parsed:
                        out.append(parsed)
            except Exception:
                continue
        return out

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(pull_series, lid, title) for lid, title in series.items()]
        for fut in as_completed(futs):
            try:
                for e in fut.result() or []:
                    by_id[e["id"]] = e
            except Exception:
                continue

    events = list(by_id.values())
    for e in events:
        key, board = _tag_cricket_event(
            e.get("sport_title") or "",
            e.get("home_team") or "",
            e.get("away_team") or "",
        )
        e["board"] = board
        e["sport_key"] = key
    return events


def _parse_cricket_header_event(ev: dict, league_name: str, sport_key: str) -> dict | None:
    teams = ev.get("competitors") or []
    if len(teams) < 2:
        return None
    home = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
    away = next((t for t in teams if t.get("homeAway") == "away"), teams[1])
    home_name = home.get("displayName") or home.get("name") or "Home"
    away_name = away.get("displayName") or away.get("name") or "Away"
    status = _cricket_status(ev.get("status"))
    kickoff = ev.get("date")
    if kickoff and str(kickoff).endswith("Z"):
        kickoff = str(kickoff).replace("Z", "+00:00")
    # Prefer ESPN crest URLs from the feed — never invent wrong ids
    home_logo = home.get("logo") or None
    away_logo = away.get("logo") or None
    if home_logo and home_logo.startswith("//"):
        home_logo = "https:" + home_logo
    if away_logo and away_logo.startswith("//"):
        away_logo = "https:" + away_logo
    if not home_logo and home.get("id"):
        home_logo = f"https://a.espncdn.com/i/teamlogos/cricket/500/{home['id']}.png"
    if not away_logo and away.get("id"):
        away_logo = f"https://a.espncdn.com/i/teamlogos/cricket/500/{away['id']}.png"
    hs_raw, aws_raw = home.get("score"), away.get("score")
    hs = _cricket_score(hs_raw)
    aws = _cricket_score(aws_raw)
    home_disp = str(hs_raw).strip() if hs_raw not in (None, "") else None
    away_disp = str(aws_raw).strip() if aws_raw not in (None, "") else None
    status_detail = ""
    st = ev.get("status")
    if isinstance(st, dict):
        status_detail = str(st.get("detail") or st.get("description") or st.get("summary") or "")
    score = None
    if home_disp or away_disp:
        score = f"{home_disp or '—'}–{away_disp or '—'}"
    home_winner = bool(home.get("winner"))
    away_winner = bool(away.get("winner"))
    return {
        "id": str(ev.get("id") or ev.get("competitionId") or f"cricket-{home_name}-{away_name}"),
        "sport_key": sport_key,
        "sport_title": league_name,
        "commence_time": kickoff,
        "home_team": home_name,
        "away_team": away_name,
        "home_logo": home_logo,
        "away_logo": away_logo,
        "status": status,
        "status_detail": status_detail,
        "home_score": hs,
        "away_score": aws,
        "home_score_display": home_disp,
        "away_score_display": away_disp,
        "home_winner": home_winner,
        "away_winner": away_winner,
        "score": score,
        "bookmakers": [],
    }


def _cricket_status(status: Any) -> str:
    if isinstance(status, dict):
        state = (status.get("state") or status.get("type") or "").lower()
    else:
        state = str(status or "").lower()
    if state in ("post", "final", "result"):
        return "completed"
    if state in ("in", "live"):
        return "live"
    return "upcoming"


def _cricket_score(raw: Any) -> int | None:
    """Runs from strings like '125/7' or '142 & 342' (sum innings — never digit-concat)."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    # Multi-innings: "142 & 342" → sum first-number of each innings
    if "&" in s:
        parts = s.split("&")
        total = 0
        any_ok = False
        for part in parts:
            head = part.split("/")[0].strip()
            digits = "".join(ch for ch in head if ch.isdigit())
            if digits:
                total += int(digits)
                any_ok = True
        return total if any_ok else None
    head = s.split("/")[0].split("(")[0].strip()
    digits = "".join(ch for ch in head if ch.isdigit())
    return int(digits) if digits else None


def _parse_event(ev: dict, sport_key: str, league_name: str, sport: str) -> dict | None:
    comps = (ev.get("competitions") or [{}])[0]
    teams = comps.get("competitors") or []
    if len(teams) < 2:
        return None
    home = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
    away = next((t for t in teams if t.get("homeAway") == "away"), teams[1])
    ht = (home.get("team") or {})
    at = (away.get("team") or {})
    home_name = ht.get("displayName") or ht.get("name") or "Home"
    away_name = at.get("displayName") or at.get("name") or "Away"

    status_obj = (ev.get("status") or {}).get("type") or {}
    status = _status(status_obj)
    status_detail = (
        status_obj.get("detail")
        or status_obj.get("shortDetail")
        or status_obj.get("description")
        or ""
    )
    kickoff = ev.get("date")
    if kickoff and str(kickoff).endswith("Z"):
        kickoff = str(kickoff).replace("Z", "+00:00")

    odds_block = (comps.get("odds") or [{}])[0] if comps.get("odds") else {}
    home_odds, draw_odds, away_odds = _odds_from_espn(odds_block, sport)

    bookmakers = []
    if home_odds and away_odds:
        outcomes = [
            {"name": home_name, "price": home_odds},
            {"name": away_name, "price": away_odds},
        ]
        if draw_odds and sport == "soccer":
            outcomes.insert(1, {"name": "Draw", "price": draw_odds})
        bookmakers.append({
            "key": "espn",
            "title": (odds_block.get("provider") or {}).get("name") or "ESPN",
            "markets": [{"key": "h2h", "outcomes": outcomes}],
        })

    raw_hs, raw_aws = home.get("score"), away.get("score")
    # Cricket (and some cup feeds) use "125/7" — never int() that or the fixture is dropped
    if sport == "cricket":
        hs = _cricket_score(raw_hs)
        aws = _cricket_score(raw_aws)
        home_disp = str(raw_hs).strip() if raw_hs not in (None, "") else (str(hs) if hs is not None else None)
        away_disp = str(raw_aws).strip() if raw_aws not in (None, "") else (str(aws) if aws is not None else None)
    else:
        hs = _safe_int_score(raw_hs)
        aws = _safe_int_score(raw_aws)
        home_disp = str(hs) if hs is not None else None
        away_disp = str(aws) if aws is not None else None

    title = (
        comps.get("altGameNote")
        or (comps.get("series") or {}).get("title")
        or (comps.get("notes") or [{}])[0].get("headline")
        or league_name
    )
    home_logo = _team_logo(ht, sport)
    away_logo = _team_logo(at, sport)
    score = None
    if home_disp is not None or away_disp is not None:
        score = f"{home_disp or '—'}–{away_disp or '—'}"
    # ESPN sets competitor.winner on completed cricket (and some basketball)
    home_winner = bool(home.get("winner"))
    away_winner = bool(away.get("winner"))
    return {
        "id": str(ev.get("id") or f"espn-{home_name}-{away_name}"),
        "sport_key": sport_key,
        "sport_title": title,
        "commence_time": kickoff,
        "home_team": home_name,
        "away_team": away_name,
        "home_logo": home_logo,
        "away_logo": away_logo,
        "status": status,
        "status_detail": status_detail,
        "home_score": hs,
        "away_score": aws,
        "home_score_display": home_disp,
        "away_score_display": away_disp,
        "home_winner": home_winner,
        "away_winner": away_winner,
        "score": score,
        "bookmakers": bookmakers,
    }


def _safe_int_score(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _cricket_score(raw)


def _team_logo(team: dict, sport: str) -> str | None:
    logos = team.get("logos") or []
    for prefer in ("full", "default", "scoreboard", "indoor"):
        for L in logos:
            if (L.get("rel") == prefer or prefer in (L.get("rel") or "")) and L.get("href"):
                href = L["href"]
                return f"https:{href}" if href.startswith("//") else href
    if logos:
        href = logos[0].get("href")
        if href:
            return f"https:{href}" if href.startswith("//") else href
    logo = team.get("logo")
    if logo:
        return f"https:{logo}" if str(logo).startswith("//") else logo
    tid = team.get("id")
    if tid:
        # Soccer often lives under soccer/500; hoop under nba/wnba paths already via sport
        return f"https://a.espncdn.com/i/teamlogos/{sport}/500/{tid}.png"
    return None


def _status(t: dict) -> str:
    name = (t.get("name") or "").upper()
    state = (t.get("state") or "").lower()
    desc = (t.get("description") or "").upper()
    # Cricket ESPN often omits type.name and only sets state/description
    if (
        t.get("completed")
        or state in ("post", "final")
        or name in ("STATUS_FINAL", "STATUS_FULL_TIME")
        or desc in ("RESULT", "FINAL")
    ):
        return "completed"
    if name in (
        "STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_FIRST_HALF",
        "STATUS_SECOND_HALF", "STATUS_END_PERIOD",
    ) or state in ("in", "live"):
        return "live"
    return "upcoming"


def _to_dec(v: Any) -> float | None:
    if v is None:
        return None
    try:
        s = str(v).strip()
        if "/" in s and not s.startswith("+") and not s.startswith("-"):
            # fractional odds e.g. 11/4
            a, b = s.split("/", 1)
            return round(1 + float(a) / float(b), 2)
        if s.startswith("+") or (s.startswith("-") and s[1:].isdigit()):
            am = int(s)
            if am > 0:
                return round(1 + am / 100, 2)
            return round(1 + 100 / abs(am), 2)
        f = float(s)
        return round(f, 2) if f > 1 else None
    except Exception:
        return None


def _side_odds(block: dict | None) -> float | None:
    if not block:
        return None
    odds = block.get("odds") if isinstance(block.get("odds"), dict) else None
    if odds:
        return _to_dec(odds.get("value")) or _to_dec(odds.get("summary"))
    return (
        _to_dec(block.get("moneyLine"))
        or _to_dec(block.get("closePrice"))
        or _to_dec(block.get("current", {}).get("american") if isinstance(block.get("current"), dict) else None)
    )


def _odds_from_espn(odds: dict, sport: str) -> tuple[float | None, float | None, float | None]:
    if not odds:
        return None, None, None
    ml = odds.get("moneyline") or {}
    h = _to_dec((ml.get("home") or {}).get("close", {}).get("odds")) or _to_dec((ml.get("home") or {}).get("odds"))
    a = _to_dec((ml.get("away") or {}).get("close", {}).get("odds")) or _to_dec((ml.get("away") or {}).get("odds"))
    d = _to_dec((ml.get("draw") or {}).get("close", {}).get("odds")) or _to_dec((ml.get("draw") or {}).get("odds"))
    if h is None:
        h = _side_odds(odds.get("homeTeamOdds"))
    if a is None:
        a = _side_odds(odds.get("awayTeamOdds"))
    if d is None and sport == "soccer":
        d = _side_odds(odds.get("drawOdds")) if isinstance(odds.get("drawOdds"), dict) else _to_dec(odds.get("drawOdds"))
    return h, (d if sport == "soccer" else None), a


def enrich_open_odds(events: list[dict], cap: int = 36) -> None:
    """Public: backfill 1X2 on open unpriced rows (capped)."""
    _enrich_missing_odds(events, cap=cap)
    _ensure_fair_books(events)


def _ensure_fair_books(events: list[dict]) -> None:
    """When ESPN has no prices (common for WNBA/NCAA/cricket), attach vig-free Elo fair h2h.

    Marked key=model_fair so the desk never confuses it with a sportsbook.
    """
    try:
        from bet_placer.ml.board_train import _predict
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params
        ratings_by = (load_params().get("elo_by_sport") or {})
    except Exception:
        return

    def fair(p: float) -> float:
        p = max(0.05, min(0.95, float(p)))
        return round(1.0 / p, 3)

    for e in events or []:
        if e.get("bookmakers"):
            continue
        if e.get("status") not in ("live", "upcoming"):
            continue
        sk = e.get("sport_key") or ""
        if sk.startswith("basketball"):
            sport = "basketball"
        elif sk.startswith("cricket"):
            sport = "cricket"
        else:
            continue
        home, away = e.get("home_team") or "", e.get("away_team") or ""
        if not home or not away:
            continue
        ratings = dict(ratings_by.get(sport) or {})
        probs = _predict(ratings, canon_team(home), canon_team(away), sport) if ratings else {
            "home": 0.5, "away": 0.5,
        }
        ph = float(probs.get("home") or 0.5)
        pa = float(probs.get("away") or 0.5)
        e["bookmakers"] = [{
            "key": "model_fair",
            "title": "Gambit fair",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": fair(ph)},
                {"name": away, "price": fair(pa)},
            ]}],
        }]


def _enrich_missing_odds(events: list[dict], cap: int = 60) -> None:
    """Scoreboard often omits prices; summary has them. Cap HTTP fan-out."""
    need = [
        e for e in events
        if e.get("status") in ("live", "upcoming") and not e.get("bookmakers")
    ]
    need.sort(key=lambda e: 0 if e.get("status") == "live" else 1)
    need = need[:cap]
    if not need:
        return
    sport = "soccer"
    if need[0].get("sport_key", "").startswith("basketball"):
        sport = "basketball"
    # Cricket: still try summary 2-way prices (no draw required below).

    def one(ev: dict) -> tuple[str, tuple[float | None, float | None, float | None]]:
        sk = ev.get("sport_key") or ""
        sp = "basketball" if sk.startswith("basketball") else (
            "cricket" if sk.startswith("cricket") else sport
        )
        return ev["id"], _summary_odds(ev["id"], sp, sk)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(one, e) for e in need]
        by_id = {}
        for fut in as_completed(futs):
            try:
                eid, triple = fut.result()
                by_id[eid] = triple
            except Exception:
                continue
    for e in need:
        h, d, a = by_id.get(e["id"], (None, None, None))
        if not (h and a):
            continue
        outcomes = [
            {"name": e["home_team"], "price": h},
            {"name": e["away_team"], "price": a},
        ]
        if d and sport == "soccer":
            outcomes.insert(1, {"name": "Draw", "price": d})
        e["bookmakers"] = [{
            "key": "espn",
            "title": "ESPN",
            "markets": [{"key": "h2h", "outcomes": outcomes}],
        }]


def _summary_odds(event_id: str, sport: str, sport_key: str = "") -> tuple[float | None, float | None, float | None]:
    # ESPN summary path is sport/league
    if sport == "soccer":
        path = "soccer/all"
    elif sport == "basketball":
        if "wnba" in sport_key:
            path = "basketball/wnba"
        elif "ncaab" in sport_key or "college" in sport_key:
            path = "basketball/mens-college-basketball"
        elif "fiba" in sport_key:
            path = "basketball/fiba"
        elif "nbl" in sport_key:
            path = "basketball/nbl"
        else:
            path = "basketball/nba"
    else:
        return None, None, None
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary"
    try:
        r = _session().get(url, params={"event": event_id}, timeout=10)
        if not r.ok:
            return None, None, None
        blocks = (r.json() or {}).get("odds") or []
        if not blocks:
            return None, None, None
        return _odds_from_espn(blocks[0], sport)
    except Exception:
        return None, None, None
