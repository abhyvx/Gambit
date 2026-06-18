"""'Stake, but hacked' — the FULL bet menu for one match, annotated with our read.

Goal: show EVERY field Stake offers for a game (or our full modelled catalog
when Stake is unreachable), and on each single outcome attach our own verdict:
our win probability, the edge vs the price, expected value, and a plain ✅/⚠️/❌
call so the user can select bets exactly like Stake — and know which ones we'd
actually back.

The combined-slip math (parlay vs singles, win%, EV, payout) is done live on
the client as the user clicks selections, so this module only has to produce a
rich, fully-annotated per-outcome menu.
"""

from __future__ import annotations

import logging

from bet_placer.data.team_ratings import get_team_rating
from bet_placer.engine.game_profile import is_generic_trap
from bet_placer.engine.market_advisor import analyze_all_options, serialize_option
from bet_placer.engine.market_probs import MatchModel, rate_outcome
from bet_placer.engine.player_props import PlayerModel
from bet_placer.ml.params import calibrate_prob
from bet_placer.engine.stake_odds import (
    _name_key,
    _ou_selection,
    _parse_handicap_outcome,
    _round_line,
    _team_match,
    _tokens,
    get_stake_overlay_map,
    match_overlay,
)
from bet_placer.markets.labels import format_market_label, market_category
from bet_placer.models.enums import MarketType

logger = logging.getLogger(__name__)


class _Probe:
    """Minimal shape for is_generic_trap()."""

    def __init__(self, market, selection, line, odds):
        self.market = market
        self.selection = selection
        self.line = line
        self.odds = odds


def _verdict(our_p: float | None, odds: float, is_trap: bool) -> dict:
    """Plain-language call on a SINGLE outcome at the given price.

    No jargon: we translate the value math into words a non-bettor gets.
    `ev_pct` is kept in the payload for internal use but the UI shows words.
    """
    if our_p is None:
        return {
            "tier": "unrated", "icon": "•", "label": "No read", "tone": "neutral",
            "blurb": "We don't have a read on this one.", "ev_pct": None,
        }
    ev_pct = (our_p * odds - 1.0) * 100.0

    if is_trap:
        tier, icon, label, tone = "trap", "⚠️", "Trap", "warn"
        blurb = "Wins a lot but the payout barely beats your stake — not worth it."
    elif our_p < 0.18:
        tier, icon, label, tone = "longshot", "🎲", "Long shot", "warn"
        blurb = "Unlikely to happen — only for fun money."
    elif ev_pct >= 6 and our_p >= 0.45:
        tier, icon, label, tone = "great", "✅", "Great price", "good"
        blurb = "Better odds than this should be — we'd back it."
    elif ev_pct >= 2:
        tier, icon, label, tone = "good", "👍", "Good price", "good"
        blurb = "A touch better than fair — worth a look."
    elif ev_pct >= -3:
        tier, icon, label, tone = "fair", "≈", "Fair price", "neutral"
        blurb = "Priced about right — no real edge either way."
    else:
        tier, icon, label, tone = "avoid", "❌", "Bad price", "bad"
        blurb = "The bookie has the edge here — we'd skip it."

    return {
        "tier": tier, "icon": icon, "label": label, "tone": tone,
        "blurb": blurb, "ev_pct": round(ev_pct, 1),
    }


def _model_lookups(match, probabilities, budget_inr, human_context):
    """Build (calibrated, raw) probability lookups keyed by (market, sel, line)."""
    calibrated: dict[tuple, dict] = {}
    for o in analyze_all_options(match, probabilities, budget_inr, human_context):
        so = serialize_option(o)
        key = (so["market"], so["selection"], _round_line(so["line"]))
        calibrated[key] = so

    raw: dict[tuple, float] = {}
    for p in probabilities:
        key = (p.market.value, p.selection, _round_line(p.line))
        raw.setdefault(key, p.probability)

    return calibrated, raw


def _our_prob(market, selection, line, calibrated, raw):
    key = (market, selection, _round_line(line))
    if key in calibrated:
        return calibrated[key].get("our_probability"), calibrated[key]
    if key in raw:
        return raw[key], None
    return None, None


def _dc_selection(outcome_name: str, home: str, away: str) -> str | None:
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


def _map_stake_outcome(market_name, outcome_name, line, home, away):
    """Map a Stake (market, outcome) to our (market_value, selection, line)."""
    name = market_name
    sel = outcome_name.strip()
    low = sel.lower()
    if name == "1x2":
        if _team_match(sel, home):
            return ("match_winner", "home", None)
        if _team_match(sel, away):
            return ("match_winner", "away", None)
        if low in ("draw", "x"):
            return ("match_winner", "draw", None)
        return None
    if name == "Double Chance":
        s = _dc_selection(sel, home, away)
        return ("double_chance", s, None) if s else None
    if name == "Draw No Bet":
        if _team_match(sel, home):
            return ("draw_no_bet", "home", None)
        if _team_match(sel, away):
            return ("draw_no_bet", "away", None)
        return None
    if name == "Asian Total":
        s = _ou_selection(sel)
        return ("over_under_goals", s, line) if s else None
    if name == "Both Teams to Score":
        if low == "yes":
            return ("btts", "yes", None)
        if low == "no":
            return ("btts", "no", None)
        return None
    if name == "Asian Handicap":
        team, hcp = _parse_handicap_outcome(sel)
        if hcp is None:
            return None
        if _team_match(team, home):
            return ("asian_handicap", "home", hcp)
        if _team_match(team, away):
            return ("asian_handicap", "away", hcp)
        return None
    if name in ("Total Corners", "Asian Corners"):
        s = _ou_selection(sel)
        return ("corners", s, line) if s else None
    if name == "Total Bookings":
        s = _ou_selection(sel)
        return ("cards", s, line) if s else None
    nl = name.lower()
    if "goalscorer" in nl or nl in ("1st goal", "last goal") or (
        "to score" in nl and "team" not in nl and "both" not in nl
    ):
        if low in ("no goalscorer", "no", "yes", "none"):
            return None
        return ("player_goal", sel, None)
    return None


