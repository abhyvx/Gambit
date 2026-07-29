"""On-demand Stake.com exact odds for a single match (clicked in the UI).

Best-effort and HONEST: if we can't confidently confirm the exact match on
Stake, we return available=False with a clear reason instead of showing a
different game's prices. We never guess.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.models.stake_types import StakeFixture, StakeMarket

logger = logging.getLogger(__name__)

from bet_placer.data.team_names import NOISE_TOKENS as _NOISE_TOKENS
from bet_placer.data.team_names import canon_team as _canon_team

# Legacy curated buckets kept for a few special labels. Full-board rendering now
# falls back to raw group/template names when a market is not in this map.
_CURATED = {
    "1x2": ("Match Result", 0),
    "Double Chance": ("Match Result", 1),
    "Draw No Bet": ("Match Result", 2),
    "Asian Total": ("Total Goals (Over / Under)", 3),
    "Both Teams to Score": ("Both Teams To Score", 4),
    "Asian Handicap": ("Handicap", 5),
    "Anytime Goalscorer": ("Goalscorers", 6),
    "First Goalscorer": ("Goalscorers", 6),
    "Team To Score First": ("Match Result", 1),
    "Last Goalscorer": ("Goalscorers", 7),
    "Total Bookings": ("Cards", 7),
    "Total Corners": ("Corners", 8),
    "Asian Corners": ("Corners", 8),
}

# For totals/handicaps we only show the sensible main lines.
_TOTAL_LINES = {1.5, 2.5, 3.5}
_HANDICAP_LINES = {-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0}

# Stake appends these to full-time market names (e.g. "1x2 (90' + Stoppage Time)").
_STAKE_SUFFIX_RE = re.compile(r"\s*\(90'\s*\+\s*Stoppage Time\)\s*$", re.IGNORECASE)
_STAKE_VARIANT_RE = re.compile(r"\s*\(\d+up\)\s*$", re.IGNORECASE)


def canonical_stake_market(name: str) -> str | None:
    """Map Stake's live market label to our curated canonical name."""
    raw = (name or "").strip()
    if not raw:
        return None
    base = _STAKE_SUFFIX_RE.sub("", raw).strip()
    base = _STAKE_VARIANT_RE.sub("", base).strip()
    low = base.lower()

    if "&" in base:
        return None
    if "corner" in low and not (low.startswith("total corners") or low == "asian corners"):
        return None
    if "booking" in low and base not in _CURATED:
        return None
    if base.startswith("1st Half") or base.startswith("2nd Half"):
        return None

    if base in _CURATED:
        return base
    for key in _CURATED:
        if key.lower() == low:
            return key

    if "team to score" in low or "team 1st" in low or "1st team" in low:
        return "Team To Score First"
    if "anytime goalscorer" in low:
        return "Anytime Goalscorer"
    if "goalscorer" in low and "first" not in low and "last" not in low:
        return "Anytime Goalscorer"
    if low in ("1st goal",) or low.startswith("1st goal"):
        return "First Goalscorer"
    if "last goalscorer" in low or low.startswith("last goal"):
        return "Last Goalscorer"

    return None


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
    name = (fixture.name or "").lower()
    sport = (fixture.sport or "").lower()
    blob = f"{league} {name} {sport}"
    return any(k in blob for k in ("world cup", "fifa", "wc 2026", "2026 world"))


def find_stake_fixture(home: str, away: str, scraper: StakeScraper) -> StakeFixture | None:
    """Locate a Stake fixture for these teams across trending sports."""
    fixtures = scraper.fetch_trending_fixtures(sport_slug=None)
    for fx in fixtures:
        same = _team_match(home, fx.home_team) and _team_match(away, fx.away_team)
        flipped = _team_match(home, fx.away_team) and _team_match(away, fx.home_team)
        if same or flipped:
            return fx
    return None


def _combo_market_label(market_name: str, home: str, away: str) -> str:
    """Readable label for Stake pre-built SGM combo markets."""
    raw = (market_name or "").strip()
    raw = _STAKE_SUFFIX_RE.sub("", raw).strip()
    raw = _STAKE_VARIANT_RE.sub("", raw).strip()
    return raw.replace(home, home).replace(away, away)


def _clean_label(market: StakeMarket, outcome_name: str, home: str, away: str) -> str:
    name = canonical_stake_market(market.name) or market.name
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
    low = (market.name or "").lower()
    if "1st half" in low or "2nd half" in low:
        return False
    if "player " in low and "goalscorer" not in low:
        return False
    return True


