"""Classify THIS match — drives game-specific bet picks, not generic lines."""

from __future__ import annotations

from bet_placer.models.enums import MarketType
from bet_placer.models.types import Match, ProbabilityEstimate


def profile_match(
    match: Match,
    probabilities: list[ProbabilityEstimate],
    human_context: dict,
) -> dict:
    home = match.home_team
    away = match.away_team
    ctx = human_context or {}
    ts = ctx.get("team_strength", {})
    hs = ts.get("home", 50)
    aw = ts.get("away", 50)
    total_xg = match.home_stats.xg + match.away_stats.xg

    mw = {p.selection: p.probability for p in probabilities if p.market == MarketType.MATCH_WINNER}
    over25 = next((p.probability for p in probabilities if p.market == MarketType.OVER_UNDER_GOALS and p.line == 2.5 and p.selection == "over"), 0.5)
    btts = next((p.probability for p in probabilities if p.market == MarketType.BTTS and p.selection == "yes"), 0.5)

    fav_home = mw.get("home", 0) > max(mw.get("away", 0), mw.get("draw", 0))
    fav_prob = max(mw.get("home", 0), mw.get("away", 0))
    rating_gap = abs(hs - aw)
    chaotic = ctx.get("home_must_win") or ctx.get("away_must_win")

    if rating_gap >= 15 and fav_prob >= 0.55:
        style = "dominant_favorite"
        narrative = f"{'{home}' if fav_home else '{away}'} should control this — pick result markets tied to them, not random overs."
    elif total_xg >= 2.8 and over25 >= 0.52:
        style = "high_scoring"
        narrative = f"Both attacks active (expected {total_xg:.1f} goals) — goals & scorer markets for THIS game, not Under 0.5 nonsense."
    elif total_xg < 2.2 and over25 < 0.48:
        style = "low_scoring"
        narrative = "Tight, cagey game expected — unders, double chance, and defensive angles fit THIS match."
    elif chaotic:
        style = "chaotic"
        narrative = "Must-win pressure — more cards, corners, goals variance. Stick to 55%+ probability picks only."
    elif rating_gap < 8:
        style = "tight"
        narrative = "Evenly matched — double chance and draw-no-bet safer than picking a winner at coin-flip odds."
    else:
        style = "balanced"
        narrative = "Standard group game — pick the highest-probability bets for how THESE two teams play."

    narrative = narrative.replace("{home}", home).replace("{away}", away)

    return {
        "style": style,
        "narrative": narrative,
        "total_xg": round(total_xg, 2),
        "over_25_prob": round(over25, 2),
        "btts_prob": round(btts, 2),
        "favorite": home if fav_home else away,
        "favorite_prob": round(fav_prob, 2),
        "rating_gap": round(rating_gap, 1),
        "chaotic": chaotic,
        "min_bet_probability": 0.58,
        "parlay_min_leg_probability": 0.58,
        "parlay_min_combined": 0.32,
    }


def is_generic_trap(opt) -> bool:
    """Bets that 'win 90% of the time' but are useless or not game-specific."""
    if opt.market == "over_under_goals" and opt.line is not None:
        if opt.selection == "over" and opt.line <= 1.5:
            return True
        if opt.selection == "under" and opt.line >= 4.5:
            return True
    if opt.odds < 1.12:
        return True
    return False


def game_fit_score(opt, profile: dict, home: str, away: str) -> float:
    """How well this bet fits THIS specific game (0-100)."""
    if is_generic_trap(opt):
        return -100

    score = opt.our_probability * 50  # probability is king for loss minimization
    style = profile["style"]

    if style == "dominant_favorite":
        fav = profile["favorite"]
        if fav in opt.label and opt.market in ("match_winner", "double_chance", "draw_no_bet"):
            score += 25
        if opt.market == "over_under_goals" and opt.selection == "over" and opt.line == 2.5:
            score += 10
    elif style == "high_scoring":
        if opt.market == "over_under_goals" and opt.selection == "over" and opt.line in (2.5, 3.5):
            score += 20
        if opt.market == "btts" and opt.selection == "yes":
            score += 15
        if opt.market == "player_goal":
            score += 12
    elif style == "low_scoring":
        if opt.market == "over_under_goals" and opt.selection == "under" and opt.line in (2.5, 3.5):
            score += 22
        if opt.market == "btts" and opt.selection == "no":
            score += 15
        if opt.market == "double_chance":
            score += 10
    elif style == "chaotic":
        if opt.market == "corners" and opt.selection == "over":
            score += 12
        if opt.market == "cards" and opt.selection == "over":
            score += 10
        if opt.market == "over_under_goals" and opt.selection == "over" and opt.line == 2.5:
            score += 8
    elif style == "tight":
        if opt.market == "double_chance":
            score += 25
        if opt.market == "draw_no_bet":
            score += 18
        if opt.market == "match_winner" and opt.selection == "draw":
            score += 8

    if opt.market == "player_goal" and opt.our_probability >= 0.35:
        score += 8
    if opt.recommendation == "BET":
        score += 5
    if opt.recommendation == "AVOID":
        score -= 30

    if opt.market in ("corners", "cards") and style != "chaotic":
        score -= 18

    return score