# Friendly category names for grouping the menu (Stake-style sections).
_CATEGORY_ORDER = [
    "Match Result",
    "Handicap",
    "Total Goals",
    "Both Teams To Score",
    "Combos",
    "Correct Score",
    "Halves",
    "Goalscorers",
    "Corners",
    "Cards",
    "Other",
]


def _categorize(group: str, name: str) -> str:
    """Sort a Stake market into a clean, Stake-style section. Order matters."""
    n = (name or "").lower()
    g = (group or "").lower()
    if "&" in (name or ""):
        return "Combos"
    if "correct score" in n:
        return "Correct Score"
    if "corner" in n or g == "corners":
        return "Corners"
    if "booking" in n or "card" in n or g == "cards":
        return "Cards"
    if n.startswith("1st half") or n.startswith("2nd half") or "highest scoring half" in n:
        return "Halves"
    if "both teams to score" in n:
        return "Both Teams To Score"
    if "goalscorer" in n or "to score" in n or n in ("1st goal", "last goal"):
        return "Goalscorers"
    if "handicap" in n:
        return "Handicap"
    if n in ("1x2", "1x2 (1up)", "1x2 (2up)") or "double chance" in n or "draw no bet" in n or "halftime/fulltime" in n:
        return "Match Result"
    if "total" in n or "exact goals" in n or "clean sheet" in n or "odd/even" in n:
        return "Total Goals"
    return "Other"


def _build_from_stake(fixture, match, calibrated, raw, budget_inr, home, away):
    """Annotate EVERY Stake market outcome with our model read."""
    cats: dict[str, dict] = {}
    seen: set[tuple] = set()

    try:
        mm = MatchModel(match, home, away)
    except Exception:
        mm = None
    try:
        pm = PlayerModel(mm, home, away) if mm is not None else None
    except Exception:
        pm = None

    for mk in fixture.markets:
        for oc in mk.outcomes:
            key = (mk.name, mk.line, oc.name)
            if key in seen:
                continue
            seen.add(key)
            odds = round(float(oc.odds), 2)
            if odds <= 1.0:
                continue

            mapped = _map_stake_outcome(mk.name, oc.name, mk.line, home, away)
            our_p = None
            read = None
            if mapped:
                m, s, ln = mapped
                if m == "player_goal":
                    if pm is not None:
                        our_p = pm.rate(mk.name, s)
                    if our_p is None:
                        our_p, read = _player_prob(s, calibrated, raw)
                else:
                    our_p, read = _our_prob(m, s, ln, calibrated, raw)

            # Fallback: derive the probability straight from the score matrix so
            # handicaps, combos, correct scores, halves, corners & cards all get
            # an honest read instead of "no read".
            if our_p is None and mm is not None:
                try:
                    p = rate_outcome(mm, mk.name, oc.name, mk.line, home, away)
                except Exception:
                    p = None
                if p is not None and 0.0 <= p <= 1.0:
                    our_p = p

            # Fold in what the model has LEARNED from real results (goal/result
            # markets only — player props are a different, high-variance beast).
            if not (mapped and mapped[0] == "player_goal"):
                our_p = calibrate_prob(our_p, mk.name)

            is_trap = bool(mapped) and is_generic_trap(
                _Probe(mapped[0], mapped[1], mapped[2], odds)
            )
            verdict = _verdict(our_p, odds, is_trap)
            cat = _categorize(getattr(mk, "group", ""), mk.name)
            entry = cats.setdefault(cat, {"category": cat, "markets": {}})
            mk_label = _stake_market_label(mk.name, mk.line)
            mrow = entry["markets"].setdefault(mk_label, {"market_label": mk_label, "outcomes": []})
            mrow["outcomes"].append(_outcome_payload(
                market=(mapped[0] if mapped else mk.name),
                selection=(mapped[1] if mapped else oc.name),
                line=(mapped[2] if mapped else mk.line),
                label=_pretty_outcome(mk.name, oc.name, mk.line, home, away),
                odds=odds,
                our_p=our_p,
                verdict=verdict,
                budget_inr=budget_inr,
                read=read,
                source="stake",
            ))
    return _finalize_cats(cats)


