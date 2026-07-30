from __future__ import annotations

import math

import numpy as np
from scipy.stats import poisson

from bet_placer.data.team_ratings import TEAM_RATINGS, get_team_rating
from bet_placer.models.types import Match


def expected_goals(match: Match, apply_learned: bool = True) -> tuple[float, float]:
    """Estimate lambda (expected goals) for home and away.

    Club / nation strength comes from learned Elo (with aliases) first. Flat
    league-prior xG (1.45 home / 1.20 away) is a last resort only — never the
    reason an underdog host looks stronger than a top club.
    """
    league_avg = match.league_profile.avg_goals_per_match if match.league_profile else 2.55
    ha = match.league_profile.home_advantage_factor if match.league_profile else 0.08

    goals_scale, home_edge_adj = 1.0, 0.0
    if apply_learned:
        try:
            from bet_placer.data.team_ratings import blended_elo
            from bet_placer.ml.historical import lambdas_from_ad, lambdas_from_elo
            from bet_placer.ml.params import load_params
            from bet_placer.ml.team_elo import resolve_team_elo, sport_from_match

            lp = load_params()
            goals_scale = float(lp.get("goals_scale", 1.0))
            home_edge_adj = float(lp.get("home_edge_adj", 0.0))
            gm = lp.get("goal_model") or {}
            sport = sport_from_match(match)
            he_raw = resolve_team_elo(match.home_team, sport=sport, params=lp)
            ae_raw = resolve_team_elo(match.away_team, sport=sport, params=lp)
            if gm and he_raw is not None and ae_raw is not None:
                he = blended_elo(match.home_team, he_raw)
                ae = blended_elo(match.away_team, ae_raw)
                # World Cup / neutrals → tiny HA; club leagues keep home edge
                blob = f"{getattr(match, 'sport_key', '')} {getattr(match, 'league', '')} {getattr(match, 'id', '')}".lower()
                neutral = any(t in blob for t in ("world_cup", "world cup", "fifa", "neutral", "nations league"))
                ehl, ela = lambdas_from_elo(he, ae, gm, neutral=neutral)
                ad = lp.get("ad_model") or {}
                if ad.get("att"):
                    ahl, ala = lambdas_from_ad(
                        match.home_team, match.away_team, ad, neutral=neutral,
                    )
                    if ahl is not None:
                        w = float(ad.get("w_elo", 1.0))
                        return (w * ehl + (1 - w) * ahl, w * ela + (1 - w) * ala)
                return ehl, ela
        except Exception:
            pass

    # Prefer 0–100 strength ratings over flat board priors
    try:
        hr = get_team_rating(match.home_team)
        ar = get_team_rating(match.away_team)
        if abs(hr - ar) >= 3 or min(hr, ar) < 48 or max(hr, ar) > 52:
            diff = (hr - ar) / 100.0
            sup = diff * 3.4 + ha * 3.0 + home_edge_adj
            total = (league_avg - min(0.45, abs(diff) * 0.6)) * goals_scale
            hs = 1.0 / (1.0 + math.exp(-sup))
            return max(0.2, total * hs), max(0.2, total * (1.0 - hs))
    except Exception:
        pass

    rated = match.home_team in TEAM_RATINGS and match.away_team in TEAM_RATINGS
    if rated:
        hr = get_team_rating(match.home_team)
        ar = get_team_rating(match.away_team)
        diff = (hr - ar) / 100.0
        sup = diff * 3.4 + ha * 3.0 + home_edge_adj
        total = (league_avg - min(0.45, abs(diff) * 0.6)) * goals_scale
        hs = 1.0 / (1.0 + math.exp(-sup))
        hl, al = max(0.2, total * hs), max(0.2, total * (1.0 - hs))
    else:
        h, a = match.home_stats, match.away_stats
        home_attack = h.xg or h.goals_scored
        home_defense = h.xga or h.goals_conceded
        away_attack = a.xg or a.goals_scored
        away_defense = a.xga or a.goals_conceded
        hl = (home_attack + away_defense) / 2 * 0.55 * (league_avg / 2.6) * (1 + ha)
        al = (away_attack + home_defense) / 2 * 0.45 * (league_avg / 2.6)
        hl, al = max(0.3, hl), max(0.3, al)

    chem = match.chemistry
    if chem:
        mh = getattr(chem, "morale_home", None) or 5.0
        ma = getattr(chem, "morale_away", None) or 5.0
        if mh > ma + 1.5:
            hl *= 1.0 + min(0.08, (mh - ma) * 0.015)
        elif ma > mh + 1.5:
            al *= 1.0 + min(0.08, (ma - mh) * 0.015)

    return hl, al


