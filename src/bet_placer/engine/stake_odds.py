"""On-demand Stake.com exact odds for a single match (clicked in the UI).

Best-effort and HONEST: if we can't confidently confirm the exact match on
Stake, we return available=False with a clear reason instead of showing a
different game's prices. We never guess.
"""

from __future__ import annotations

import logging
import threading
import time

from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.models.stake_types import StakeFixture, StakeMarket

logger = logging.getLogger(__name__)

from bet_placer.data.team_names import NOISE_TOKENS as _NOISE_TOKENS
from bet_placer.data.team_names import canon_team as _canon_team

# Curated, clearly-labelled markets we surface (everything else is noise to a
# student bettor). Keyed by the exact Stake market name.
_CURATED = {
    "1x2": ("Match Result", 0),
    "Double Chance": ("Match Result", 1),
    "Draw No Bet": ("Match Result", 2),
    "Asian Total": ("Total Goals (Over / Under)", 3),
    "Both Teams to Score": ("Both Teams To Score", 4),
    "Asian Handicap": ("Handicap", 5),
    "Anytime Goalscorer": ("Goalscorers", 6),
    "Total Bookings": ("Cards", 7),
    "Total Corners": ("Corners", 8),
    "Asian Corners": ("Corners", 8),
}

# For totals/handicaps we only show the sensible main lines.
_TOTAL_LINES = {1.5, 2.5, 3.5}
_HANDICAP_LINES = {-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0}


def _tokens(name: str) -> set[str]:
    raw = "".join(c if c.isalnum() else " " for c in (name or "").lower()).split()
    toks = {t for t in raw if t not in _NOISE_TOKENS}
    return toks or set(raw)