def _build_from_model(match, calibrated, raw, budget_inr, home, away):
    """Fallback: our full modelled catalog when Stake is unreachable."""
    cats: dict[str, dict] = {}
    seen: set[tuple] = set()
    try:
        pm = PlayerModel(MatchModel(match, home, away), home, away)
    except Exception:
        pm = None
    for od in match.market_odds:
        odds = round(float(od.best_odds), 2)
        if odds <= 1.0:
            continue
        market = od.market.value if hasattr(od.market, "value") else str(od.market)
        dedupe_key = (market, od.selection, _round_line(od.line))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        our_p, read = _our_prob(market, od.selection, od.line, calibrated, raw)
        if our_p is None and od.market == MarketType.PLAYER_GOAL:
            if pm is not None:
                our_p = pm.rate("Anytime Goalscorer", od.selection)
            if our_p is None:
                our_p, read = _player_prob(od.selection, calibrated, raw)
        is_trap = is_generic_trap(_Probe(market, od.selection, od.line, odds))
        verdict = _verdict(our_p, odds, is_trap)
        cat = _model_category(od.market)
        entry = cats.setdefault(cat, {"category": cat, "markets": {}})
        mk_label = _model_market_label(od.market, od.line)
        mrow = entry["markets"].setdefault(mk_label, {"market_label": mk_label, "outcomes": []})
        mrow["outcomes"].append(_outcome_payload(
            market=market,
            selection=od.selection,
            line=od.line,
            label=format_market_label(
                od.market, od.selection, od.line, home, away,
                player=od.selection if od.market == MarketType.PLAYER_GOAL else None,
            ),
            odds=odds,
            our_p=our_p,
            verdict=verdict,
            budget_inr=budget_inr,
            read=read,
            source="model",
        ))
    return _finalize_cats(cats)


def _outcome_payload(market, selection, line, label, odds, our_p, verdict, budget_inr, read, source):
    payout = round(budget_inr * odds)
    return {
        "market": market,
        "selection": selection,
        "line": line,
        "label": label,
        "odds": odds,
        "source": source,
        "our_probability": round(our_p, 4) if our_p is not None else None,
        "our_probability_pct": round(our_p * 100, 1) if our_p is not None else None,
        "implied_pct": round(100.0 / odds, 1),
        "verdict": verdict,
        "reason": (read or {}).get("reason") if read else None,
        "payout_inr": payout,
        "profit_inr": payout - round(budget_inr),
    }


def _player_prob(name, calibrated, raw):
    nk = _name_key(name)
    for key, so in calibrated.items():
        if key[0] == "player_goal" and _name_key(key[1]) == nk:
            return so.get("our_probability"), so
    for key, p in raw.items():
        if key[0] == "player_goal" and _name_key(key[1]) == nk:
            return p, None
    return None, None


def _pretty_outcome(market_name, outcome_name, line, home, away):
    sel = outcome_name.strip()
    if market_name == "Asian Total":
        return f"{sel}"
    if market_name == "Both Teams to Score":
        return f"Both score: {sel}"
    if market_name == "Draw No Bet":
        return f"{sel} (draw = refund)"
    if market_name in ("Total Corners", "Asian Corners"):
        return f"{sel} corners"
    if market_name == "Total Bookings":
        return f"{sel} cards"
    if market_name == "Anytime Goalscorer":
        return f"{sel} to score"
    return sel


def _stake_market_label(name, line):
    base = {
        "1x2": "Match Winner (1X2)",
        "Double Chance": "Double Chance",
        "Draw No Bet": "Draw No Bet",
        "Asian Total": "Total Goals",
        "Both Teams to Score": "Both Teams To Score",
        "Asian Handicap": "Asian Handicap",
        "Anytime Goalscorer": "Anytime Goalscorer",
        "Total Corners": "Total Corners",
        "Asian Corners": "Asian Corners",
        "Total Bookings": "Total Cards",
    }.get(name, name)
    # NOTE: do NOT append the line — all lines of an Asian market collapse into
    # ONE market so the UI can render a single Over/Under (or Home/Away) table,
    # exactly like Stake (instead of a separate dropdown per line).
    return base


def _model_category(market: MarketType) -> str:
    return {
        MarketType.MATCH_WINNER: "Match Result",
        MarketType.DOUBLE_CHANCE: "Match Result",
        MarketType.DRAW_NO_BET: "Match Result",
        MarketType.OVER_UNDER_GOALS: "Total Goals",
        MarketType.BTTS: "Both Teams To Score",
        MarketType.ASIAN_HANDICAP: "Handicap",
        MarketType.PLAYER_GOAL: "Goalscorers",
        MarketType.CORNERS: "Corners",
        MarketType.CARDS: "Cards",
        MarketType.EXACT_SCORE: "Correct Score",
        MarketType.HALF_TIME: "Halves",
    }.get(market, "Other")


def _model_market_label(market: MarketType, line) -> str:
    base = {
        MarketType.MATCH_WINNER: "Match Winner (1X2)",
        MarketType.DOUBLE_CHANCE: "Double Chance",
        MarketType.DRAW_NO_BET: "Draw No Bet",
        MarketType.OVER_UNDER_GOALS: "Total Goals",
        MarketType.BTTS: "Both Teams To Score",
        MarketType.ASIAN_HANDICAP: "Asian Handicap",
        MarketType.PLAYER_GOAL: "Anytime Goalscorer",
        MarketType.CORNERS: "Total Corners",
        MarketType.CARDS: "Total Cards",
        MarketType.EXACT_SCORE: "Correct Score",
        MarketType.HALF_TIME: "Half Time Result",
    }.get(market, str(market))
    # Lines collapse into one table-market (see _stake_market_label).
    return base


