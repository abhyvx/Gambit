"""Rate EVERY Stake market — fan language, team quality matters, MD1 is just one signal."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bet_placer.engine.bankroll import recommend_match_stake
from bet_placer.engine.game_profile import is_generic_trap
from bet_placer.engine.ev import compute_ev, _fair_implied
from bet_placer.engine.plain_language import (
    chance_label,
    odds_simple,
    payout_text,
    recommendation_plain,
    stake_advice,
    value_label,
)
from bet_placer.markets.labels import format_market_label, is_core_bet_market, market_category
from bet_placer.models.enums import MarketType
from bet_placer.models.types import MarketOdds, Match, ProbabilityEstimate

logger = logging.getLogger(__name__)


@dataclass
class _TrapProbe:
    """Lightweight view of a candidate bet for is_generic_trap() checks."""
    market: str
    selection: str
    line: float | None
    odds: float


@dataclass
class MarketOption:
    category: str
    market: str
    selection: str
    line: float | None
    label: str
    odds: float
    stake_payout: float
    our_probability: float
    book_implied: float
    fair_implied: float
    edge_pct: float
    ev_pct: float
    recommendation: str
    stake_inr: float
    reason: str
    human_factors: list[str]
    # Plain English for non-bettors
    plain_verdict: str
    plain_chance: str
    plain_payout: str
    plain_value: str
    stake_payout_text: str
    source: str = "book"


def analyze_all_options(
    match: Match,
    probabilities: list[ProbabilityEstimate],
    budget_per_match_inr: float,
    human_context: dict | None = None,
) -> list[MarketOption]:
    human_context = human_context or {}
    options: list[MarketOption] = []
    team_strength = human_context.get("team_strength", {})

    for prob in probabilities:
        odds_row = _find_odds(match.market_odds, prob)
        if not odds_row:
            continue
        # Model-fabricated prices (bookmaker_count=0) invent circular "edge" — never surface them.
        if int(getattr(odds_row, "bookmaker_count", 1) or 0) <= 0:
            continue

        if prob.market == MarketType.PLAYER_GOAL:
            from bet_placer.data.team_stars import player_goal_eligible
            if not player_goal_eligible(match.home_team, match.away_team, prob.selection):
                continue

        if is_generic_trap(_TrapProbe(
            market=prob.market.value,
            selection=prob.selection,
            line=prob.line,
            odds=odds_row.best_odds,
        )):
            continue

        true_p = prob.probability
        book_impl = odds_row.implied_probability
        try:
            fair_impl = _fair_implied(match.market_odds, prob)
        except Exception:
            # Vig removal can fail when sibling outcomes are missing; the raw
            # book-implied probability is a safe, intentional fallback.
            logger.debug(
                "fair_implied fallback for %s/%s: using book implied",
                prob.market.value, prob.selection, exc_info=True,
            )
            fair_impl = book_impl

        # Calibration: if our model is miscalibrated, it will feel \"off\" vs real
        # book prices. We lightly shrink toward the vig-free book implied based on
        # model confidence (still anchored on our model; not \"what you want to hear\").
        conf = float(getattr(prob, "confidence", 0.65) or 0.65)
        conf = min(0.92, max(0.45, conf))
        w = 0.80 if conf >= 0.7 else 0.68  # higher confidence => trust model more
        cal_p = w * true_p + (1 - w) * fair_impl
        # Corners/cards: Poisson models overstate "safety" — anchor closer to the book.
        if prob.market in (MarketType.CORNERS, MarketType.CARDS):
            cal_p = min(cal_p, fair_impl + 0.04)
            cal_p = max(cal_p, fair_impl - 0.03)
        cal_p = min(0.995, max(0.005, cal_p))

        ev = compute_ev(cal_p, odds_row.best_odds)
        edge = cal_p - fair_impl
        human_notes: list[str] = []

        # Team quality lens — who's actually the better side?
        hs = team_strength.get("home", 50)
        aw = team_strength.get("away", 50)
        if prob.market == MarketType.MATCH_WINNER:
            if prob.selection == "home" and hs > aw + 10:
                human_notes.append(f"{match.home_team} are the stronger team on paper")
            if prob.selection == "away" and aw > hs + 10:
                human_notes.append(f"{match.away_team} have more quality in the squad")
            if prob.selection == "draw" and abs(hs - aw) < 8:
                human_notes.append("Evenly matched — draws happen plenty in group stages")

        if human_context.get("home_must_win") and prob.market == MarketType.MATCH_WINNER:
            if prob.selection == "home":
                human_notes.append(f"{match.home_team} MUST win — they'll attack but nerves are real")
            if prob.selection == "draw":
                human_notes.append("When teams are desperate, draws become less likely")
        if human_context.get("away_must_win") and prob.market == MarketType.MATCH_WINNER:
            if prob.selection == "away":
                human_notes.append(f"{match.away_team} need points badly — open game possible")

        if human_context.get("trending_on"):
            if prob.selection == "home" and human_context["trending_on"] == match.home_team:
                human_notes.append(f"📈 Stake bettors piling on {match.home_team}")
            if human_context.get("fade_public") and prob.selection == "home":
                human_notes.append("Crowd might be overhyping the favourite")

        if human_context.get("fan_take"):
            human_notes.append(human_context["fan_take"])

        rec, reason = _recommend_fan(ev, edge, cal_p, prob.market, prob.line, team_strength, prob.selection, match)

        if prob.market == MarketType.MATCH_WINNER and prob.selection == "draw":
            fav_impl = _heavy_favourite_implied(match)
            if fav_impl and fav_impl > 0.68:
                human_notes.append(f"Bookies make one team a {fav_impl:.0%} favourite — draws are tough here")
                rec = "SKIP"
                reason = "Draw might look tasty but when there's a clear favourite, they usually win."

        stake = 0.0
        if rec == "BET":
            # Soccer-only: extreme goal lines are lottery tickets. BB/cricket totals are huge by design.
            if (
                prob.market == MarketType.OVER_UNDER_GOALS
                and _ou_line_is_lottery(match, prob.line)
            ):
                rec = "SKIP"
                reason = "Long-shot line — fun for a fiver but not a sensible main bet."
            elif edge > 0.15 or ev > 0.15:
                rec = "SKIP"
                reason = "Something's off with this price — check live Stake odds first."
            else:
                rec_stake = recommend_match_stake(
                    cal_p, odds_row.best_odds, 0.6, 0.4, budget_per_match_inr,
                )
                ev_floor = budget_per_match_inr * min(0.40, max(0.10, ev * 2.0))
                stake = min(max(rec_stake.recommended_stake, ev_floor), budget_per_match_inr * 0.45)
                stake = max(0, round(stake / 10) * 10)
                if stake < 20:
                    rec = "SKIP"
                    reason = "Not worth a tiny bet — skip or bump your match budget"
                    stake = 0

        plain_p = payout_text(stake or budget_per_match_inr * 0.2, odds_row.best_odds)
        sport_key = str(getattr(match, "sport_key", "") or "")
        options.append(MarketOption(
            category=market_category(prob.market, prob.line, sport_key),
            market=prob.market.value,
            selection=prob.selection,
            line=prob.line,
            label=format_market_label(
                prob.market, prob.selection, prob.line,
                match.home_team, match.away_team,
                player=prob.selection if prob.market == MarketType.PLAYER_GOAL else None,
                sport=sport_key,
            ),
            odds=odds_row.best_odds,
            stake_payout=round((stake or 50) * odds_row.best_odds),
            our_probability=round(cal_p, 4),
            book_implied=round(book_impl, 4),
            fair_implied=round(fair_impl, 4),
            edge_pct=round(edge * 100, 1),
            ev_pct=round(ev * 100, 1),
            recommendation=rec,
            stake_inr=stake,
            reason=reason,
            human_factors=human_notes,
            plain_verdict=recommendation_plain(rec),
            plain_chance=chance_label(cal_p),
            plain_payout=odds_simple(odds_row.best_odds),
            plain_value=value_label(ev * 100),
            stake_payout_text=plain_p if stake > 0 else f"Stake payout on Stake: {odds_row.best_odds}x your money",
            source=getattr(odds_row, "source", "book"),
        ))

    order = {"BET": 0, "SKIP": 1, "AVOID": 2}
    options.sort(key=lambda o: (order.get(o.recommendation, 9), -o.ev_pct))
    return options


def _match_sport(match: Match) -> str:
    try:
        from bet_placer.ml.elo import _sport_from_match
        return _sport_from_match(match)
    except Exception:
        return "soccer"


def _ou_line_is_lottery(match: Match, line: float | None) -> bool:
    """Soccer 3.5+ goals = lottery. Basketball/cricket use 100+ point/run lines."""
    if line is None:
        return False
    sport = _match_sport(match)
    if sport == "basketball":
        return line < 180 or line > 270
    if sport == "cricket":
        # T20 ~120–200; ODI/Test team totals vary — only reject absurd
        return line < 40 or line > 450
    return line >= 3.5


def _recommend_fan(
    ev: float,
    edge: float,
    prob: float,
    market: MarketType,
    line: float | None,
    team_strength: dict,
    selection: str,
    match: Match,
) -> tuple[str, str]:
    """Decide like a smart fan — value + who actually wins, not robot tail bets."""
    sport = _match_sport(match)

    if ev < -0.02:
        return "AVOID", "Bookies have the advantage here — don't throw money at it."

    if market in (MarketType.EXACT_SCORE,):
        return "SKIP", "Exact score is a lottery — skip unless it's fun money."

    # Soccer-only extreme goal lines — never main picks
    if market == MarketType.OVER_UNDER_GOALS and _ou_line_is_lottery(match, line):
        return "SKIP", "Needs a crazy scoreline — lottery ticket, not a smart bet."

    # Soccer markets that don't exist on BB/cricket boards
    if sport in ("basketball", "cricket") and market in (
        MarketType.BTTS, MarketType.CORNERS, MarketType.CARDS, MarketType.PLAYER_GOAL,
    ):
        return "SKIP", "Not a core market for this sport."
    if sport == "cricket" and market == MarketType.HALF_TIME:
        return "SKIP", "No half-time market for cricket."

    if market == MarketType.PLAYER_GOAL:
        if prob < 0.32:
            return "SKIP", "This scorer is unlikely in THIS game — skip."
        if ev >= 0.02 and prob >= 0.35:
            return "BET", f"Scorer fits this game's attack — {prob:.0%} chance they score."
        if prob >= 0.38:
            return "SKIP", f"Decent chance ({prob:.0%}) but price is fair — only if you fancy them."
        return "AVOID", "Too unlikely for this matchup."

    if market == MarketType.CARDS:
        if prob >= 0.52 and ev >= 0.01:
            return "BET", "Card count suits how heated this game should be."
        return "SKIP", "Cards too unpredictable for this match."

    if market == MarketType.CORNERS:
        if prob >= 0.54 and ev >= 0.02:
            return "BET", "Corner line fits both teams' wide play in THIS game."
        return "SKIP", "Corners not a strong angle here."

    if market == MarketType.MATCH_WINNER:
        hs = team_strength.get("home", 50)
        aw = team_strength.get("away", 50)
        if selection == "draw" and sport in ("basketball", "cricket"):
            return "SKIP", "No draw market in this sport."
        if selection == "home" and hs >= aw + 8 and ev >= 0.02:
            return "BET", f"{match.home_team} should be too good here."
        if selection == "away" and aw >= hs + 8 and ev >= 0.02:
            return "BET", f"{match.away_team} have the quality edge."
        if selection == "draw" and abs(hs - aw) < 10 and ev >= 0.03:
            return "BET", "Even teams — a draw is live at this price."
        if ev >= 0.03:
            return "SKIP", "Tight game — winner bet is a coin flip at this price."

    if market == MarketType.OVER_UNDER_GOALS and line is not None and ev >= 0.02:
        from bet_placer.markets.labels import _total_unit
        unit = _total_unit(line, sport)
        # Soccer: prefer main 1.5–2.5 lines. BB/cricket: any in-band line.
        if sport == "soccer" and line > 2.5:
            pass  # fall through — already handled lottery above for >=3.5
        elif sport == "soccer" and line <= 2.5:
            side = "Over" if "over" in str(selection).lower() else "Under"
            return "BET", f"{side} {line} {unit} fits how these teams play."
        elif sport in ("basketball", "cricket"):
            side = "Over" if "over" in str(selection).lower() else "Under"
            team = ""
            sel = str(selection).lower()
            if sel.startswith("home"):
                team = f"{match.home_team} "
            elif sel.startswith("away"):
                team = f"{match.away_team} "
            return "BET", f"{team}{side} {line} {unit} — line fits the matchup."

    if market == MarketType.BTTS and sport == "soccer" and ev >= 0.02:
        return "BET", "Both teams can score — price looks about right."

    if market == MarketType.CORNERS and sport == "soccer" and line and line <= 10.5 and ev >= 0.03:
        return "BET", "Corner count suits both teams' styles."

    if market == MarketType.ASIAN_HANDICAP and sport in ("basketball", "cricket") and ev >= 0.025:
        team = match.home_team if selection == "home" else match.away_team
        return "BET", f"{team} vs the spread looks priced soft."

    if ev >= 0.03:
        return "BET", "Price looks a touch generous — sensible bet."

    if ev >= 0.01:
        return "SKIP", "Marginal — save it for a clearer spot."

    return "SKIP", "Nothing stands out here."


def _heavy_favourite_implied(match: Match) -> float | None:
    for o in match.market_odds:
        if o.market != MarketType.MATCH_WINNER:
            continue
        if o.selection in ("home", "away") and o.implied_probability > 0.65:
            return o.implied_probability
    return None


def _find_odds(odds_list: list[MarketOdds], prob: ProbabilityEstimate) -> MarketOdds | None:
    for o in odds_list:
        if o.market != prob.market or o.selection != prob.selection:
            continue
        if prob.line is not None and o.line is not None and abs(o.line - prob.line) > 0.01:
            continue
        return o
    return None


def market_option_from_flat(row: dict, budget: float) -> MarketOption | None:
    """Convert a Stake flat-board row into a portfolio MarketOption."""
    market = str(row.get("market") or "")
    label = str(row.get("label") or "")
    if not is_core_bet_market(market):
        if market != "stake_combo":
            return None
    if "&" in market or "&" in label:
        return None
    odds = float(row.get("odds") or 0)
    our_p = row.get("our_probability")
    if our_p is None or odds <= 1.0:
        return None
    market = str(row.get("market") or "")
    if market in ("stake_combo",):
        return None
    selection = str(row.get("selection") or "")
    line = row.get("line")
    label = row.get("label") or f"{selection} {line or ''}".strip()
    book_impl = 1.0 / odds
    fair_impl = book_impl
    our_p = float(our_p)
    ev = compute_ev(our_p, odds)
    edge = our_p - fair_impl
    rec = "SKIP"
    reason = row.get("reason") or "From Stake board."
    verdict = row.get("verdict") or {}
    if verdict.get("tier") in ("great", "good", "value", "strong"):
        rec = "BET"
    elif verdict.get("tier") in ("avoid", "trap", "bad"):
        rec = "AVOID"
    stake = 0.0
    if rec == "BET":
        rec_stake = recommend_match_stake(our_p, odds, 0.65, 0.4, budget)
        stake = rec_stake.recommended_stake
    cat = row.get("category") or market
    return MarketOption(
        category=cat,
        market=market,
        selection=selection,
        line=line,
        label=label,
        odds=odds,
        stake_payout=round(budget * odds),
        our_probability=our_p,
        book_implied=book_impl,
        fair_implied=fair_impl,
        edge_pct=edge * 100,
        ev_pct=verdict.get("ev_pct") if verdict.get("ev_pct") is not None else ev * 100,
        recommendation=rec,
        stake_inr=stake,
        reason=reason,
        human_factors=[],
        plain_verdict=verdict.get("label") or recommendation_plain(rec),
        plain_chance=chance_label(our_p),
        plain_payout=odds_simple(odds),
        plain_value=value_label(ev * 100),
        stake_payout_text=payout_text(stake, odds) if stake else odds_simple(odds),
        source=row.get("source") or "stake",
    )


def options_from_flat_board(flat: list[dict], budget: float) -> list[MarketOption]:
    out: list[MarketOption] = []
    seen: set[tuple] = set()
    for row in flat:
        key = (row.get("market"), row.get("selection"), row.get("line"))
        if key in seen:
            continue
        opt = market_option_from_flat(row, budget)
        if opt:
            seen.add(key)
            out.append(opt)
    return out


def supplement_options_from_overlay(
    options: list[MarketOption],
    overlay: dict,
    match: Match,
    budget: float,
    home: str,
    away: str,
) -> list[MarketOption]:
    """Add Stake-only lines (e.g. cards 1.5) and drop lines Stake doesn't offer."""
    from bet_placer.engine.stake_odds import option_on_stake, _round_line

    if not overlay or not overlay.get("available"):
        return options

    existing = {(o.market, o.selection, _round_line(o.line)) for o in options}
    odds_map = overlay.get("odds", {})
    merged = list(options)

    for m, s, l in overlay.get("available") or []:
        if m == "player_goal":
            continue
        rl = _round_line(l)
        key = (m, s, rl)
        if key in existing:
            continue
        odds = odds_map.get((m, s, l)) or odds_map.get(key)
        if not odds or odds <= 1.0:
            continue
        try:
            mt = MarketType(m)
        except ValueError:
            continue
        label = format_market_label(mt, s, l, home, away)
        book_impl = 1.0 / odds
        our_p = min(0.62, book_impl * 0.96)
        ev = compute_ev(our_p, odds)
        merged.append(MarketOption(
            category=market_category(mt),
            market=m,
            selection=s,
            line=l,
            label=label,
            odds=float(odds),
            stake_payout=round(budget * odds),
            our_probability=our_p,
            book_implied=book_impl,
            fair_implied=book_impl,
            edge_pct=(our_p - book_impl) * 100,
            ev_pct=ev * 100,
            recommendation="SKIP",
            stake_inr=0,
            reason="Stake line — priced from Stake.",
            human_factors=[],
            plain_verdict="From Stake",
            plain_chance=chance_label(our_p),
            plain_payout=odds_simple(odds),
            plain_value=value_label(ev * 100),
            stake_payout_text=odds_simple(odds),
            source="stake",
        ))
        existing.add(key)

    return [
        o for o in merged
        if option_on_stake(o.market, o.selection, o.line, overlay)
    ]