def _dc_rho_default() -> float:
    """Learned Dixon-Coles draw-correlation (negative => more draws)."""
    try:
        from bet_placer.ml.params import load_params
        return float((load_params().get("goal_model") or {}).get("dc_rho", 0.0) or 0.0)
    except Exception:
        return 0.0


def score_matrix(home_lambda: float, away_lambda: float, max_goals: int = 6,
                 rho: float | None = None) -> np.ndarray:
    """Score grid with a Dixon-Coles low-score correction.

    Independent Poisson badly under-counts draws (it ignores that tight games
    clump on 0-0 / 1-1), which makes the model over-back favourites. The DC tau
    re-weights the four low-score cells so P(draw) matches reality.
    """
    if rho is None:
        rho = _dc_rho_default()
    n = max_goals + 1
    ks = np.arange(n)
    matrix = np.outer(poisson.pmf(ks, home_lambda), poisson.pmf(ks, away_lambda))
    if rho:
        matrix = matrix.copy()
        matrix[0, 0] *= 1.0 - home_lambda * away_lambda * rho
        matrix[0, 1] *= 1.0 + home_lambda * rho
        matrix[1, 0] *= 1.0 + away_lambda * rho
        matrix[1, 1] *= 1.0 - rho
        np.clip(matrix, 1e-12, None, out=matrix)
    return matrix / matrix.sum()


def rebalance_1x2(
    ph: float, pd: float, pa: float,
    *,
    market_draw: float | None = None,
    rating_gap: float | None = None,
    both_happy_draw: bool = False,
) -> tuple[float, float, float]:
    """Pull the 1X2 vector toward realistic draw rates.

    Independent Poisson + a single Elo gap still under-price draws in tight
    group games. The market draw line and tournament context carry real signal.
    """
    pd = float(pd)
    if market_draw is not None and market_draw > 0:
        pd = 0.40 * pd + 0.60 * market_draw
    # WC group stage: ~28% of games finish level — floor in open groups.
    if both_happy_draw or (rating_gap is not None and rating_gap < 12):
        pd = max(pd, 0.27)
    top = max(ph, pa)
    if top < 0.52:
        pd = max(pd, 0.30)
    elif top < 0.58 and pd >= 0.22:
        pd = min(0.38, pd * 1.12)
    s = ph + pd + pa
    if s <= 0:
        return ph, pd, pa
    return ph / s, pd / s, pa / s


def match_outcome_probs(match: Match) -> dict[str, float]:
    hl, al = expected_goals(match)
    mat = score_matrix(hl, al)
    home_win = float(np.tril(mat, k=-1).sum())
    draw = float(np.trace(mat))
    away_win = float(np.triu(mat, k=1).sum())
    total_goals = []
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            total_goals.append((i + j, mat[i, j]))
    over_25 = sum(p for g, p in total_goals if g > 2.5)
    btts = float(mat[1:, 1:].sum()) + float(mat[0, 1:].sum()) + float(mat[1:, 0].sum())
    # Fix btts: both score at least 1
    btts = 1.0 - float(mat[0, :].sum()) - float(mat[:, 0].sum()) + float(mat[0, 0])

    return {
        "home": home_win,
        "draw": draw,
        "away": away_win,
        "over_2.5": over_25,
        "under_2.5": 1 - over_25,
        "btts_yes": btts,
        "btts_no": 1 - btts,
        "home_lambda": hl,
        "away_lambda": al,
    }


def corners_prob(match: Match, line: float = 9.5) -> dict[str, float]:
    avg = match.league_profile.avg_corners if match.league_profile else 10.0
    home_c = match.home_stats.corners or avg / 2
    away_c = match.away_stats.corners or avg / 2
    expected = home_c + away_c
    # Poisson approximation for total corners
    over = 1 - poisson.cdf(line, expected)
    return {"over": float(over), "under": float(1 - over), "expected": expected}