def _finalize_cats(cats: dict) -> list[dict]:
    out = []

    def emit(cat: str, data: dict):
        markets = list(data["markets"].values())
        for m in markets:
            label = m["market_label"].lower()
            # Player lists read best most-likely-first; everything else keeps
            # Stake's natural outcome order so it mirrors the real sportsbook.
            if "goalscorer" in label or "to be carded" in label or "to score" in label:
                m["outcomes"].sort(key=lambda o: o["odds"])
        out.append({"category": cat, "markets": markets})

    for cat in _CATEGORY_ORDER:
        if cat in cats:
            emit(cat, cats[cat])
    for cat, data in cats.items():
        if cat not in _CATEGORY_ORDER:
            emit(cat, data)
    return out


def _attach_market_stats(categories: list[dict]) -> None:
    """De-vig each *complete* market to a fair price, then judge each outcome on
    true edge (our prob − fair prob) instead of EV vs the vig-inflated odds.

    This kills the 'phantom value' bug where a high-odds long-shot looked like
    +150% EV just because our model disagreed slightly with a big price.
    """
    from collections import defaultdict
    for c in categories:
        for m in c["markets"]:
            # Group by line so Over/Under (and each handicap line) de-vig as a
            # complementary pair, while 1x2 / correct-score de-vig as a whole.
            by_line: dict = defaultdict(list)
            for o in m["outcomes"]:
                by_line[o.get("line")].append(o)
            for group in by_line.values():
                inv = [1.0 / o["odds"] for o in group if o.get("odds", 0) > 1.0]
                overround = sum(inv) if inv else 0.0
                # 2-/3-way pairs and score grids overround < ~1.8; independent
                # 'anytime' player lists overround far higher → skip those.
                complete = len(group) >= 2 and 1.0 < overround <= 1.8
                for o in group:
                    fair = (1.0 / o["odds"]) / overround if (complete and o.get("odds", 0) > 1.0) else None
                    o["fair_prob"] = round(fair, 4) if fair is not None else None
                    p = o.get("our_probability")
                    # Market blend: a sharp book aggregates huge information, so our
                    # honest estimate is mostly the model, pulled toward the de-vigged
                    # price. This shrinks edges → we only flag a bet when we genuinely
                    # disagree with the market, not on model noise.
                    if p is not None and fair is not None:
                        blended = 0.62 * p + 0.38 * fair
                        o["model_prob"] = round(p, 4)
                        o["model_prob_pct"] = round(p * 100, 1)
                        o["our_probability"] = round(blended, 4)
                        o["our_probability_pct"] = round(blended * 100, 1)
                        p = blended
                    o["edge_pct"] = round((p - fair) * 100, 1) if (p is not None and fair is not None) else None
                    o["verdict"] = _refine_verdict(p, o["odds"], fair, o.get("verdict"))


def _refine_verdict(our_p, odds, fair_p, prior) -> dict:
    """Edge-aware verdict. Falls back to the EV-based prior when we can't de-vig."""
    if our_p is None:
        return prior or {"tier": "unrated", "icon": "•", "label": "No read",
                         "tone": "neutral", "blurb": "We don't have a read on this one.", "ev_pct": None}
    ev_pct = round((our_p * odds - 1.0) * 100.0, 1)
    if fair_p is None:
        v = dict(prior or {})
        v["ev_pct"] = ev_pct
        v["edge_pct"] = None
        return v
    edge = (our_p - fair_p) * 100.0
    if our_p < 0.12:
        tier, icon, label, tone = "longshot", "🎲", "Long shot", "warn"
        blurb = "Unlikely — fun money only, even if the price looks generous."
    elif our_p >= 0.85 and odds <= 1.2:
        tier, icon, label, tone = "trap", "⚠️", "Skip", "warn"
        blurb = "Wins often but the payout barely beats your stake."
    elif edge > 18:
        tier, icon, label, tone = "good", "🔎", "Check the line", "neutral"
        blurb = "Our model likes this far more than the price — verify the line before trusting it."
    elif edge >= 4 and our_p >= 0.25 and odds <= 4.5:
        tier, icon, label, tone = "great", "✅", "Great price", "good"
        blurb = f"About {edge:.0f}% better than the fair price — we'd back it."
    elif edge >= 1.5:
        tier, icon, label, tone = "good", "👍", "Good price", "good"
        blurb = "A touch better than fair — worth a look."
    elif edge >= -2:
        tier, icon, label, tone = "fair", "≈", "Fair price", "neutral"
        blurb = "Priced about right — no real edge either way."
    else:
        tier, icon, label, tone = "avoid", "❌", "Bad price", "bad"
        blurb = "The book has the edge here — we'd skip it."
    return {"tier": tier, "icon": icon, "label": label, "tone": tone,
            "blurb": blurb, "ev_pct": ev_pct, "edge_pct": round(edge, 1)}


