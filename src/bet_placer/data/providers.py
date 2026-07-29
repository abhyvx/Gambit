"""Unified odds provider — Odds API → ESPN live → demo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bet_placer.data.catalog import SportInfo, list_sports
from bet_placer.data.demo_events import get_demo_events
from bet_placer.data.espn_leagues import espn_supports, fetch_espn_events
from bet_placer.data.odds_api import OddsAPIClient, event_to_match
from bet_placer.data.stake_cache import fetch_or_cache
from bet_placer.data.stake_mapper import stake_fixture_to_match
from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.models.types import Match

logger = logging.getLogger(__name__)

STAKE_ENDPOINTS = [
    "https://stake.com/_api/graphql",
    "https://stake.bet/_api/graphql",
    "https://stake1021.com/_api/graphql",
]

# The Odds API cricket keys (cricket_all is product-only — expand when keyed)
_ODDS_CRICKET_KEYS: tuple[str, ...] = (
    "cricket_international_t20",
    "cricket_odi",
    "cricket_test_match",
    "cricket_the_hundred",
    "cricket_big_bash",
    "cricket_ipl",
    "cricket_psl",
    "cricket_caribbean_premier_league",
    "cricket_t20_blast",
    "cricket_asia_cup",
    "cricket_t20_world_cup",
    "cricket_icc_world_cup",
    "cricket_icc_trophy",
)

_ODDS_CRICKET_TAG: dict[str, str] = {
    "cricket_international_t20": "cricket_international",
    "cricket_odi": "cricket_international",
    "cricket_test_match": "cricket_international",
    "cricket_the_hundred": "cricket_hundred",
    "cricket_big_bash": "cricket_bbl",
    "cricket_ipl": "cricket_ipl",
    "cricket_psl": "cricket_psl",
    "cricket_caribbean_premier_league": "cricket_cpl",
    "cricket_t20_blast": "cricket_other",
    "cricket_asia_cup": "cricket_tournaments",
    "cricket_t20_world_cup": "cricket_tournaments",
    "cricket_icc_world_cup": "cricket_tournaments",
    "cricket_icc_trophy": "cricket_tournaments",
}


@dataclass
class EventSummary:
    id: str
    home_team: str
    away_team: str
    league: str
    sport_key: str
    kickoff: str | None
    source: str
    bookmaker_count: int = 0
    home_logo: str | None = None
    away_logo: str | None = None
    status: str = "upcoming"
    home_score: int | None = None
    away_score: int | None = None
    home_score_display: str | None = None
    away_score_display: str | None = None
    score: str | None = None
    status_detail: str | None = None
    home_odds: float | None = None
    draw_odds: float | None = None
    away_odds: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    events: list[EventSummary]
    matches: list[Match]
    source: str
    live: bool
    message: str
    raw_events: list[dict] = field(default_factory=list)


def _h2h_from_raw(ev: dict, home: str, away: str) -> tuple[float | None, float | None, float | None]:
    best_h = best_d = best_a = None
    for bm in ev.get("bookmakers") or []:
        for market in bm.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            for oc in market.get("outcomes") or []:
                name, price = oc.get("name"), float(oc.get("price") or 0)
                if not price:
                    continue
                if name == home:
                    best_h = max(best_h or 0, price) or price
                elif name == away:
                    best_a = max(best_a or 0, price) or price
                elif str(name).lower() == "draw":
                    best_d = max(best_d or 0, price) or price
    return best_h, best_d, best_a


def _summaries_from_raw(raw: list[dict], sport_key: str, source: str) -> list[EventSummary]:
    out = []
    for e in raw:
        home, away = e.get("home_team", ""), e.get("away_team", "")
        h, d, a = _h2h_from_raw(e, home, away)
        kickoff = e.get("commence_time")
        out.append(EventSummary(
            id=str(e.get("id")),
            home_team=home,
            away_team=away,
            league=e.get("sport_title") or sport_key,
            sport_key=e.get("sport_key") or sport_key,
            kickoff=kickoff,
            source=source,
            bookmaker_count=len(e.get("bookmakers") or []),
            home_logo=e.get("home_logo"),
            away_logo=e.get("away_logo"),
            status=e.get("status") or "upcoming",
            home_score=e.get("home_score"),
            away_score=e.get("away_score"),
            home_score_display=e.get("home_score_display"),
            away_score_display=e.get("away_score_display"),
            score=e.get("score"),
            status_detail=e.get("status_detail") or None,
            home_odds=h,
            draw_odds=d,
            away_odds=a,
        ))
    _backfill_model_h2h(out)
    return out


def _backfill_model_h2h(summaries: list[EventSummary]) -> None:
    """When ESPN/Odds API/Stake has no price, always show a fair moneyline.

    Never leave open fixtures blank — model Elo first, flat prior last.
    """
    elo = None
    try:
        from bet_placer.ml.elo import EloModel, _sport_from_match
        elo = EloModel()
    except Exception:
        _sport_from_match = None  # type: ignore

    for e in summaries:
        if e.status == "completed":
            continue
        if e.home_odds and e.away_odds:
            continue
        sport = "soccer"
        ph = pd = pa = None
        if elo is not None and _sport_from_match is not None:
            fake = type("M", (), {
                "home_team": e.home_team,
                "away_team": e.away_team,
                "league": e.league,
                "id": e.sport_key or e.id,
                "sport_key": e.sport_key,
            })()
            try:
                sport = _sport_from_match(fake)
                raw = elo.predict(fake)
                ph, pd, pa = float(raw["home"]), float(raw["draw"]), float(raw["away"])
            except Exception:
                ph = pd = pa = None
        # Flat priors if Elo missing — still bettable-looking prices
        if ph is None or pa is None:
            if (e.sport_key or "").startswith("basketball") or sport == "basketball":
                ph, pd, pa, sport = 0.55, 0.0, 0.45, "basketball"
            elif (e.sport_key or "").startswith("cricket") or sport == "cricket":
                ph, pd, pa, sport = 0.52, 0.0, 0.48, "cricket"
            else:
                ph, pd, pa, sport = 0.40, 0.28, 0.32, "soccer"
        margin = 1.04
        if sport in ("basketball", "cricket"):
            s = ph + pa
            if s <= 0:
                continue
            ph, pa = ph / s, pa / s
            e.home_odds = round(margin / max(ph, 0.05), 2)
            e.away_odds = round(margin / max(pa, 0.05), 2)
            e.draw_odds = None
        else:
            s = ph + pd + pa
            if s <= 0:
                continue
            ph, pd, pa = ph / s, pd / s, pa / s
            e.home_odds = round(margin / max(ph, 0.05), 2)
            e.draw_odds = round(margin / max(pd, 0.08), 2)
            e.away_odds = round(margin / max(pa, 0.05), 2)
        e.extra["odds_source"] = e.extra.get("odds_source") or "model"
        if e.source not in ("stake", "odds_api"):
            e.source = e.source or "model"


def _merge_espn_logos(summaries: list[EventSummary], sport_key: str) -> None:
    """Odds API events lack crests — copy logos from ESPN when names match."""
    if all(e.home_logo and e.away_logo for e in summaries):
        return
    if not espn_supports(sport_key) and not sport_key.startswith(("soccer", "basketball", "cricket")):
        return
    try:
        espn_key = sport_key
        if sport_key.startswith("soccer") and sport_key not in (
            "soccer_all", "soccer_epl", "soccer_uefa_champs_league",
            "soccer_spain_la_liga", "soccer_germany_bundesliga",
            "soccer_italy_serie_a", "soccer_usa_mls",
        ):
            espn_key = "soccer_all"
        raw = fetch_espn_events(espn_key)
    except Exception:
        return

    def norm(s: str) -> str:
        return "".join(ch for ch in (s or "").lower() if ch.isalnum())

    by_pair = {
        (norm(e.get("home_team", "")), norm(e.get("away_team", ""))): e
        for e in raw
    }
    for e in summaries:
        hit = by_pair.get((norm(e.home_team), norm(e.away_team)))
        if not hit:
            continue
        e.home_logo = e.home_logo or hit.get("home_logo")
        e.away_logo = e.away_logo or hit.get("away_logo")


def _merge_stake_h2h(summaries: list[EventSummary]) -> None:
    """Overlay cached Stake 1X2 onto board rows when team names match."""
    try:
        from bet_placer.engine.stake_odds import (
            build_stake_overlay, get_stake_overlay_map, match_overlay,
        )
        ov_map = get_stake_overlay_map(force_refresh=False, launch_browser=False)
        if not ov_map:
            return
        for e in summaries:
            fx = match_overlay(e.home_team, e.away_team, ov_map)
            if fx is None:
                continue
            try:
                overlay = build_stake_overlay(fx)
            except Exception:
                continue
            odds = overlay.get("odds") or {}
            h = odds.get(("match_winner", "home", None))
            d = odds.get(("match_winner", "draw", None))
            a = odds.get(("match_winner", "away", None))
            if h:
                e.home_odds = float(h)
            if d:
                e.draw_odds = float(d)
            if a:
                e.away_odds = float(a)
            if h or a:
                e.source = "stake"
                e.extra["odds_source"] = "stake"
    except Exception as exc:
        logger.debug("Stake board merge skipped: %s", exc)


def _norm_team(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _merge_fixture_boards(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Keep primary logos/status; fill h2h + missing fixtures from extra source."""
    out: list[dict] = [dict(e) for e in (primary or [])]
    by_pair: dict[tuple[str, str], dict] = {}
    for e in out:
        key = (_norm_team(e.get("home_team", "")), _norm_team(e.get("away_team", "")))
        if key[0] or key[1]:
            by_pair[key] = e

    for e in extra or []:
        home, away = e.get("home_team", ""), e.get("away_team", "")
        key = (_norm_team(home), _norm_team(away))
        rev = (key[1], key[0])
        hit = by_pair.get(key) or by_pair.get(rev)
        if hit is None:
            row = dict(e)
            out.append(row)
            if key[0] or key[1]:
                by_pair[key] = row
            continue
        if e.get("bookmakers"):
            hit["bookmakers"] = e["bookmakers"]
        title = str(hit.get("sport_title") or "")
        if e.get("sport_title") and (not title or title.lower() in ("cricket", "cricket_all", "soccer", "basketball")):
            hit["sport_title"] = e["sport_title"]
        if e.get("sport_key") and (
            not hit.get("sport_key")
            or hit.get("sport_key") in ("cricket_other", "soccer_all", "basketball_all")
        ):
            hit["sport_key"] = e["sport_key"]
        # Prefer live status/score from primary; fill if primary missing
        if not hit.get("status") or hit.get("status") == "upcoming":
            if e.get("status"):
                hit["status"] = e["status"]
        for k in (
            "home_logo", "away_logo", "score", "home_score_display", "away_score_display",
            "status_detail", "home_score", "away_score",
        ):
            if not hit.get(k) and e.get(k) is not None:
                hit[k] = e[k]

    return out