def _team_match(a: str, b: str) -> bool:
    """Match on canonical names (accent/alias-aware), order-insensitive.

    Handles 'DR Congo' == 'Congo DR', 'Bosnia' == 'Bosnia and Herzegovina',
    'Czechia' == 'Czech Republic', 'Korea Republic' == 'South Korea' — while
    still rejecting 'Korea Republic' vs 'Korea DPR'.
    """
    ca, cb = _canon_team(a), _canon_team(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    # token-set equality as a fallback (e.g. word-order differences)
    return set(ca.split()) == set(cb.split())


def _is_world_cup(fixture: StakeFixture) -> bool:
    league = (fixture.league or "").lower()
    return "world cup" in league or "wc" == league.strip()


def find_stake_fixture(home: str, away: str, scraper: StakeScraper) -> StakeFixture | None:
    """Locate the EXACT Stake fixture for these teams (both teams + WC)."""
    fixtures = scraper.fetch_trending_fixtures(sport_slug="soccer")
    for fx in fixtures:
        if not _is_world_cup(fx):
            continue
        same = _team_match(home, fx.home_team) and _team_match(away, fx.away_team)
        flipped = _team_match(home, fx.away_team) and _team_match(away, fx.home_team)
        if same or flipped:
            return fx
    return None


def _clean_label(market: StakeMarket, outcome_name: str, home: str, away: str) -> str:
    name = market.name
    sel = outcome_name.strip()
    if name == "1x2":
        return sel  # already a team name or 'Draw'
    if name == "Asian Total":
        return f"{sel} goals"
    if name == "Both Teams to Score":
        return f"Both teams score: {sel}"
    if name == "Asian Handicap":
        return sel  # e.g. 'Argentina (-0.5)'
    if name == "Anytime Goalscorer":
        return f"{sel} to score anytime"
    if name == "Total Bookings":
        return f"{sel} cards"
    if name in ("Total Corners", "Asian Corners"):
        return f"{sel} corners"
    if name == "Double Chance":
        return sel
    if name == "Draw No Bet":
        return f"{sel} (draw = money back)"
    return f"{name}: {sel}"


def _include_market(market: StakeMarket) -> bool:
    if market.name not in _CURATED:
        return False
    if market.name == "Asian Total":
        return market.line in _TOTAL_LINES
    if market.name == "Asian Handicap":
        return market.line in _HANDICAP_LINES
    return True


def curate_stake_markets(fixture: StakeFixture, budget_inr: float) -> list[dict]:
    """Return clean, clearly-labelled payout cards grouped by plain category."""
    cats: dict[str, dict] = {}
    seen: set[tuple] = set()
    for mk in fixture.markets:
        if not _include_market(mk):
            continue
        cat_name, order = _CURATED[mk.name]
        for oc in mk.outcomes:
            key = (mk.name, mk.line, oc.name)
            if key in seen:
                continue
            seen.add(key)
            payout = round(budget_inr * oc.odds)
            profit = payout - budget_inr
            entry = cats.setdefault(cat_name, {"category": cat_name, "_order": order, "options": []})
            entry["options"].append({
                "market": mk.name,
                "label": _clean_label(mk, oc.name, fixture.home_team, fixture.away_team),
                "selection": oc.name,
                "line": mk.line,
                "odds": round(oc.odds, 2),
                "payout_text": f"₹{budget_inr:,.0f} → ₹{payout:,.0f} (+₹{profit:,.0f}) if it wins",
                "return_inr": payout,
            })
    ordered = sorted(cats.values(), key=lambda c: c["_order"])
    for c in ordered:
        c.pop("_order", None)
    return ordered


def _stake_unavailable_reason(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "cloudflare" in low or "human check" in low:
        return (
            "Stake needs a one-time browser check. A Chrome window should open — "
            "complete the Cloudflare / login prompt on stake.com, then refresh this match."
        )
    if "already in use" in low or "profile is already open" in low:
        return (
            "Another Stake browser window is already open. "
            "Close it (or restart the API) and try again."
        )
    if "playwright not installed" in low:
        return "Playwright is not installed on the server — run: playwright install chromium"
    if "asyncio loop" in low:
        return (
            "Stake browser hit an internal startup glitch. "
            "Restart the API server, complete the Stake browser check if prompted, then retry."
        )
    if "geo" in low or "blocked" in low:
        return (
            "Couldn't reach Stake from this network (geo-blocked). "
            "The plan below uses DraftKings prices — open Stake directly for exact payouts."
        )
    return (
        "Couldn't reach Stake right now. "
        "The plan below uses live DraftKings prices — open Stake to confirm exact payouts."
    )


def get_stake_match_odds(home: str, away: str, budget_inr: float = 300.0) -> dict:
    """Best-effort, honest scrape of exact Stake payouts for one match."""
    global _overlay_fail_ts
    # If Stake just failed, skip the slow browser launch and degrade fast.
    if (time.monotonic() - _overlay_fail_ts) < OVERLAY_FAIL_COOLDOWN_SECONDS:
        return {
            "available": False,
            "reason": (
                "Couldn't reach Stake right now. The plan below uses live "
                "DraftKings prices — open Stake to confirm exact payouts."
            ),
            "categories": [],
        }
    try:
        scraper = StakeScraper(timeout=30)
        fixture = find_stake_fixture(home, away, scraper)
    except Exception as exc:  # geo-block, timeout, cloudflare, etc.
        logger.warning("Stake match lookup failed for %s vs %s: %s", home, away, exc)
        _overlay_fail_ts = time.monotonic()
        return {
            "available": False,
            "reason": _stake_unavailable_reason(exc),
            "detail": str(exc)[:200],
            "categories": [],
        }

    if not fixture:
        return {
            "available": False,
            "reason": (
                f"Couldn't confirm {home} vs {away} on Stake right now "
                "(it may not be listed yet, or the names differ). "
                "Showing the live-book estimate instead — open Stake to check."
            ),
            "categories": [],
        }

    categories = curate_stake_markets(fixture, budget_inr)
    return {
        "available": True,
        "fixture_id": fixture.id,
        "matched_name": fixture.name,
        "name": fixture.name,
        "tournament": fixture.league,
        "status": fixture.status,
        "kickoff": fixture.kickoff.isoformat() if fixture.kickoff else None,
        "total_bet_value_usd": round(fixture.total_bet_value, 2),
        "total_bets": fixture.total_bet_count,
        "total_bettors": fixture.total_user_count,
        "categories": categories,
        "stake_url": "https://stake.com/sports/soccer",
        "note": (
            f"Exact live payouts from Stake — {fixture.name} "
            f"({fixture.league}). Verify it's your match before betting."
        ),
    }


# ---------------------------------------------------------------------------
# Bet-plan integration: overlay Stake's real odds onto the analysis match.
# ---------------------------------------------------------------------------

def _parse_handicap_outcome(name: str) -> tuple[str, float | None]:
    """'Argentina (-0.5)' -> ('Argentina', -0.5)."""
    if "(" not in name or ")" not in name:
        return name, None
    team = name[: name.index("(")].strip()
    inside = name[name.index("(") + 1 : name.index(")")].strip()
    try:
        return team, float(inside)
    except ValueError:
        return team, None


def _round_line(x: float | None) -> float | None:
    return None if x is None else round(float(x), 1)


def _ou_selection(name: str) -> str | None:
    low = name.lower()
    if low.startswith("over"):
        return "over"
    if low.startswith("under"):
        return "under"
    return None


def _name_key(name: str) -> str:
    return "".join(sorted(_tokens(name)))


def build_stake_overlay(fixture: StakeFixture) -> dict:
    """Extract Stake's real odds AND exactly which bets Stake actually offers.

    Returns:
      - odds: {('market','selection',line): odds} to re-price the plan
      - available: set of ('market','selection',rounded_line) the user can bet
      - available_markets: set of market types Stake lists for this game
      - goalscorers / goalscorer_odds: which players Stake offers (by name key)
      - stats: crowd volume for the human story
    """
    overlay: dict[tuple, float] = {}
    available: set[tuple] = set()
    available_markets: set[str] = set()
    goalscorers: set[str] = set()
    goalscorer_odds: dict[str, float] = {}
    home, away = fixture.home_team, fixture.away_team

    for mk in fixture.markets:
        name = mk.name
        if name == "1x2":
            available_markets.add("match_winner")
            for oc in mk.outcomes:
                if oc.name == home:
                    sel = "home"
                elif oc.name == away:
                    sel = "away"
                elif oc.name.lower() in ("draw", "x"):
                    sel = "draw"
                else:
                    continue
                overlay[("match_winner", sel, None)] = oc.odds
                available.add(("match_winner", sel, None))
        elif name == "Asian Total" and mk.line is not None:
            available_markets.add("over_under_goals")
            for oc in mk.outcomes:
                sel = _ou_selection(oc.name)
                if not sel:
                    continue
                overlay[("over_under_goals", sel, mk.line)] = oc.odds
                available.add(("over_under_goals", sel, _round_line(mk.line)))
        elif name == "Both Teams to Score":
            available_markets.add("btts")
            for oc in mk.outcomes:
                low = oc.name.lower()
                sel = "yes" if low == "yes" else "no" if low == "no" else None
                if not sel:
                    continue
                overlay[("btts", sel, None)] = oc.odds
                available.add(("btts", sel, None))
        elif name == "Asian Handicap":
            available_markets.add("asian_handicap")
            for oc in mk.outcomes:
                team, hcp = _parse_handicap_outcome(oc.name)
                if hcp is None:
                    continue
                if _team_match(team, home):
                    sel = "home"
                elif _team_match(team, away):
                    sel = "away"
                else:
                    continue
                overlay[("asian_handicap", sel, hcp)] = oc.odds
                available.add(("asian_handicap", sel, _round_line(hcp)))
        elif name in ("Total Corners", "Asian Corners") and mk.line is not None:
            available_markets.add("corners")
            for oc in mk.outcomes:
                sel = _ou_selection(oc.name)
                if not sel:
                    continue
                overlay[("corners", sel, mk.line)] = oc.odds
                available.add(("corners", sel, _round_line(mk.line)))
        elif name == "Total Bookings" and mk.line is not None:
            available_markets.add("cards")
            for oc in mk.outcomes:
                sel = _ou_selection(oc.name)
                if not sel:
                    continue
                overlay[("cards", sel, mk.line)] = oc.odds
                available.add(("cards", sel, _round_line(mk.line)))
        elif name == "Anytime Goalscorer":
            available_markets.add("player_goal")
            for oc in mk.outcomes:
                key = _name_key(oc.name)
                if not key:
                    continue
                goalscorers.add(key)
                goalscorer_odds[key] = oc.odds
        elif name == "Double Chance":
            available_markets.add("double_chance")
        elif name == "Draw No Bet":
            available_markets.add("draw_no_bet")

    return {
        "odds": overlay,
        "available": available,
        "available_markets": available_markets,
        "goalscorers": goalscorers,
        "goalscorer_odds": goalscorer_odds,
        "stats": {
            "total_bet_value_usd": round(fixture.total_bet_value, 2),
            "total_bets": fixture.total_bet_count,
            "total_bettors": fixture.total_user_count,
            "fixture_name": fixture.name,
            "tournament": fixture.league,
        },
    }


def option_on_stake(market: str, selection: str, line: float | None, overlay: dict) -> bool:
    """True if this exact bet is actually offered on Stake for this match.

    When we have no Stake availability info, we DON'T filter (return True).
    """
    if not overlay:
        return True
    available = overlay.get("available")
    if not available:
        return True
    avail_markets = overlay.get("available_markets", set())

    if market == "player_goal":
        return _name_key(selection) in overlay.get("goalscorers", set())

    # These market types exist on Stake but selections/combos are hard to map
    # 1:1; if Stake lists the market, allow it.
    if market in ("double_chance", "draw_no_bet"):
        return market in avail_markets

    if market in ("match_winner", "btts"):
        return (market, selection, None) in available

    if market in ("over_under_goals", "corners", "cards", "asian_handicap"):
        rl = _round_line(line)
        if (market, selection, rl) in available:
            return True
        for (m, s, l) in available:
            if m == market and s == selection and l is not None and rl is not None and abs(l - rl) < 0.26:
                return True
        return False

    # Anything else (exact score, shots, half-time, assists, bookings props):
    # only allow if Stake actually listed that market type.
    return market in avail_markets


def fetch_stake_overlay_map(scraper: StakeScraper | None = None) -> dict[str, StakeFixture]:
    """One call: map normalized 'home|away' -> WC StakeFixture for all trending."""
    scraper = scraper or StakeScraper(timeout=9)
    result: dict[str, StakeFixture] = {}
    for fx in scraper.fetch_trending_fixtures(sport_slug="soccer"):
        if not _is_world_cup(fx):
            continue
        result[_overlay_key(fx.home_team, fx.away_team)] = fx
    return result


def _overlay_key(home: str, away: str) -> str:
    """Order-insensitive canonical key for matching our match to a Stake fixture."""
    return "|".join(sorted([_canon_team(home), _canon_team(away)]))


# ---------------------------------------------------------------------------
# Thread-safe TTL cache for the trending Stake overlay map.
#
# analyze_worldcup() runs once per API request and used to hit Stake on every
# call. The overlay map (trending WC fixtures + odds) changes slowly, so we
# cache it briefly and share it across FastAPI threadpool threads.
# ---------------------------------------------------------------------------

OVERLAY_CACHE_TTL_SECONDS = 45.0
# When Stake is unreachable, don't re-attempt the slow browser launch on every
# request — back off so the app stays fast and just serves modelled prices.
OVERLAY_FAIL_COOLDOWN_SECONDS = 90.0

_overlay_cache_lock = threading.Lock()
_overlay_cache: dict[str, StakeFixture] = {}
_overlay_cache_ts: float = 0.0
_overlay_fail_ts: float = 0.0


def stake_overlay_status() -> dict:
    """Lightweight status for the UI/health: is Stake currently reachable?"""
    now = time.monotonic()
    with _overlay_cache_lock:
        cooling = (now - _overlay_fail_ts) < OVERLAY_FAIL_COOLDOWN_SECONDS
        return {
            "have_data": bool(_overlay_cache),
            "fixtures": len(_overlay_cache),
            "cooling_down": cooling,
            "retry_in_s": round(max(0.0, OVERLAY_FAIL_COOLDOWN_SECONDS - (now - _overlay_fail_ts)), 1) if cooling else 0,
        }


def get_stake_overlay_map(force_refresh: bool = False) -> dict[str, StakeFixture]:
    """Return the trending Stake overlay map, cached for OVERLAY_CACHE_TTL_SECONDS.

    Thread-safe across FastAPI threadpool threads. A successful fetch refreshes
    the shared cache. On failure we record the time and back off for
    OVERLAY_FAIL_COOLDOWN_SECONDS so we don't relaunch the (slow) browser on
    every request — the app stays snappy on modelled prices and retries later.
    """
    global _overlay_cache, _overlay_cache_ts, _overlay_fail_ts

    now = time.monotonic()
    with _overlay_cache_lock:
        # Fresh = we successfully fetched within the TTL — serve it even if the
        # map came back empty (nothing trending), so we don't re-hit the slow
        # browser every request.
        if not force_refresh and (now - _overlay_cache_ts) < OVERLAY_CACHE_TTL_SECONDS:
            return dict(_overlay_cache)
        # Recently failed → skip the slow retry, serve what we have immediately.
        if not force_refresh and (now - _overlay_fail_ts) < OVERLAY_FAIL_COOLDOWN_SECONDS:
            return dict(_overlay_cache)

    # Fetch outside the lock so a slow Stake call doesn't block other threads.
    try:
        fetched = fetch_stake_overlay_map()
    except Exception as exc:
        logger.warning("Stake overlay map fetch failed: %s", exc)
        with _overlay_cache_lock:
            _overlay_fail_ts = time.monotonic()
            # Serve stale data if we have it; otherwise an empty map (callers
            # gracefully fall back to DraftKings pricing).
            return dict(_overlay_cache)

    with _overlay_cache_lock:
        # Mark the success time even when the result is empty (nothing trending /
        # no WC fixtures right now). Otherwise we'd re-run the slow browser fetch
        # on EVERY request — the main cause of the app feeling sluggish.
        _overlay_cache_ts = time.monotonic()
        _overlay_fail_ts = 0.0
        if fetched:
            _overlay_cache = fetched
            return _overlay_cache
        # Empty fetch: keep any prior good map but still honour the TTL above.
        return dict(_overlay_cache)


def match_overlay(home: str, away: str, overlay_map: dict[str, StakeFixture]) -> StakeFixture | None:
    return overlay_map.get(_overlay_key(home, away))


def apply_overlay_to_match(match, overlay: dict) -> int:
    """Re-price match.market_odds with Stake's real odds where mappable.

    Mutates matched MarketOdds in place and tags them with source='stake'.
    Returns how many selections were re-priced.
    """
    odds_map = overlay.get("odds", {})
    gs_odds = overlay.get("goalscorer_odds", {})
    applied = 0
    for o in match.market_odds:
        new = None
        if o.market.value == "player_goal":
            new = gs_odds.get(_name_key(o.selection))
        else:
            new = odds_map.get((o.market.value, o.selection, o.line))
            if new is None and o.line is not None:
                for (m, s, line), v in odds_map.items():
                    if m == o.market.value and s == o.selection and line is not None and abs(line - o.line) < 0.01:
                        new = v
                        break
        if new and new > 1.0:
            o.best_odds = new
            o.avg_odds = new
            o.implied_probability = 1.0 / new
            o.source = "stake"
            applied += 1
    return applied