def build_bet_menu(home: str, away: str, budget_inr: float = 300.0) -> dict:
    """Full annotated bet menu for one match. Real Stake odds when reachable,
    else our complete modelled catalog. Always returns something usable."""
    from bet_placer.data.worldcup2026 import get_all_group_matches
    from bet_placer.engine.worldcup_pipeline import wc_match_to_analysis_match

    wc = _find_wc_match(home, away, get_all_group_matches())
    if not wc:
        return {
            "available": False,
            "reason": f"Couldn't find {home} vs {away} in the World Cup fixtures.",
            "categories": [],
        }

    match = wc_match_to_analysis_match(wc)
    from bet_placer.engine.all_markets import predict_all_markets
    probabilities = predict_all_markets(match)
    human_context = {
        "team_strength": {
            "home": get_team_rating(wc.home),
            "away": get_team_rating(wc.away),
        },
        "home_must_win": wc.home_must_win,
        "away_must_win": wc.away_must_win,
    }
    calibrated, raw = _model_lookups(match, probabilities, budget_inr, human_context)

    fixture = None
    source = "model"
    if wc.status in ("upcoming", "live"):
        try:
            # Reuse the warm, shared 45s overlay cache (same path the main
            # pipeline uses) so this stays fast instead of a fresh Stake call.
            overlay_map = get_stake_overlay_map()
            fixture = match_overlay(wc.home, wc.away, overlay_map)
        except Exception as exc:
            logger.warning("Bet-builder: Stake overlay failed for %s vs %s: %s", home, away, exc)

    if fixture and fixture.markets:
        categories = _build_from_stake(fixture, match, calibrated, raw, budget_inr, wc.home, wc.away)
        source = "stake"
    else:
        categories = _build_from_model(match, calibrated, raw, budget_inr, wc.home, wc.away)

    # De-vig every market → true edge + edge-aware verdicts, then recommend.
    _attach_market_stats(categories)

    # Analyst intuition + recommendations resolved against this same board.
    from bet_placer.engine.analyst_read import analyst_read
    from bet_placer.engine.game_profile import profile_match
    try:
        gp = profile_match(match, probabilities, human_context)
        read = analyst_read(wc.home, wc.away, gp)
        flat = _flatten_outcomes(categories)
        thesis = _match_thesis(flat, wc.home, wc.away)
        recommended = _resolve_recommendations(flat, thesis, read, wc.home, wc.away)
        # "Easy money" = we're confident AND a genuine-value pick exists (price edge,
        # not just a short favourite). Otherwise it's a lean or a skip.
        if thesis:
            has_value = any("Value" in (p.get("tag") or "") for p in recommended)
            tier = (thesis.get("confidence") or {}).get("tier")
            thesis["easy_money"] = bool(tier in ("lock", "strong") and has_value)
        parlay = _parlay_advice(recommended)
    except Exception as exc:
        logger.warning("Analyst read failed for %s vs %s: %s", home, away, exc)
        gp, read, recommended, parlay, thesis = None, None, [], None, None

    wp = {p.selection: p.probability for p in probabilities if p.market == MarketType.MATCH_WINNER}
    total = (wp.get("home", 0) + wp.get("draw", 0) + wp.get("away", 0)) or 1.0

    total_fields = sum(len(m["outcomes"]) for c in categories for m in c["markets"])
    return {
        "available": True,
        "source": source,
        "home": wc.home,
        "away": wc.away,
        "match_name": f"{wc.home} vs {wc.away}",
        "budget_inr": round(budget_inr),
        "field_count": total_fields,
        "group": wc.group,
        "status": wc.status,
        "kickoff": wc.kickoff.isoformat() if getattr(wc, "kickoff", None) else None,
        "win_probability": {
            "home": round(wp.get("home", 0) / total, 3),
            "draw": round(wp.get("draw", 0) / total, 3),
            "away": round(wp.get("away", 0) / total, 3),
        },
        "game_profile": gp,
        "analyst_read": read,
        "match_read": thesis,
        "recommended_picks": recommended,
        "best_parlay": parlay,
        "parlay_caution": _PARLAY_CAUTION,
        "categories": categories,
        "note": (
            "Live Stake prices — pick any bets and we'll grade your slip."
            if source == "stake"
            else "Stake unreachable — modelled prices shown. Verify exact odds on Stake before betting."
        ),
        "stake_url": "https://stake.com/sports/soccer",
    }


def _find_wc_match(home: str, away: str, matches: list):
    for m in matches:
        same = _team_match(home, m.home) and _team_match(away, m.away)
        flip = _team_match(home, m.away) and _team_match(away, m.home)
        if same or flip:
            return m
    return None


# ---------------------------------------------------------------------------
# Recommendations resolved against the SAME market board the user bets on, so
# "our picks" and the bet slip are always the same underlying outcomes.
# ---------------------------------------------------------------------------

def _flatten_outcomes(categories: list[dict]) -> list[dict]:
    flat = []
    for c in categories:
        for m in c["markets"]:
            for o in m["outcomes"]:
                flat.append({**o, "market_label": m["market_label"], "category": c["category"]})
    return flat


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def _name_match(a: str, b: str) -> bool:
    """Match players by SURNAME (last token), not first name — so 'Luis Díaz'
    never matches 'Luis Suárez'."""
    ak = _name_key(_strip_accents(a))
    bk = _name_key(_strip_accents(b))
    if ak == bk:
        return True
    at = _strip_accents(a).lower().replace(",", " ").split()
    bt = _strip_accents(b).lower().replace(",", " ").split()
    if not at or not bt:
        return False
    return at[-1] == bt[-1] and len(at[-1]) > 2