def _market_category_name(market: StakeMarket) -> tuple[str, int]:
    canon = canonical_stake_market(market.name)
    if canon and canon in _CURATED:
        return _CURATED[canon]
    template = (market.template or "").strip()
    group = (market.group or "").strip()
    label = template or group or "More markets"
    order_map = {
        "main": 0, "winner": 1, "threeway": 2, "totals": 3, "goals": 4,
        "handicap": 5, "corners": 6, "cards": 7, "player props": 8,
    }
    order = order_map.get(group.lower(), 50)
    return label, order


def curate_stake_markets(fixture: StakeFixture, budget_inr: float) -> list[dict]:
    """Return a full-board Stake market view grouped for UI rendering."""
    cats: dict[str, dict] = {}
    seen: set[tuple] = set()
    for mk in fixture.markets:
        cat_name, order = _market_category_name(mk)
        if "&" in (mk.name or ""):
            for oc in mk.outcomes:
                if oc.odds <= 1.0:
                    continue
                key = (mk.name, mk.line, oc.name)
                if key in seen:
                    continue
                seen.add(key)
                label = oc.name.strip()
                if label.lower() in ("yes", "no") and len(mk.outcomes) <= 2:
                    label = f"{_combo_market_label(mk.name, fixture.home_team, fixture.away_team)} — {label}"
                else:
                    label = label or _combo_market_label(mk.name, fixture.home_team, fixture.away_team)
                payout = round(budget_inr * oc.odds)
                profit = payout - budget_inr
                entry = cats.setdefault("Combos", {"category": "Combos", "_order": 99, "options": []})
                entry["options"].append({
                    "market_id": mk.id,
                    "outcome_id": oc.id,
                    "market": mk.name,
                    "label": label,
                    "selection": oc.name,
                    "line": mk.line,
                    "odds": round(oc.odds, 2),
                    "payout_text": f"₹{budget_inr:,.0f} → ₹{payout:,.0f} (+₹{profit:,.0f}) if it wins",
                    "return_inr": payout,
                    "is_stake_combo": True,
                    "group": mk.group,
                    "template": mk.template,
                    "specifiers": mk.specifiers,
                })
            continue
        if not _include_market(mk):
            continue
        for oc in mk.outcomes:
            key = (mk.name, mk.line, oc.name)
            if key in seen:
                continue
            seen.add(key)
            payout = round(budget_inr * oc.odds)
            profit = payout - budget_inr
            entry = cats.setdefault(cat_name, {"category": cat_name, "_order": order, "options": []})
            entry["options"].append({
                "market_id": mk.id,
                "outcome_id": oc.id,
                "market": mk.name,
                "label": (
                    _clean_label(mk, oc.name, fixture.home_team, fixture.away_team)
                    if canonical_stake_market(mk.name)
                    else oc.name.strip() or mk.name
                ),
                "selection": oc.name,
                "line": mk.line,
                "odds": round(oc.odds, 2),
                "payout_text": f"₹{budget_inr:,.0f} → ₹{payout:,.0f} (+₹{profit:,.0f}) if it wins",
                "return_inr": payout,
                "group": mk.group,
                "template": mk.template,
                "specifiers": mk.specifiers,
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
    global _overlay_fail_ts, _overlay_cache, _overlay_cache_ts

    # Fast path: already-warm overlay cache (no browser launch).
    try:
        overlay_map = get_stake_overlay_map(launch_browser=False)
        fx = match_overlay(home, away, overlay_map)
        if fx and fx.markets:
            categories = curate_stake_markets(fx, budget_inr)
            if categories:
                ov = build_stake_overlay(fx)
                persist_match_stake_data(home, away, fx, ov)
                return _stake_match_response(fx, categories, source="stake_overlay")
    except Exception as exc:
        logger.debug("Stake overlay lookup failed: %s", exc)

    fixture = None
    try:
        scraper = StakeScraper(timeout=60, allow_browser_launch=True)
        fixture = _lookup_stake_fixture(scraper, home, away)
    except Exception as exc:
        if _is_profile_lock_error(exc):
            logger.warning("Stake profile locked for %s vs %s, waiting: %s", home, away, exc)
            from bet_placer.data.stake_browser import wait_for_browser_ready

            if wait_for_browser_ready(timeout_s=120.0):
                try:
                    scraper = StakeScraper(timeout=60, allow_browser_launch=True)
                    fixture = _lookup_stake_fixture(scraper, home, away)
                except Exception as retry_exc:
                    exc = retry_exc
        if fixture is None:
            logger.warning("Stake match lookup failed for %s vs %s: %s", home, away, exc)
            _overlay_fail_ts = time.monotonic()
            cached_fx = get_cached_fixture(home, away)
            if cached_fx and cached_fx.markets:
                categories = curate_stake_markets(cached_fx, budget_inr)
                if categories:
                    resp = _stake_match_response(cached_fx, categories, source="stake_cache")
                    resp["from_cache"] = True
                    resp["note"] = (
                        f"Cached Stake lines for {home} vs {away}. "
                        "Stake is unreachable — open Odds tab to refresh when back online."
                    )
                    return resp
            return {
                "available": False,
                "reason": _stake_unavailable_reason(exc),
                "detail": str(exc)[:200],
                "categories": [],
            }

    if not fixture or not fixture.markets:
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
    if not categories:
        return {
            "available": False,
            "reason": f"Found {home} vs {away} on Stake but couldn't map markets.",
            "categories": [],
        }

    # Warm the shared cache with this fixture for the main pipeline.
    ov = build_stake_overlay(fixture)
    persist_match_stake_data(home, away, fixture, ov)

    return _stake_match_response(fixture, categories, source="stake_live")


def _stake_match_response(fixture: StakeFixture, categories: list, *, source: str) -> dict:
    return {
        "available": True,
        "fixture_id": fixture.id,
        "matched_name": fixture.name,
        "name": fixture.name,
        "home": fixture.home_team,
        "away": fixture.away_team,
        "tournament": fixture.league,
        "status": fixture.status,
        "kickoff": fixture.kickoff.isoformat() if fixture.kickoff else None,
        "total_bet_value_usd": round(fixture.total_bet_value, 2),
        "total_bets": fixture.total_bet_count,
        "total_bettors": fixture.total_user_count,
        "categories": categories,
        "source": source,
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


def _dc_selection(outcome_name: str, home: str, away: str) -> str | None:
    """Map Stake double-chance label → home_draw / draw_away / home_away."""
    toks = _tokens(outcome_name)
    home_t, away_t, draw_t = _tokens(home), _tokens(away), {"draw", "x"}
    has_home = bool(toks & home_t)
    has_away = bool(toks & away_t)
    has_draw = bool(toks & draw_t)
    if has_home and has_draw:
        return "home_draw"
    if has_away and has_draw:
        return "draw_away"
    if has_home and has_away:
        return "home_away"
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
    goalscorer_labels: dict[str, str] = {}
    stake_combos: list[dict] = []
    home, away = fixture.home_team, fixture.away_team

    for mk in fixture.markets:
        name = mk.name or ""
        # Stake same-game multis are pre-built combo markets (name contains "&").
        if "&" in name:
            for oc in mk.outcomes:
                if oc.odds <= 1.0:
                    continue
                label = oc.name.strip()
                if label.lower() in ("yes", "no") and len(mk.outcomes) <= 2:
                    label = f"{_combo_market_label(name, home, away)} — {label}"
                else:
                    label = label or _combo_market_label(name, home, away)
                stake_combos.append({
                    "stake_market": name,
                    "label": label,
                    "selection": oc.name,
                    "line": mk.line,
                    "odds": round(float(oc.odds), 2),
                    "market": "stake_combo",
                    "source": "stake",
                })
            continue

        name = canonical_stake_market(name)
        if not name:
            continue
        if name == "1x2":
            available_markets.add("match_winner")
            for oc in mk.outcomes:
                if _team_match(oc.name, home):
                    sel = "home"
                elif _team_match(oc.name, away):
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
                goalscorer_labels[key] = oc.name.strip()
        elif name == "Double Chance":
            available_markets.add("double_chance")
            for oc in mk.outcomes:
                sel = _dc_selection(oc.name, home, away)
                if not sel:
                    continue
                overlay[("double_chance", sel, None)] = oc.odds
                available.add(("double_chance", sel, None))
        elif name == "Draw No Bet":
            available_markets.add("draw_no_bet")
            for oc in mk.outcomes:
                if _team_match(oc.name, home):
                    sel = "home"
                elif _team_match(oc.name, away):
                    sel = "away"
                else:
                    continue
                overlay[("draw_no_bet", sel, None)] = oc.odds
                available.add(("draw_no_bet", sel, None))
        elif name == "Team To Score First":
            available_markets.add("team_first_goal")
            for oc in mk.outcomes:
                if _team_match(oc.name, home):
                    sel = "home"
                elif _team_match(oc.name, away):
                    sel = "away"
                else:
                    continue
                overlay[("team_first_goal", sel, None)] = oc.odds
                available.add(("team_first_goal", sel, None))

    return {
        "home": home,
        "away": away,
        "odds": overlay,
        "available": available,
        "available_markets": available_markets,
        "goalscorers": goalscorers,
        "goalscorer_odds": goalscorer_odds,
        "goalscorer_labels": goalscorer_labels,
        "stake_combos": stake_combos,
        "stats": {
            "total_bet_value_usd": round(fixture.total_bet_value, 2),
            "total_bets": fixture.total_bet_count,
            "total_bettors": fixture.total_user_count,
            "fixture_name": fixture.name,
            "tournament": fixture.league,
        },
    }


def stake_overlay_ready(overlay: dict | None) -> bool:
    """True when we have a confirmed Stake availability list for this fixture."""
    if not overlay:
        return False
    if overlay.get("available"):
        return True
    # Cached overlays always retain the availability list.
    return bool(overlay.get("from_cache") and overlay.get("odds"))


def stake_lines_usable(overlay: dict | None, ctx: dict | None = None) -> bool:
    """True when we can build recs from verified Stake lines (live, cache, or flat board)."""
    if stake_overlay_ready(overlay):
        return True
    ctx = ctx or {}
    if ctx.get("_board_source") == "stake" and ctx.get("_flat_board"):
        return True
    if ctx.get("stake_from_cache") and overlay:
        return True
    if ctx.get("grading_replay") and ctx.get("_flat_board") and stake_overlay_ready(overlay):
        return True
    return False


def _goalscorer_key_match(selection: str, overlay: dict) -> str | None:
    """Match model/squad name to a scraped Stake goalscorer key."""
    from bet_placer.data.team_stars import _names_same_player

    nk = _name_key(selection)
    keys = overlay.get("goalscorers") or set()
    if nk in keys:
        return nk
    labels = overlay.get("goalscorer_labels") or {}
    for key in keys:
        label = labels.get(key, "")
        if label and _names_same_player(selection, label):
            return key
        if key and nk and (nk in key or key in nk):
            return key
    return None


def inject_goalscorer_options(options: list, overlay: dict | None, home: str, away: str) -> int:
    """Add Stake-scraped scorers missing from the model options list."""
    if not overlay or not overlay.get("goalscorer_odds"):
        return 0
    from bet_placer.data.team_stars import player_goal_eligible
    from bet_placer.engine.market_advisor import MarketOption

    existing = {_name_key(o.selection) for o in options if o.market == "player_goal"}
    labels = overlay.get("goalscorer_labels") or {}
    added = 0
    for key, odds in (overlay.get("goalscorer_odds") or {}).items():
        if odds <= 1.0:
            continue
        name = labels.get(key) or key
        if not player_goal_eligible(home, away, name):
            continue
        if key in existing:
            continue
        prob = min(0.55, 1.0 / float(odds) * 0.94)
        options.append(MarketOption(
            category="Goalscorers",
            market="player_goal",
            selection=name,
            line=None,
            label=f"{name} to score",
            odds=round(float(odds), 2),
            stake_payout=round(100 * float(odds), 0),
            our_probability=prob,
            book_implied=round(1.0 / float(odds), 4),
            fair_implied=prob,
            edge_pct=0.0,
            ev_pct=0.0,
            recommendation="NEUTRAL",
            stake_inr=0.0,
            reason="Stake anytime goalscorer",
            human_factors=[],
            plain_verdict="",
            plain_chance="",
            plain_payout="",
            plain_value="",
            stake_payout_text="",
            source="stake",
        ))
        existing.add(key)
        added += 1
    return added


def option_on_stake(market: str, selection: str, line: float | None, overlay: dict) -> bool:
    """True if this exact bet is actually offered on Stake for this match."""
    if not stake_overlay_ready(overlay):
        return False
    available = overlay.get("available")
    avail_markets = overlay.get("available_markets", set())

    if market == "player_goal":
        home = overlay.get("home")
        away = overlay.get("away")
        if home and away:
            from bet_placer.data.team_stars import player_goal_eligible
            if not player_goal_eligible(home, away, selection):
                return False
        return _goalscorer_key_match(selection, overlay) is not None

    # These market types exist on Stake but selections/combos are hard to map
    # 1:1; if Stake lists the market, allow it.
    if market in ("double_chance", "draw_no_bet", "team_first_goal"):
        return market in avail_markets or (market, selection, None) in available

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


def _is_profile_lock_error(exc: Exception) -> bool:
    low = str(exc).lower()
    return "profile is already open" in low or "already in use" in low


def _fetch_overlay_map_launching() -> dict[str, StakeFixture]:
    """Fetch overlay map; if browser is still starting, wait — never kill Chrome."""
    try:
        return fetch_stake_overlay_map(launch_browser=True)
    except Exception as exc:
        if not _is_profile_lock_error(exc):
            raise
        logger.warning("Stake profile locked during overlay fetch, waiting: %s", exc)
        from bet_placer.data.stake_browser import wait_for_browser_ready

        if wait_for_browser_ready(timeout_s=180.0):
            return fetch_stake_overlay_map(launch_browser=True)
        raise


def fetch_stake_overlay_map(
    scraper: StakeScraper | None = None,
    *,
    launch_browser: bool = False,
) -> dict[str, StakeFixture]:
    """Map WC fixtures on Stake → fixture with markets (trending feed, fast)."""
    scraper = scraper or StakeScraper(timeout=45, allow_browser_launch=launch_browser)
    return fetch_fast_stake_overlay(scraper)


def fetch_fast_stake_overlay(scraper: StakeScraper) -> dict[str, StakeFixture]:
    """Trending fixtures across sports — they already ship full market boards.

    Never re-fetch odds when markets are present (the detail query often 400s
    and blocks the single browser thread for minutes).
    """
    result: dict[str, StakeFixture] = {}
    fixtures: list = []
    # Unfiltered homepage trending covers soccer + basketball + cricket + more.
    try:
        fixtures.extend(scraper.fetch_trending_fixtures(sport_slug=None))
    except Exception as exc:
        logger.warning("Stake trending (all) failed: %s", exc)
    for slug in ("soccer", "basketball", "cricket"):
        try:
            fixtures.extend(scraper.fetch_trending_fixtures(sport_slug=slug))
        except Exception as exc:
            logger.debug("Stake trending %s failed: %s", slug, exc)

    seen_ids: set[str] = set()
    for fx in fixtures:
        fid = str(getattr(fx, "id", "") or "")
        key = _overlay_key(fx.home_team, fx.away_team)
        if fid and fid in seen_ids:
            # Prefer the copy that already has markets
            if key in result and result[key].markets:
                continue
        if fid:
            seen_ids.add(fid)
        if fx.markets:
            result[key] = fx
            continue
        if not fx.id:
            result[key] = fx
            continue
        try:
            result[key] = scraper.fetch_fixture_odds(fx.id)
        except Exception as exc:
            logger.debug("Stake odds fetch %s failed: %s", key, exc)
            result[key] = fx

    logger.info("Stake fast overlay: %d fixtures", len(result))
    return result


def fetch_full_worldcup_overlay(scraper: StakeScraper) -> dict[str, StakeFixture]:
    """Alias — fast trending overlay + on-demand lookup for one-off matches."""
    return fetch_fast_stake_overlay(scraper)


def _lookup_stake_fixture(scraper: StakeScraper, home: str, away: str) -> StakeFixture | None:
    """Find a fixture on Stake; keep embedded markets when already present."""
    fx = find_stake_fixture(home, away, scraper)
    if not fx:
        try:
            fx = scraper.search_fixture_by_teams(home, away)
        except Exception:
            fx = None
    if not fx or fx.markets or not fx.id:
        return fx
    try:
        return scraper.fetch_fixture_odds(fx.id)
    except Exception as exc:
        logger.debug("Stake detail fetch %s vs %s failed: %s", home, away, exc)
        return fx


def _overlay_key(home: str, away: str) -> str:
    """Order-insensitive canonical key for matching our match to a Stake fixture."""
    return "|".join(sorted([_canon_team(home), _canon_team(away)]))


# ---------------------------------------------------------------------------
# Thread-safe TTL cache for the trending Stake overlay map.
#
# analyze_worldcup() runs once per API request and used to hit Stake on every
# call. The overlay map (trending soccer fixtures + odds) changes slowly, so we
# cache it briefly and share it across FastAPI threadpool threads.
# ---------------------------------------------------------------------------

OVERLAY_CACHE_TTL_SECONDS = 1800.0
# When Stake is unreachable, don't re-attempt the slow browser launch on every
# request — back off so the app stays fast and serves cached prices.
OVERLAY_FAIL_COOLDOWN_SECONDS = 45.0

_overlay_cache_lock = threading.Condition()
_overlay_cache: dict[str, StakeFixture] = {}
_overlay_cache_ts: float = 0.0
_overlay_fail_ts: float = 0.0
_overlay_fetching = False
_overlay_fetch_started: float = 0.0
OVERLAY_FETCH_MAX_SECONDS = 90.0

_disk_loaded = False
_overlay_disk_overlays: dict[str, dict] = {}


def _stake_disk_path() -> Path:
    return Path.home() / ".bet_placer" / "stake_overlay_cache.json"


def _serialize_fixture(fx: StakeFixture) -> dict:
    return {
        "id": fx.id,
        "name": fx.name,
        "home_team": fx.home_team,
        "away_team": fx.away_team,
        "sport": fx.sport,
        "league": fx.league,
        "status": fx.status,
        "kickoff": fx.kickoff.isoformat() if fx.kickoff else None,
        "total_bet_value": fx.total_bet_value,
        "total_bet_count": fx.total_bet_count,
        "total_user_count": fx.total_user_count,
        "markets": [
            {
                "name": m.name,
                "group": m.group,
                "line": m.line,
                "outcomes": [
                    {
                        "id": o.id,
                        "name": o.name,
                        "odds": o.odds,
                        "active": o.active,
                        "payout_multiplier": o.payout_multiplier,
                    }
                    for o in m.outcomes
                ],
            }
            for m in fx.markets
        ],
    }


def _deserialize_fixture(data: dict) -> StakeFixture | None:
    if not data or not data.get("home_team") or not data.get("away_team"):
        return None
    from bet_placer.models.stake_types import StakeOutcome

    kickoff = None
    if data.get("kickoff"):
        try:
            kickoff = datetime.fromisoformat(str(data["kickoff"]).replace("Z", "+00:00"))
        except Exception:
            kickoff = None
    markets = []
    for m in data.get("markets") or []:
        outcomes = [
            StakeOutcome(
                id=str(o.get("id") or ""),
                name=str(o.get("name") or ""),
                odds=float(o.get("odds") or 0),
                active=bool(o.get("active", True)),
                payout_multiplier=o.get("payout_multiplier"),
                market_id=str(o.get("market_id") or ""),
                raw=o.get("raw") or {},
            )
            for o in m.get("outcomes") or []
        ]
        markets.append(StakeMarket(
            id=str(m.get("id") or ""),
            name=str(m.get("name") or ""),
            group=str(m.get("group") or ""),
            outcomes=outcomes,
            line=m.get("line"),
            specifiers=str(m.get("specifiers") or ""),
            template=str(m.get("template") or ""),
            status=str(m.get("status") or ""),
            raw=m.get("raw") or {},
        ))
    return StakeFixture(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        home_team=str(data["home_team"]),
        away_team=str(data["away_team"]),
        sport=str(data.get("sport") or "soccer"),
        league=str(data.get("league") or ""),
        status=str(data.get("status") or ""),
        kickoff=kickoff,
        markets=markets,
        total_bet_value=float(data.get("total_bet_value") or 0),
        total_bet_count=int(data.get("total_bet_count") or 0),
        total_user_count=int(data.get("total_user_count") or 0),
    )


def _overlay_for_disk(overlay: dict) -> dict:
    out = dict(overlay)
    for key in ("available", "available_markets", "goalscorers"):
        val = out.get(key)
        if isinstance(val, set):
            out[key] = [list(x) if isinstance(x, tuple) else x for x in val]
    odds = out.get("odds")
    if isinstance(odds, dict):
        out["odds"] = {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in odds.items()}
    return out


def _overlay_from_disk(data: dict) -> dict:
    out = dict(data)
    out["from_cache"] = True
    for key in ("available", "available_markets", "goalscorers"):
        val = out.get(key)
        if val and isinstance(val, list):
            if key == "goalscorers":
                out[key] = set(val)
            elif key == "available_markets":
                out[key] = set(val)
            else:
                out[key] = {tuple(x) for x in val}
    odds = out.get("odds")
    if isinstance(odds, dict):
        parsed = {}
        for k, v in odds.items():
            if isinstance(k, str) and "|" in k:
                parts = k.split("|", 2)
                line = None if parts[2] in ("None", "") else float(parts[2]) if parts[2] else None
                parsed[(parts[0], parts[1], line)] = float(v)
            else:
                parsed[k] = v
        out["odds"] = parsed
    return out


def warm_stake_cache_from_disk() -> int:
    """Load persisted Stake fixtures + overlays into memory. Returns fixture count."""
    global _disk_loaded, _overlay_cache, _overlay_cache_ts, _overlay_disk_overlays
    with _overlay_cache_lock:
        if _disk_loaded:
            return len(_overlay_cache)
        _disk_loaded = True
        path = _stake_disk_path()
        if not path.exists():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Stake disk cache unreadable: %s", exc)
            return 0
        for key, fx_data in (raw.get("fixtures") or {}).items():
            fx = _deserialize_fixture(fx_data)
            if fx and fx.markets:
                _overlay_cache[key] = fx
        for key, ov_data in (raw.get("overlays") or {}).items():
            if ov_data:
                _overlay_disk_overlays[key] = _overlay_from_disk(ov_data)
        if _overlay_cache or _overlay_disk_overlays:
            _overlay_cache_ts = time.monotonic()
            _overlay_fail_ts = 0.0
        logger.info(
            "Stake disk cache loaded: %d fixtures, %d overlays",
            len(_overlay_cache), len(_overlay_disk_overlays),
        )
        return len(_overlay_cache)


def _save_disk_cache() -> None:
    path = _stake_disk_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "fixtures": {_k: _serialize_fixture(fx) for _k, fx in _overlay_cache.items() if fx.markets},
            "overlays": {_k: _overlay_for_disk(ov) for _k, ov in _overlay_disk_overlays.items()},
        }
        path.write_text(json.dumps(payload, indent=0), encoding="utf-8")
    except Exception as exc:
        logger.warning("Stake disk cache save failed: %s", exc)


def persist_match_stake_data(
    home: str, away: str, fixture: StakeFixture | None, overlay: dict | None,
) -> None:
    """Keep Stake lines on disk — survives restarts and failed refreshes."""
    with _overlay_cache_lock:
        _persist_match_stake_unlocked(home, away, fixture, overlay)
        _save_disk_cache()


def _persist_match_stake_unlocked(
    home: str, away: str, fixture: StakeFixture | None, overlay: dict | None,
) -> None:
    global _overlay_cache_ts, _overlay_fail_ts
    key = _overlay_key(home, away)
    if fixture and fixture.markets:
        _overlay_cache[key] = fixture
    if overlay:
        ov = dict(overlay)
        ov["home"] = home
        ov["away"] = away
        ov["from_cache"] = True
        ov["cached_at"] = datetime.utcnow().isoformat() + "Z"
        _overlay_disk_overlays[key] = ov
    _overlay_cache_ts = time.monotonic()
    _overlay_fail_ts = 0.0


def get_cached_fixture(home: str, away: str) -> StakeFixture | None:
    warm_stake_cache_from_disk()
    key = _overlay_key(home, away)
    with _overlay_cache_lock:
        return _overlay_cache.get(key)


def get_cached_match_overlay(home: str, away: str) -> dict | None:
    """Return last known Stake overlay for this match (memory or disk)."""
    warm_stake_cache_from_disk()
    key = _overlay_key(home, away)
    with _overlay_cache_lock:
        ov = _overlay_disk_overlays.get(key)
        if ov:
            return dict(ov)
        fx = _overlay_cache.get(key)
    if fx and fx.markets:
        try:
            ov = build_stake_overlay(fx)
            ov["home"] = home
            ov["away"] = away
            ov["from_cache"] = True
            with _overlay_cache_lock:
                _overlay_disk_overlays[key] = ov
            return ov
        except Exception:
            return None
    return None


def hydrate_stake_context(ctx: dict, home: str, away: str) -> dict:
    """Ensure human_context has Stake overlay from live data or cache."""
    ctx = dict(ctx or {})
    overlay = ctx.get("stake_overlay")
    if stake_overlay_ready(overlay):
        return ctx
    cached = get_cached_match_overlay(home, away)
    if cached:
        ctx["stake_overlay"] = cached
        ctx["stake_from_cache"] = True
        ctx["stake_priced"] = True
    return ctx


def _reset_stale_overlay_fetch() -> None:
    global _overlay_fetching
    if not _overlay_fetching:
        return
    if (time.monotonic() - _overlay_fetch_started) > OVERLAY_FETCH_MAX_SECONDS:
        logger.warning("Stake overlay fetch timed out — resetting stuck fetch flag")
        _overlay_fetching = False
        _overlay_cache_lock.notify_all()


def refresh_stake_overlay() -> dict:
    """Force a fast trending refresh (used by /api/stake/refresh)."""
    global _overlay_fetching, _overlay_fetch_started
    with _overlay_cache_lock:
        _overlay_fetching = False
        _overlay_fetch_started = 0.0
        _overlay_cache_lock.notify_all()
    fetched = get_stake_overlay_map(force_refresh=True, launch_browser=True)
    return {"fixtures": len(fetched), "status": stake_overlay_status()}


def stake_overlay_status() -> dict:
    """Lightweight status for the UI/health: is Stake currently reachable?"""
    now = time.monotonic()
    with _overlay_cache_lock:
        _reset_stale_overlay_fetch()
        cooling = (now - _overlay_fail_ts) < OVERLAY_FAIL_COOLDOWN_SECONDS
        return {
            "have_data": bool(_overlay_cache or _overlay_disk_overlays),
            "fixtures": len(_overlay_cache),
            "cached_overlays": len(_overlay_disk_overlays),
            "cooling_down": cooling,
            "fetching": _overlay_fetching,
            "retry_in_s": round(max(0.0, OVERLAY_FAIL_COOLDOWN_SECONDS - (now - _overlay_fail_ts)), 1) if cooling else 0,
        }


def get_stake_overlay_map(
    force_refresh: bool = False,
    *,
    launch_browser: bool = False,
) -> dict[str, StakeFixture]:
    """Return the trending Stake overlay map, cached for OVERLAY_CACHE_TTL_SECONDS.

    Thread-safe across FastAPI threadpool threads. A successful fetch refreshes
    the shared cache. On failure we record the time and back off for
    OVERLAY_FAIL_COOLDOWN_SECONDS so we don't relaunch the (slow) browser on
    every request — the app stays snappy on modelled prices and retries later.

    When launch_browser=False (default), never starts Chromium — only returns
    cached data. Use launch_browser=True for explicit Stake odds requests.
    """
    global _overlay_cache, _overlay_cache_ts, _overlay_fail_ts, _overlay_fetching, _overlay_fetch_started

    warm_stake_cache_from_disk()
    now = time.monotonic()
    with _overlay_cache_lock:
        _reset_stale_overlay_fetch()
        if not force_refresh and (now - _overlay_cache_ts) < OVERLAY_CACHE_TTL_SECONDS:
            return dict(_overlay_cache)
        if not force_refresh and (now - _overlay_fail_ts) < OVERLAY_FAIL_COOLDOWN_SECONDS:
            return dict(_overlay_cache)
        if not launch_browser:
            return dict(_overlay_cache)
        while _overlay_fetching:
            _overlay_cache_lock.wait(timeout=10.0)
            _reset_stale_overlay_fetch()
            if not force_refresh and (time.monotonic() - _overlay_cache_ts) < OVERLAY_CACHE_TTL_SECONDS:
                return dict(_overlay_cache)
        _overlay_fetching = True
        _overlay_fetch_started = time.monotonic()

    try:
        fetched = _fetch_overlay_map_launching()
    except Exception as exc:
        logger.warning("Stake overlay map fetch failed: %s", exc)
        with _overlay_cache_lock:
            _overlay_fail_ts = time.monotonic()
            return dict(_overlay_cache)
    finally:
        with _overlay_cache_lock:
            _overlay_fetching = False
            _overlay_cache_lock.notify_all()

    with _overlay_cache_lock:
        _overlay_cache_ts = time.monotonic()
        _overlay_fail_ts = 0.0
        if fetched:
            _overlay_cache.update(fetched)
            for key, fx in fetched.items():
                if not fx.markets:
                    continue
                try:
                    ov = build_stake_overlay(fx)
                    _persist_match_stake_unlocked(fx.home_team, fx.away_team, fx, ov)
                except Exception as exc:
                    logger.debug("Stake overlay persist failed for %s: %s", key, exc)
            _save_disk_cache()
            return dict(_overlay_cache)
        return dict(_overlay_cache)


def match_overlay(home: str, away: str, overlay_map: dict[str, StakeFixture]) -> StakeFixture | None:
    return overlay_map.get(_overlay_key(home, away))


def reprice_options_from_overlay(
    options: list, overlay: dict | None, home: str | None = None, away: str | None = None,
) -> int:
    """Sync option odds to scraped Stake prices where mappable."""
    if not overlay:
        return 0
    home = home or overlay.get("home")
    away = away or overlay.get("away")
    odds_map = overlay.get("odds", {})
    gs_odds = overlay.get("goalscorer_odds", {})
    applied = 0
    for o in options:
        if o.market == "player_goal" and home and away:
            from bet_placer.data.team_stars import player_goal_eligible
            if not player_goal_eligible(home, away, o.selection):
                continue
        new = None
        if o.market == "player_goal":
            gkey = _goalscorer_key_match(o.selection, overlay)
            new = gs_odds.get(gkey) if gkey else None
        else:
            new = odds_map.get((o.market, o.selection, o.line))
            if new is None and o.line is not None:
                rl = _round_line(o.line)
                new = odds_map.get((o.market, o.selection, rl))
                if new is None:
                    for (m, s, line), v in odds_map.items():
                        if m == o.market and s == o.selection and line is not None and abs(line - rl) < 0.26:
                            new = v
                            break
        if new and new > 1.0:
            o.odds = round(float(new), 2)
            o.source = "stake"
            applied += 1
    return applied


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
            gkey = _goalscorer_key_match(o.selection, overlay)
            new = gs_odds.get(gkey) if gkey else None
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
