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

    for line in [1.5, 2.5, 3.5, 4.5, 5.5]:
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


def generate_sport_market_odds(match: Match) -> list[MarketOdds]:
    """Book-shaped prices for every market we model — soccer Poisson or 2-way Elo."""
    from bet_placer.ml.elo import _sport_from_match

    sport = _sport_from_match(match)
    if sport in ("basketball", "cricket"):
        return _odds_from_estimates(_predict_two_way_markets(match, sport), margin=0.045)
    return generate_all_market_odds(match)


def _odds_from_estimates(estimates: list[ProbabilityEstimate], margin: float = 0.05) -> list[MarketOdds]:
    """Turn model probs into placeable decimal odds (small book margin)."""
    out: list[MarketOdds] = []
    for est in estimates:
        p = float(max(0.02, min(0.98, est.probability)))
        book = max(1.05, round((1.0 / p) * (1.0 - margin), 2))
        out.append(MarketOdds(
            market=est.market,
            selection=est.selection,
            line=est.line,
            best_odds=book,
            avg_odds=round(book * 0.98, 2),
            implied_probability=decimal_to_implied(book),
            bookmaker_count=0,  # model-priced — not a scraped book
        ))
    return out


def predict_all_markets(match: Match) -> list[ProbabilityEstimate]:
    """True probabilities for every market we understand for this sport."""
    from bet_placer.ml.elo import _sport_from_match

    sport = _sport_from_match(match)
    if sport in ("basketball", "cricket"):
        return _predict_two_way_markets(match, sport)
    return _predict_soccer_markets(match)