def _merge_cricket_boards(espn: list[dict], odds: list[dict]) -> list[dict]:
    return _merge_fixture_boards(espn, odds)


class UnifiedOddsProvider:
    def __init__(self):
        self.odds_api = OddsAPIClient()

    def list_sports(self, category: str | None = None, featured: bool = False) -> list[SportInfo]:
        return list_sports(category=category, featured_only=featured)

    def fetch_events(self, sport_key: str, match_filter: str | None = None) -> FetchResult:
        if sport_key in ("soccer", "soccer_trending"):
            stake_result = self._try_stake(sport_key, match_filter)
            if stake_result:
                return stake_result

        # Cricket: ESPN first (keyless)
        if sport_key.startswith("cricket"):
            return self._fetch_cricket(sport_key, match_filter)

        # 1. ESPN live scoreboards (no credit cost) — primary board path
        if espn_supports(sport_key):
            try:
                raw = fetch_espn_events(sport_key)
                raw = self._filter_raw(raw, match_filter)
                if raw:
                    try:
                        from bet_placer.data.espn_leagues import _cache_put
                        if not match_filter:
                            base = "cricket_all" if sport_key.startswith("cricket") else sport_key
                            _cache_put(f"{base}:f", raw)
                    except Exception:
                        pass
                    # Odds paint from disk only on the request path — enrich in background
                    # so boards return Stake-fast (no 80-summary fan-out on the hot path).
                    if self.odds_api.is_configured:
                        try:
                            oa = self.odds_api.fetch_odds(sport_key, markets="h2h", force=False) or []
                            # Soccer "other" / all: also pull major Odds API keys when board is thin
                            if sport_key in ("soccer_all",) or (
                                sport_key.startswith("soccer_") and len(raw) < 30
                            ):
                                for alt in (
                                    "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
                                    "soccer_italy_serie_a", "soccer_france_ligue_one",
                                    "soccer_uefa_champs_league", "soccer_usa_mls",
                                ):
                                    if alt == sport_key:
                                        continue
                                    try:
                                        chunk = self.odds_api.fetch_odds(alt, markets="h2h", force=False) or []
                                        oa.extend(chunk)
                                    except Exception:
                                        continue
                            if sport_key == "basketball_all":
                                for alt in ("basketball_nba", "basketball_wnba", "basketball_ncaab"):
                                    try:
                                        chunk = self.odds_api.fetch_odds(alt, markets="h2h", force=False) or []
                                        oa.extend(chunk)
                                    except Exception:
                                        continue
                            if oa:
                                raw = _merge_fixture_boards(raw, oa)
                        except Exception:
                            pass
                    try:
                        import threading
                        from bet_placer.data.espn_leagues import enrich_open_odds, _cache_put as _cp

                        def _bg_enrich(rows=list(raw), key=sport_key):
                            try:
                                enrich_open_odds(rows, cap=40)
                                base = "cricket_all" if key.startswith("cricket") else key
                                _cp(f"{base}:f", rows)
                            except Exception:
                                pass

                        threading.Thread(
                            target=_bg_enrich, daemon=True, name=f"espn-enrich-{sport_key}",
                        ).start()
                    except Exception:
                        pass
                    matches = [event_to_match(e, sport_key) for e in raw]
                    summaries = _summaries_from_raw(raw, sport_key, "espn")
                    _merge_stake_h2h(summaries)
                    return FetchResult(
                        summaries,
                        matches, "espn", True,
                        "Live fixtures from ESPN (+ cached books when available)",
                        raw_events=raw,
                    )
            except Exception as e:
                logger.warning("ESPN fetch failed: %s", e)

        # 2. Odds API only if ESPN empty — cache first; one forced refresh if still empty
        if self.odds_api.is_configured:
            try:
                raw = self.odds_api.fetch_odds(sport_key, force=False)
                raw = self._filter_raw(raw, match_filter)
                if raw:
                    matches = [event_to_match(e, sport_key) for e in raw]
                    summaries = _summaries_from_raw(raw, sport_key, "odds_api")
                    _merge_espn_logos(summaries, sport_key)
                    _merge_stake_h2h(summaries)
                    return FetchResult(
                        summaries,
                        matches, "odds_api", True,
                        "Live odds via The Odds API (cached)",
                        raw_events=raw,
                    )
            except Exception as e:
                logger.warning("Odds API failed: %s", e)

        # 3. Demo
        raw = get_demo_events(sport_key)
        raw = self._filter_raw(raw, match_filter)
        matches = [event_to_match(e, sport_key) for e in raw]
        return FetchResult(
            _summaries_from_raw(raw, sport_key, "demo"),
            matches, "demo", False,
            "Demo fixtures (ESPN/Stake/model cover live boards without a key)",
            raw_events=raw,
        )

    def _fetch_cricket(self, sport_key: str, match_filter: str | None) -> FetchResult:
        """ESPN fixtures/logos first; overlay Odds API h2h + Stake when available."""
        from bet_placer.data.espn_leagues import _filter_cricket_board, _tag_cricket_event

        raw: list[dict] = []
        sources: list[str] = []
        try:
            raw = fetch_espn_events("cricket_all")
            if raw:
                sources.append("espn")
        except Exception as e:
            logger.warning("ESPN cricket failed: %s", e)

        odds_raw: list[dict] = []
        if self.odds_api.is_configured:
            for key in _ODDS_CRICKET_KEYS:
                try:
                    chunk = self.odds_api.fetch_odds(key, markets="h2h", force=False) or []
                except Exception:
                    continue
                tag = _ODDS_CRICKET_TAG.get(key, "cricket_other")
                for e in chunk:
                    e = dict(e)
                    e["sport_key"] = tag
                    e.setdefault("sport_title", e.get("sport_title") or key.replace("_", " ").title())
                    # Ensure taxonomy if Odds title is thin
                    if not e.get("sport_key") or e["sport_key"] == key:
                        sk, _ = _tag_cricket_event(
                            e.get("sport_title") or "",
                            e.get("home_team") or "",
                            e.get("away_team") or "",
                        )
                        e["sport_key"] = sk
                    odds_raw.append(e)
            if odds_raw:
                sources.append("odds_api")

        raw = _merge_cricket_boards(raw, odds_raw)
        if sport_key != "cricket_all":
            raw = _filter_cricket_board(raw, sport_key)
        raw = self._filter_raw(raw, match_filter)

        if not raw:
            demo = get_demo_events(sport_key)
            demo = self._filter_raw(demo, match_filter)
            return FetchResult(
                _summaries_from_raw(demo, sport_key, "demo"),
                [event_to_match(e, sport_key) for e in demo],
                "demo", False,
                "No live cricket boards — demo fixtures",
                raw_events=demo,
            )

        try:
            import threading
            from bet_placer.data.espn_leagues import enrich_open_odds, _cache_put

            def _bg(rows=list(raw)):
                try:
                    enrich_open_odds(rows, cap=24)
                    _cache_put("cricket_all:f", rows)
                except Exception:
                    pass

            threading.Thread(target=_bg, daemon=True, name="espn-enrich-cricket").start()
        except Exception:
            pass

        source = "+".join(sources) if sources else "espn"
        matches = [event_to_match(e, e.get("sport_key") or sport_key) for e in raw]
        summaries = _summaries_from_raw(raw, sport_key, source)
        _merge_stake_h2h(summaries)
        priced = sum(1 for s in summaries if s.home_odds and s.away_odds)
        msg = f"Cricket via {source} · {len(summaries)} fixtures"
        if priced:
            msg += f" · {priced} with 1X2"
        return FetchResult(summaries, matches, source, True, msg, raw_events=raw)

    def _filter_raw(self, raw: list[dict], match_filter: str | None) -> list[dict]:
        if not match_filter:
            return raw
        needle = match_filter.lower()
        return [
            e for e in raw
            if needle in (e.get("home_team") or "").lower()
            or needle in (e.get("away_team") or "").lower()
        ]

    def get_match(self, sport_key: str, event_id: str) -> Match | None:
        result = self.fetch_events(sport_key)
        for m in result.matches:
            if m.id == event_id:
                return m
        return None

    def _try_stake(self, sport_key: str, match_filter: str | None) -> FetchResult | None:
        for endpoint in STAKE_ENDPOINTS:
            try:
                scraper = StakeScraper(endpoint=endpoint)
                fixtures, _, _, from_live = fetch_or_cache(scraper, sport="soccer")
                if not fixtures:
                    continue
                matches = [stake_fixture_to_match(f) for f in fixtures]
                if match_filter:
                    needle = match_filter.lower()
                    matches = [
                        m for m in matches
                        if needle in m.home_team.lower() or needle in m.away_team.lower()
                    ]
                if not matches:
                    continue
                summaries = [
                    EventSummary(
                        id=m.id, home_team=m.home_team, away_team=m.away_team,
                        league=m.league, sport_key=sport_key,
                        kickoff=m.kickoff.isoformat() if m.kickoff else None,
                        source="stake", bookmaker_count=1,
                    )
                    for m in matches
                ]
                _merge_stake_h2h(summaries)
                _backfill_model_h2h(summaries)
                return FetchResult(
                    summaries, matches, "stake", from_live,
                    "Live Stake odds" if from_live else "Cached Stake odds",
                )
            except Exception as e:
                logger.debug("Stake endpoint %s failed: %s", endpoint, e)
        return None