def resolve_portfolio_options(
    match: Match,
    probabilities: list,
    budget: float,
    human_context: dict | None,
    home: str,
    away: str,
) -> list[MarketOption]:
    """Options for portfolio building from the board plus any extra Stake-only lines."""
    from bet_placer.engine.stake_odds import option_on_stake, stake_lines_usable, stake_overlay_ready, hydrate_stake_context

    ctx = hydrate_stake_context(human_context or {}, home, away)
    flat = ctx.get("_flat_board") or []
    board_source = ctx.get("_board_source", "model")
    overlay = ctx.get("stake_overlay")

    if flat:
        options = options_from_flat_board(flat, budget)
    else:
        if not stake_lines_usable(overlay, ctx):
            return []
        options = supplement_options_from_overlay([], overlay, match, budget, home, away)

    # The flat board often misses Stake-only variants/fields; merge those in when we
    # have a live or cached overlay so planning can look beyond the usual 20-30 lines.
    if overlay and stake_lines_usable(overlay, ctx):
        options = supplement_options_from_overlay(options, overlay, match, budget, home, away)

    # Prefer Stake-listed lines when the book is open; if the filter empties
    # (markets not up yet / partial book), keep model options so we don't mass-skip.
    if stake_overlay_ready(overlay):
        on_stake = [
            o for o in options
            if option_on_stake(o.market, o.selection, o.line, overlay)
        ]
        if on_stake:
            return on_stake
    return options


def serialize_option(o: MarketOption) -> dict:
    return {
        "category": o.category,
        "market": o.market,
        "selection": o.selection,
        "line": o.line,
        "label": o.label,
        "odds": o.odds,
        "stake_payout": o.stake_payout,
        "our_probability": o.our_probability,
        "book_implied": o.book_implied,
        "fair_implied": o.fair_implied,
        "edge_pct": o.edge_pct,
        "ev_pct": o.ev_pct,
        "recommendation": o.recommendation,
        "stake_inr": o.stake_inr,
        "reason": o.reason,
        "human_factors": o.human_factors,
        "plain_verdict": o.plain_verdict,
        "plain_chance": o.plain_chance,
        "plain_payout": o.plain_payout,
        "plain_value": o.plain_value,
        "stake_payout_text": o.stake_payout_text,
        "source": o.source,
    }