def _find_outcome(flat, market, selection=None, line=None, player=None):
    if player:
        cands = [o for o in flat if o["market"] == "player_goal" and _name_match(o["selection"], player)]
    else:
        cands = [o for o in flat if o["market"] == market]
        if selection is not None:
            cands = [o for o in cands if o["selection"] == selection]
    cands = [o for o in cands if o["odds"] > 1.12 and (o.get("verdict") or {}).get("tier") not in ("trap", "longshot")]
    if not cands:
        return None
    if line is not None:
        cands.sort(key=lambda o: (abs((o["line"] if o["line"] is not None else 0) - line), -(o["our_probability"] or 0)))
    else:
        # prefer genuine edge (de-vigged), not phantom EV on big prices
        cands.sort(key=lambda o: -(o.get("edge_pct") if o.get("edge_pct") is not None else -999))
    return cands[0]


def _ev_of(o):
    return (o.get("verdict") or {}).get("ev_pct")


def _rec_family(o) -> str:
    """Group similar bets so we never recommend 3 versions of the same thing."""
    m = o.get("market")
    if m == "over_under_goals":
        return "totals"
    if m in ("match_winner", "double_chance", "draw_no_bet"):
        return "result"
    if m == "btts":
        return "btts"
    if m == "player_goal":
        return f"scorer:{_name_key(o.get('selection', ''))}"
    return m or "other"


# Markets we model well enough to actually bet on. Team-totals, half-markets,
# corner/card ranges and exotic grids stay on the board for manual betting but
# are NEVER auto-recommended — that's where our model disagrees wildly with a
# sharp book (the "98% / +50% edge" phantoms) and loses money.
_CORE_REC_MARKETS = {
    "match_winner", "double_chance", "draw_no_bet",
    "over_under_goals", "btts", "asian_handicap", "corners", "cards",
}


def _is_core_rec(o, home, away) -> bool:
    if o.get("market") not in _CORE_REC_MARKETS:
        return False
    ml = (o.get("market_label") or "").lower()
    # Drop team-specific totals and split/segment markets from recommendations.
    if any(t in ml for t in ("1st half", "2nd half", "half -", "range", "first half", "second half")):
        return False
    if _team_match_loose(home, ml) or _team_match_loose(away, ml):
        return False
    return True


def _team_match_loose(team: str, text: str) -> bool:
    t = _strip_accents(team).lower()
    return t in text or any(w in text for w in t.split() if len(w) > 3)


_REC_ELIGIBLE_MARKETS = {
    "match_winner", "double_chance", "draw_no_bet", "over_under_goals",
    "btts", "asian_handicap", "corners", "cards",
}


def _is_rec_eligible(o, home, away) -> bool:
    """Broader than core: include team totals & handicaps so we engage with more
    of Stake's board. The plausibility + sane-edge filters (in the resolver) cull
    the markets our model can't price, so this stays safe."""
    import re
    if o.get("market") not in _REC_ELIGIBLE_MARKETS:
        return False
    ml = (o.get("market_label") or "").lower()
    if any(t in ml for t in ("1st half", "2nd half", "half -", "range",
                             "first half", "second half", "odd", "exact")):
        return False
    sel = (o.get("selection") or "").strip()
    if re.fullmatch(r"\d+\s*[-–]\s*\d+", sel):   # correct-score-like "5-6"
        return False
    return True


def _sel_side(sel: str, home: str, away: str):
    """Which side a selection backs, even when it's embedded ('Brazil to Win',
    'Korea Republic', 'Mexico (0.75)'). Returns 'home' / 'away' / 'draw' / None."""
    s = _strip_accents(sel or "").lower().strip()
    if s in ("home", "away", "draw"):
        return s
    if "draw" in s or s in ("x", "tie"):
        return "draw"
    ch = _strip_accents(home).lower()
    ca = _strip_accents(away).lower()
    if any(w in s for w in ch.split() if len(w) > 3):
        return "home"
    if any(w in s for w in ca.split() if len(w) > 3):
        return "away"
    if _team_match(sel, home):
        return "home"
    if _team_match(sel, away):
        return "away"
    return None


def _axis_dir(o, home, away):
    """Map an outcome to (axis, direction) so we can spot contradictions."""
    m = o.get("market")
    s = (o.get("selection") or "").lower()
    if m == "match_winner":
        return ("result", _sel_side(o.get("selection", ""), home, away) or "draw")
    if m in ("draw_no_bet", "asian_handicap"):
        side = _sel_side(o.get("selection", ""), home, away)
        if side in ("home", "away"):
            return ("result", side)
    if m == "double_chance":
        side = _sel_side(o.get("selection", ""), home, away)
        if "draw" in s and side in ("home", "away"):
            return ("result", side)
        return ("result", "nodraw")
    if m == "over_under_goals":
        return ("goals", "over" if "over" in s else "under")
    if m == "btts":
        return ("btts", "yes" if "yes" in s else "no")
    if m == "corners":
        return ("corners", "over" if "over" in s else "under")
    if m == "cards":
        return ("cards", "over" if "over" in s else "under")
    return (m or "other", "-")


