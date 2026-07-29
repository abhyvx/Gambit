"""Scan ALL Stake markets and produce probability + odds for each."""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson

from bet_placer.data.team_ratings import TEAM_RATINGS, get_team_rating
from bet_placer.markets.odds import decimal_to_implied
from bet_placer.ml.params import calibrate_prob
from bet_placer.ml.poisson import expected_goals, rebalance_1x2, score_matrix
from bet_placer.models.enums import MarketType
from bet_placer.models.types import MarketOdds, Match, ProbabilityEstimate


def _intel_prop_adjustments(home: str, away: str) -> tuple[float, float]:
    """Corners/cards expectations from scouting intel — not flat baselines."""
    from bet_placer.data.football_intel import get_rivalry, get_team_intel

    hi, ai = get_team_intel(home), get_team_intel(away)
    rivalry = get_rivalry(home, away)
    cards_exp = 3.8
    corners_exp = 10.5
    for intel in (hi, ai):
        if intel["discipline"] == "hot":
            cards_exp += 0.55
        elif intel["discipline"] == "physical":
            cards_exp += 0.25
        if intel["style"] == "possession":
            corners_exp += 0.4
        if intel["tempo"] == "high":
            corners_exp += 0.2
    if rivalry and rivalry.get("intensity", 0) >= 8:
        cards_exp += 0.8
    if hi["style"] == "possession" and ai["style"] in ("defensive", "balanced"):
        corners_exp += 0.6
    if ai["style"] == "possession" and hi["style"] in ("defensive", "balanced"):
        corners_exp += 0.6
    return corners_exp, cards_exp


