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
from bet_placer.markets.labels import format_market_label, market_category
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
            # Block fake edges on extreme lines (demo odds artifact)
            if prob.line and prob.line >= 3.5 and prob.market == MarketType.OVER_UNDER_GOALS:
                rec = "SKIP"
                reason = "Long-shot goals line — fun for a fiver but not a sensible main bet."
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
        options.append(MarketOption(
            category=market_category(prob.market),
            market=prob.market.value,
            selection=prob.selection,
            line=prob.line,
            label=format_market_label(
                prob.market, prob.selection, prob.line,
                match.home_team, match.away_team,
                player=prob.selection if prob.market == MarketType.PLAYER_GOAL else None,
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
    if ev < -0.02:
        return "AVOID", "Bookies have the advantage here — don't throw money at it."

    if market in (MarketType.EXACT_SCORE,):
        return "SKIP", "Exact score is a lottery — skip unless it's fun money."

    # Extreme goal lines — never main picks
    if market == MarketType.OVER_UNDER_GOALS and line and line >= 3.5:
        return "SKIP", "Needs a crazy scoreline — lottery ticket, not a smart bet."

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
        if selection == "home" and hs >= aw + 8 and ev >= 0.02:
            return "BET", f"{match.home_team} should be too good here."
        if selection == "away" and aw >= hs + 8 and ev >= 0.02:
            return "BET", f"{match.away_team} have the quality edge."
        if selection == "draw" and abs(hs - aw) < 10 and ev >= 0.03:
            return "BET", "Even teams — a draw is live at this price."
        if ev >= 0.03:
            return "SKIP", "Tight game — winner bet is a coin flip at this price."

    if market == MarketType.OVER_UNDER_GOALS and line and line <= 2.5 and ev >= 0.02:
        over_under = "Over" if selection == "over" else "Under"
        return "BET", f"{over_under} {line} goals fits how these teams play."

    if market == MarketType.BTTS and ev >= 0.02:
        return "BET", "Both teams can score — price looks about right."

    if market == MarketType.CORNERS and line and line <= 10.5 and ev >= 0.03:
        return "BET", "Corner count suits both teams' styles."

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