def _predict_two_way_markets(match: Match, sport: str) -> list[ProbabilityEstimate]:
    """Basketball / cricket — moneyline, totals, handicap from Elo + book lean + rest."""
    from bet_placer.ml.elo import EloModel

    elo = EloModel()
    raw = elo.predict(match)
    ph = float(raw["home"])
    pa = float(raw["away"])

    # Blend toward market moneyline when real books are on the match
    mh = ma = None
    for o in match.market_odds or []:
        if o.market != MarketType.MATCH_WINNER:
            continue
        if int(getattr(o, "bookmaker_count", 1) or 0) <= 0:
            continue
        if o.selection == "home":
            mh = float(o.implied_probability or 0)
        elif o.selection == "away":
            ma = float(o.implied_probability or 0)
    if mh and ma and mh + ma > 0.5:
        s = mh + ma
        mh, ma = mh / s, ma / s
        ph = 0.55 * ph + 0.45 * mh
        pa = 0.55 * pa + 0.45 * ma

    # Rest / congestion from external factors when present
    ext = getattr(match, "external", None) or getattr(match, "external_factors", None)
    if ext is not None:
        rh = int(getattr(ext, "rest_days_home", 7) or 7)
        ra = int(getattr(ext, "rest_days_away", 7) or 7)
        # ~1.5% per rest-day gap, capped — tired dogs fade
        rest_bump = max(-0.04, min(0.04, (rh - ra) * 0.008))
        ph = max(0.05, min(0.95, ph + rest_bump))
        pa = 1.0 - ph

    s = ph + pa
    if s > 0:
        ph, pa = ph / s, pa / s
    else:
        ph = pa = 0.5

    estimates: list[ProbabilityEstimate] = []

    def est(market, sel, prob, line=None, conf=0.62):
        estimates.append(ProbabilityEstimate(
            market=market, selection=sel, line=line,
            probability=float(max(0.02, min(0.98, prob))),
            confidence=conf,
            model_contributions={"elo": float(prob)},
        ))

    est(MarketType.MATCH_WINNER, "home", ph, conf=0.74)
    est(MarketType.MATCH_WINNER, "away", pa, conf=0.74)
    est(MarketType.DRAW_NO_BET, "home", ph, conf=0.72)
    est(MarketType.DRAW_NO_BET, "away", pa, conf=0.72)

    if sport == "basketball":
        base_total = 222.0
        # Pace lean: favorites slightly suppress totals when heavy; dogs inflate
        pace_adj = abs(ph - 0.5) * -4.0
        exp_total = base_total + (ph - 0.5) * 4 + pace_adj
        lines = [209.5, 214.5, 219.5, 224.5, 229.5, 234.5]
        spread_lines = [-12.5, -9.5, -6.5, -3.5, -1.5, 1.5, 3.5, 6.5, 9.5, 12.5]
        home_margin = (ph - 0.5) * 18
        home_pts = exp_total * (0.50 + (ph - 0.5) * 0.35)
        away_pts = exp_total - home_pts
        for line in (104.5, 108.5, 112.5, 116.5, 120.5):
            ho = 1.0 / (1.0 + 10 ** ((line - home_pts) / 6.0))
            ao = 1.0 / (1.0 + 10 ** ((line - away_pts) / 6.0))
            est(MarketType.OVER_UNDER_GOALS, "home_over", ho, line=line, conf=0.56)
            est(MarketType.OVER_UNDER_GOALS, "home_under", 1 - ho, line=line, conf=0.56)
            est(MarketType.OVER_UNDER_GOALS, "away_over", ao, line=line, conf=0.56)
            est(MarketType.OVER_UNDER_GOALS, "away_under", 1 - ao, line=line, conf=0.56)
        # 1H moneyline — favorites cover live more often; keep mild
        est(MarketType.HALF_TIME, "home", 0.50 * ph + 0.25, conf=0.52)
        est(MarketType.HALF_TIME, "away", 0.50 * pa + 0.25, conf=0.52)
    else:
        league = str(getattr(match, "league", "") or getattr(match, "id", "") or "").lower()
        t20ish = any(k in league for k in ("t20", "ipl", "bbl", "blast", "hundred", "cpl", "psl"))
        if t20ish:
            base_total = 165.0
            lines = [149.5, 154.5, 159.5, 164.5, 169.5, 174.5]
            spread_lines = [-25.5, -15.5, -5.5, 5.5, 15.5, 25.5]
            home_margin = (ph - 0.5) * 28
            team_lines = [79.5, 84.5, 89.5, 94.5]
        else:
            base_total = 310.0
            lines = [279.5, 289.5, 299.5, 309.5, 319.5, 329.5]
            spread_lines = [-35.5, -20.5, -10.5, 10.5, 20.5, 35.5]
            home_margin = (ph - 0.5) * 35
            team_lines = [149.5, 159.5, 169.5, 179.5]
        exp_total = base_total + (ph - 0.5) * 8
        home_runs = exp_total * (0.50 + (ph - 0.5) * 0.3)
        away_runs = exp_total - home_runs
        for line in team_lines:
            ho = 1.0 / (1.0 + 10 ** ((line - home_runs) / 8.0))
            ao = 1.0 / (1.0 + 10 ** ((line - away_runs) / 8.0))
            est(MarketType.OVER_UNDER_GOALS, "home_over", ho, line=line, conf=0.55)
            est(MarketType.OVER_UNDER_GOALS, "home_under", 1 - ho, line=line, conf=0.55)
            est(MarketType.OVER_UNDER_GOALS, "away_over", ao, line=line, conf=0.55)
            est(MarketType.OVER_UNDER_GOALS, "away_under", 1 - ao, line=line, conf=0.55)

    for line in lines:
        over_p = 1.0 / (1.0 + 10 ** ((line - exp_total) / 10.0))
        est(MarketType.OVER_UNDER_GOALS, "over", over_p, line=line, conf=0.60)
        est(MarketType.OVER_UNDER_GOALS, "under", 1 - over_p, line=line, conf=0.60)

    for line in spread_lines:
        cover = 1.0 / (1.0 + 10 ** ((line - home_margin) / 7.0))
        est(MarketType.ASIAN_HANDICAP, "home", cover, line=line, conf=0.62)
        est(MarketType.ASIAN_HANDICAP, "away", 1 - cover, line=-line, conf=0.62)

    return estimates


def _predict_soccer_markets(match: Match) -> list[ProbabilityEstimate]:
    """Soccer: Poisson goals grid + derived markets."""
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

    for line in [1.5, 2.5, 3.5, 4.5, 5.5]:
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