def _match_thesis(flat, home, away) -> dict:
    """Study THIS match: who we favour, the goals lean, the BTTS lean — derived
    from the calibrated full-match markets. Recommendations must agree with it."""
    res = {}
    for o in flat:
        if o.get("market") == "match_winner" and o.get("our_probability") is not None:
            res[_axis_dir(o, home, away)[1]] = o["our_probability"]

    def core_prob(market, line, side):
        for o in flat:
            if (o.get("market") == market and o.get("line") == line
                    and _is_core_rec(o, home, away)
                    and side in (o.get("selection") or "").lower()):
                return o.get("our_probability")
        return None

    over25 = core_prob("over_under_goals", 2.5, "over")
    btts_yes = None
    for o in flat:
        if o.get("market") == "btts" and "yes" in (o.get("selection") or "").lower():
            btts_yes = o.get("our_probability")
            break

    fav = max(res, key=res.get) if res else None
    fav_pct = res.get(fav) if fav else None
    result_dir = fav if (fav in ("home", "away") and fav_pct and fav_pct >= 0.45) else None
    goals_dir = ("over" if (over25 is not None and over25 >= 0.58)
                 else "under" if (over25 is not None and over25 <= 0.42) else None)
    btts_dir = ("yes" if (btts_yes is not None and btts_yes >= 0.58)
                else "no" if (btts_yes is not None and btts_yes <= 0.42) else None)

    fav_name = home if result_dir == "home" else away if result_dir == "away" else None
    if result_dir and fav_pct and fav_pct >= 0.62:
        lead = f"We make {fav_name} clear favourites (~{round(fav_pct*100)}%)."
    elif result_dir:
        lead = f"Slight lean to {fav_name} (~{round(fav_pct*100)}%), but it's close."
    else:
        lead = "Too close to call — no side has a real edge."
    goal_txt = ("Leaning a higher-scoring game." if goals_dir == "over"
                else "Leaning a tight, low-scoring game." if goals_dir == "under" else "")
    conf = _confidence_for(fav_pct)
    return {
        "favorite": fav_name, "favorite_pct": round(fav_pct * 100) if fav_pct else None,
        "result_dir": result_dir, "goals_dir": goals_dir, "btts_dir": btts_dir,
        "over25_pct": round(over25 * 100) if over25 is not None else None,
        "btts_yes_pct": round(btts_yes * 100) if btts_yes is not None else None,
        "confidence": conf,
        "easy_money": False,   # set true later only if a confident pick ALSO has value
        "summary": (lead + (" " + goal_txt if goal_txt else "")).strip(),
    }


def _confidence_for(fav_pct) -> dict | None:
    """Map the favourite's (model+market) probability to a confidence tier and the
    model's REAL historical hit-rate at that confidence (so the badge is honest)."""
    if not fav_pct:
        return {"tier": "coinflip", "label": "Coin-flip", "hit_pct": None,
                "note": "No side stands out — usually a skip."}
    try:
        from bet_placer.ml.params import load_params
        tiers = ((load_params().get("report") or {}).get("confident")) or {}
    except Exception:
        tiers = {}

    def hit(key, fallback):
        c = tiers.get(key)
        return round(c["accuracy"] * 100) if c and c.get("accuracy") else fallback

    p = fav_pct * 100
    if p >= 70:
        h = hit("70", 80)
        return {"tier": "lock", "label": "High-confidence spot", "hit_pct": h,
                "note": f"When we're this sure, our pick lands ~{h}% of the time. A spot to actually bet."}
    if p >= 62:
        h = hit("65", 77)
        return {"tier": "strong", "label": "Strong lean", "hit_pct": h,
                "note": f"Confident here — historically right ~{h}% at this level."}
    if p >= 55:
        h = hit("60", 74)
        return {"tier": "lean", "label": "Slight lean", "hit_pct": h,
                "note": f"A lean, not a lock — right ~{h}% at this confidence. Stake small or skip."}
    return {"tier": "coinflip", "label": "Coin-flip", "hit_pct": None,
            "note": "Too close to call — best left alone unless there's a price edge."}