def generate_all_market_odds(match: Match, base_h2h: tuple[float, float, float] | None = None) -> list[MarketOdds]:
    """Generate realistic odds for every Stake market type from Poisson model + noise."""
    hl, al = expected_goals(match)
    mat = score_matrix(hl, al)
    probs = _derive_all_probs(mat, hl, al)

    odds_list: list[MarketOdds] = []

    def add(market, sel, prob, line=None, margin=0.05):
        fair_odds = 1.0 / max(prob, 0.02)
        book_odds = fair_odds * (1 - margin)  # bookmaker margin
        book_odds = max(1.05, round(book_odds, 2))
        odds_list.append(MarketOdds(
            market=market, selection=sel, line=line,
            best_odds=book_odds, avg_odds=book_odds * 0.98,
            implied_probability=decimal_to_implied(book_odds),
            bookmaker_count=7,
        ))

    # ONE coherent result vector drives 1X2 / Double Chance / DNB / handicap so
    # the board can never contradict itself (e.g. 1X2 favouring one team while
    # DNB favours the other). When market h2h is supplied we blend it with the
    # model, leaning on the model since the fallback h2h is often a placeholder.
    ph, pd, pa = probs["home"], probs["draw"], probs["away"]
    md = None
    if base_h2h:
        mh, md, ma = base_h2h
        w = 0.55  # lean model but respect the market line
        ph = w * ph + (1 - w) * mh
        pd = w * pd + (1 - w) * md
        pa = w * pa + (1 - w) * ma
        s = ph + pd + pa
        if s > 0:
            ph, pd, pa = ph / s, pd / s, pa / s
    gap = 20.0
    if match.home_team in TEAM_RATINGS and match.away_team in TEAM_RATINGS:
        gap = abs(get_team_rating(match.home_team) - get_team_rating(match.away_team))
    ph, pd, pa = rebalance_1x2(ph, pd, pa, market_draw=md, rating_gap=gap)
    # Draw-specific calibration learned from 49k historical games.
    ph = calibrate_prob(ph, "match_winner", "home") or ph
    pd = calibrate_prob(pd, "match_winner", "draw") or pd
    pa = calibrate_prob(pa, "match_winner", "away") or pa
    s = ph + pd + pa
    if s > 0:
        ph, pd, pa = ph / s, pd / s, pa / s

    add(MarketType.MATCH_WINNER, "home", ph, margin=0.04)
    add(MarketType.MATCH_WINNER, "draw", pd, margin=0.04)
    add(MarketType.MATCH_WINNER, "away", pa, margin=0.04)

    # Double chance — exactly consistent with the 1X2 vector above
    add(MarketType.DOUBLE_CHANCE, "home_draw", ph + pd)
    add(MarketType.DOUBLE_CHANCE, "home_away", ph + pa)
    add(MarketType.DOUBLE_CHANCE, "draw_away", pd + pa)

    # Draw no bet (conditional on no draw)
    h_nd = ph / (ph + pa) if (ph + pa) > 0 else 0.5
    add(MarketType.DRAW_NO_BET, "home", h_nd)
    add(MarketType.DRAW_NO_BET, "away", 1 - h_nd)

    # O/U multiple lines
    for line in [0.5, 1.5, 2.0, 2.5, 3.0, 3.5, 4.5]:
        over_p = _over_prob(mat, line)
        add(MarketType.OVER_UNDER_GOALS, "over", over_p, line=line)
        add(MarketType.OVER_UNDER_GOALS, "under", 1 - over_p, line=line)

    # BTTS
    add(MarketType.BTTS, "yes", probs["btts_yes"])
    add(MarketType.BTTS, "no", probs["btts_no"])

    # Corners / cards — intel-adjusted (Uruguay hot, Spain possession, etc.)
    exp_corners, exp_cards = _intel_prop_adjustments(match.home_team, match.away_team)
    exp_corners += (hl + al - 2.5) * 0.8
    for line in [8.5, 9.5, 10.5, 11.5]:
        over_c = 1 - poisson.cdf(line, exp_corners)
        add(MarketType.CORNERS, "over", over_c, line=line)
        add(MarketType.CORNERS, "under", 1 - over_c, line=line)

    for line in [2.5, 3.5, 4.5, 5.5]:
        over_cards = 1 - poisson.cdf(line, exp_cards)
        add(MarketType.CARDS, "over", over_cards, line=line)
        add(MarketType.CARDS, "under", 1 - over_cards, line=line)

    # Half time (approximate — 45% of full time lambda)
    ht_mat = score_matrix(hl * 0.45, al * 0.45)
    add(MarketType.HALF_TIME, "home", float(np.tril(ht_mat, k=-1).sum()))
    add(MarketType.HALF_TIME, "draw", float(np.trace(ht_mat)))
    add(MarketType.HALF_TIME, "away", float(np.triu(ht_mat, k=1).sum()))

    # Correct score top outcomes
    scores = []
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            scores.append((f"{i}-{j}", float(mat[i, j])))
    scores.sort(key=lambda x: -x[1])
    for score_str, p in scores[:11]:
        add(MarketType.EXACT_SCORE, score_str, p, margin=0.12)

    # Asian handicap — consistent with the same result vector
    for line in [-0.5, 0.5, -1.5, 1.5]:
        if line < 0:
            p = ph * 0.85
            add(MarketType.ASIAN_HANDICAP, "home", p, line=line)
            add(MarketType.ASIAN_HANDICAP, "away", 1 - p, line=-line)
        else:
            p = pa * 0.85
            add(MarketType.ASIAN_HANDICAP, "away", p, line=line)
            add(MarketType.ASIAN_HANDICAP, "home", 1 - p, line=-line)

    from bet_placer.data.team_stars import add_player_props
    dummy_est: list = []
    add_player_props(match, odds_list, dummy_est, hl, al)

    return odds_list