def _resolve_recommendations(flat, thesis, read, home, away) -> list[dict]:
    """Coherent, match-specific, money-aware picks.

    Rules that build trust:
      • only well-modelled CORE markets (no phantom team-total edges),
      • only outcomes where our model is in the same ballpark as the price
        (a sharp book isn't off by 30% — that's our error, not value),
      • one pick per axis and never two that contradict each other / the thesis,
      • lead with genuine +EV value; never recommend a negative-EV bet as 'value'.
    """
    picks: list[dict] = []
    axis_dir: dict = {}   # axis -> chosen direction (coherence lock)

    def implied(o):
        return 1.0 / o["odds"] if o.get("odds", 0) > 1.0 else 1.0

    def plausible(o):
        p = o.get("our_probability")
        return p is not None and abs(p - implied(o)) <= 0.22

    strong_fav = (thesis.get("favorite_pct") or 0) >= 60
    AXIS_CAP = {"result": 2, "goals": 2}   # everything else: 1
    MAX_PICKS = 6
    axis_count: dict = {}
    used_labels: set = set()

    def _team_total(o):
        ml = (o.get("market_label") or "").lower()
        return _team_match_loose(home, ml) or _team_match_loose(away, ml)

    def dedup_key(o):
        return (o.get("market_label") or o.get("market") or "").lower()

    def aligned(o):
        axis, d = _axis_dir(o, home, away)
        if dedup_key(o) in used_labels:           # never the same market twice
            return False
        tdir = {"result": thesis.get("result_dir"), "goals": thesis.get("goals_dir"),
                "btts": thesis.get("btts_dir")}.get(axis)
        if tdir is not None and d != tdir and d != "nodraw":
            return False
        if axis in axis_dir and axis_dir[axis] != d:
            return False
        if axis_count.get(axis, 0) >= AXIS_CAP.get(axis, 1):
            return False
        if axis == "btts":
            gdir = thesis.get("goals_dir") or axis_dir.get("goals")
            if d == "no" and gdir == "over" and not strong_fav:
                return False
            if d == "yes" and gdir == "under":
                return False
        if axis == "goals" and d == "over" and axis_dir.get("btts") == "no" and not strong_fav:
            return False
        if axis in ("corners", "cards") and any(
                _axis_dir(p, home, away)[0] in ("corners", "cards") for p in picks):
            return False
        return True

    def push(o, why, tag):
        axis, d = _axis_dir(o, home, away)
        axis_dir[axis] = d
        axis_count[axis] = axis_count.get(axis, 0) + 1
        used_labels.add(dedup_key(o))
        picks.append({**o, "why": why, "tag": tag, "reason": why})

    pool = [o for o in flat
            if _is_rec_eligible(o, home, away) and plausible(o) and o.get("odds", 0) >= 1.25
            and (o.get("our_probability") or 0) >= 0.30]

    # 1) VALUE — genuine, *sane* edge (a sharp book is never off by >10%). Keep a
    #    probability floor so we never lead with a sub-coin-flip longshot.
    value = sorted(
        [o for o in pool
         if 1.5 <= (o.get("edge_pct") or -99) <= 10
         and (o.get("verdict") or {}).get("ev_pct", -99) >= 1.0
         and (o.get("our_probability") or 0) >= 0.45],
        key=lambda o: -(o.get("edge_pct") or -99),
    )
    for o in value:
        if len(picks) >= MAX_PICKS:
            break
        if aligned(o):
            edge = round(o.get("edge_pct") or 0)
            pct = round((o.get("our_probability") or 0) * 100)
            scope = " on the team total" if _team_total(o) else ""
            push(o, f"Genuine value{scope} — our model makes this ~{edge}% better than the fair "
                    f"price, and it still lands ~{pct}% of the time.", "💰 Value")

    # 2) MODEL LEAN — thesis-aligned, fairly priced (not -EV), broadening the slate
    #    across more of the board. Honest: our read, not a guaranteed price edge.
    leans = sorted(
        [o for o in pool
         if (o.get("verdict") or {}).get("ev_pct", -99) >= -3
         and (o.get("our_probability") or 0) >= 0.50],
        key=lambda o: -(o.get("our_probability") or 0),
    )
    for o in leans:
        if len(picks) >= MAX_PICKS:
            break
        axis, _d = _axis_dir(o, home, away)
        # only lean on a primary axis the thesis actually has a view on
        if axis in ("result", "goals", "btts") and not thesis.get(f"{axis}_dir") \
           and not _team_total(o):
            continue
        if aligned(o):
            pct = round((o.get("our_probability") or 0) * 100)
            push(o, f"Our read for this match — about {pct}% by our model, at a fair price. "
                    "Solid, but no extra value in the odds.", "📌 Model lean")

    # 3) PLAYER read — optional fun shout, never contradicts, clearly caveated.
    if picks and len(picks) < MAX_PICKS:
        scorers = sorted(
            [o for o in flat if o.get("market") == "player_goal"
             and (o.get("our_probability") or 0) >= 0.33 and o.get("odds", 0) >= 1.6
             and (o.get("verdict") or {}).get("tier") not in ("trap",)],
            key=lambda o: -(o.get("our_probability") or 0),
        )
        if scorers:
            o = scorers[0]
            pct = round((o.get("our_probability") or 0) * 100)
            push(o, f"Most likely scorer (~{pct}%). Scorer prices carry a steep margin, so a small, "
                    "fun stake only — not a value play.", "⭐ Player flutter")

    return picks


def _parlay_advice(picks: list[dict]) -> dict | None:
    """Build the *strongest* multi from our singles, but front-load the caution:
    every leg must land, and same-match legs are correlated."""
    safe = sorted(
        [p for p in picks if (p.get("our_probability") or 0) >= 0.45 and p["odds"] >= 1.2],
        key=lambda o: -(o.get("our_probability") or 0),
    )
    # avoid stacking two legs from the same market family (highly correlated / often conflicting)
    legs: list[dict] = []
    fams: set = set()
    for p in safe:
        fam = _rec_family(p)
        if fam in fams:
            continue
        fams.add(fam)
        legs.append(p)
        if len(legs) >= 3:
            break
    if len(legs) < 2:
        return None
    prob = 1.0
    odds = 1.0
    for p in legs:
        prob *= (p.get("our_probability") or 0)
        odds *= p["odds"]
    pct = round(prob * 100)
    return {
        "legs": [{"label": p["label"], "market_label": p.get("market_label"), "odds": p["odds"],
                  "our_probability_pct": round((p.get("our_probability") or 0) * 100)} for p in legs],
        "combined_odds": round(odds, 2),
        "combined_prob_pct": pct,
        "recommendation": "single" if pct < 35 else "ok",
        "message": (
            f"If you really want a multi, this is the strongest we'd build — but all {len(legs)} legs "
            f"must land (~{pct}% by our model, and same-match legs are correlated, so treat that as "
            "optimistic). Backing these as singles is the safer long-run play."
        ),
    }


_PARLAY_CAUTION = (
    "Parlays multiply the price and the risk: every leg has to win. Same-match combos look "
    "tempting but the legs move together and the book trims the odds — most of the time, singles "
    "give you a better long-run return. We'll always show you the best singles first."
)