def predict_all_markets(match: Match) -> list[ProbabilityEstimate]:
    """True probabilities for every market."""
    hl, al = expected_goals(match)
    mat = score_matrix(hl, al)
    probs = _derive_all_probs(mat, hl, al)
    gap = 20.0
    if match.home_team in TEAM_RATINGS and match.away_team in TEAM_RATINGS:
        gap = abs(get_team_rating(match.home_team) - get_team_rating(match.away_team))
    # Market draw anchor from priced 1X2 if available
    md = None
    for o in match.market_odds or []:
        if o.market == MarketType.MATCH_WINNER and o.selection == "draw":
            md = o.implied_probability
            break
    ph, pd, pa = rebalance_1x2(
        probs["home"], probs["draw"], probs["away"],
        market_draw=md, rating_gap=gap,
    )
    ph = calibrate_prob(ph, "match_winner", "home") or ph
    pd = calibrate_prob(pd, "match_winner", "draw") or pd
    pa = calibrate_prob(pa, "match_winner", "away") or pa
    s = ph + pd + pa
    if s > 0:
        ph, pd, pa = ph / s, pd / s, pa / s
    probs = {**probs, "home": ph, "draw": pd, "away": pa}
    estimates: list[ProbabilityEstimate] = []

    def est(market, sel, prob, line=None, conf=0.65):
        estimates.append(ProbabilityEstimate(
            market=market, selection=sel, line=line,
            probability=prob, confidence=conf,
            model_contributions={"poisson": prob},
        ))

    est(MarketType.MATCH_WINNER, "home", probs["home"], conf=0.75)
    est(MarketType.MATCH_WINNER, "draw", probs["draw"], conf=0.70)
    est(MarketType.MATCH_WINNER, "away", probs["away"], conf=0.75)

    est(MarketType.DOUBLE_CHANCE, "home_draw", probs["home"] + probs["draw"])
    est(MarketType.DOUBLE_CHANCE, "home_away", probs["home"] + probs["away"])
    est(MarketType.DOUBLE_CHANCE, "draw_away", probs["draw"] + probs["away"])

    h_nd = probs["home"] / (probs["home"] + probs["away"]) if (probs["home"] + probs["away"]) > 0 else 0.5
    est(MarketType.DRAW_NO_BET, "home", h_nd)
    est(MarketType.DRAW_NO_BET, "away", 1 - h_nd)

    for line in [0.5, 1.5, 2.0, 2.5, 3.0, 3.5, 4.5]:
        over_p = _over_prob(mat, line)
        est(MarketType.OVER_UNDER_GOALS, "over", over_p, line=line)
        est(MarketType.OVER_UNDER_GOALS, "under", 1 - over_p, line=line)

    est(MarketType.BTTS, "yes", probs["btts_yes"])
    est(MarketType.BTTS, "no", probs["btts_no"])

    exp_corners, exp_cards = _intel_prop_adjustments(match.home_team, match.away_team)
    exp_corners += (hl + al - 2.5) * 0.8
    for line in [8.5, 9.5, 10.5, 11.5]:
        over_c = 1 - poisson.cdf(line, exp_corners)
        est(MarketType.CORNERS, "over", over_c, line=line, conf=0.58)
        est(MarketType.CORNERS, "under", 1 - over_c, line=line, conf=0.58)

    for line in [2.5, 3.5, 4.5, 5.5]:
        over_cards = 1 - poisson.cdf(line, exp_cards)
        est(MarketType.CARDS, "over", over_cards, line=line, conf=0.55)
        est(MarketType.CARDS, "under", 1 - over_cards, line=line, conf=0.55)

    ht_mat = score_matrix(hl * 0.45, al * 0.45)
    est(MarketType.HALF_TIME, "home", float(np.tril(ht_mat, k=-1).sum()), conf=0.60)
    est(MarketType.HALF_TIME, "draw", float(np.trace(ht_mat)), conf=0.60)
    est(MarketType.HALF_TIME, "away", float(np.triu(ht_mat, k=1).sum()), conf=0.60)

    scores = []
    for i in range(min(5, mat.shape[0])):
        for j in range(min(5, mat.shape[1])):
            scores.append((f"{i}-{j}", float(mat[i, j])))
    scores.sort(key=lambda x: -x[1])
    for score_str, p in scores[:11]:
        est(MarketType.EXACT_SCORE, score_str, p, conf=0.50)

    # Asian handicap
    for line in [-0.5, 0.5, -1.5, 1.5]:
        if line < 0:
            p = probs["home"] * 0.85
            est(MarketType.ASIAN_HANDICAP, "home", p, line=line, conf=0.62)
            est(MarketType.ASIAN_HANDICAP, "away", 1 - p, line=-line, conf=0.62)
        else:
            p = probs["away"] * 0.85
            est(MarketType.ASIAN_HANDICAP, "away", p, line=line, conf=0.62)
            est(MarketType.ASIAN_HANDICAP, "home", 1 - p, line=-line, conf=0.62)

    from bet_placer.data.team_stars import add_player_props
    add_player_props(match, [], estimates, hl, al)

    return estimates


def _derive_all_probs(mat: np.ndarray, hl: float, al: float) -> dict[str, float]:
    home = float(np.tril(mat, k=-1).sum())
    draw = float(np.trace(mat))
    away = float(np.triu(mat, k=1).sum())
    btts = 1.0 - float(mat[0, :].sum()) - float(mat[:, 0].sum()) + float(mat[0, 0])
    over_25 = _over_prob(mat, 2.5)
    return {
        "home": home, "draw": draw, "away": away,
        "btts_yes": btts, "btts_no": 1 - btts,
        "over_2.5": over_25, "under_2.5": 1 - over_25,
        "home_lambda": hl, "away_lambda": al,
    }


def _over_prob(mat: np.ndarray, line: float) -> float:
    total = 0.0
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            if i + j > line:
                total += mat[i, j]
    return float(total)
