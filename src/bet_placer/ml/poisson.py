from __future__ import annotations

import math

import numpy as np
from scipy.stats import poisson

from bet_placer.data.team_ratings import TEAM_RATINGS, get_team_rating
from bet_placer.models.types import Match


def expected_goals(match: Match, apply_learned: bool = True) -> tuple[float, float]:
    """Estimate lambda (expected goals) for home and away.

    For World Cup sides we drive the split off the power ratings so a real
    quality gap (Colombia 74 vs Uzbekistan 45) actually shows up as a clear
    favourite instead of a coin-flip. Falls back to the xG/xGA stats model for
    teams we don't rate.

    `apply_learned` folds in the corrections the tracker has learned from real
    results (overall scoring level + home edge). The backtest calls it with
    apply_learned=False so it always fits against the raw model.
    """
    league_avg = match.league_profile.avg_goals_per_match if match.league_profile else 2.55
    ha = match.league_profile.home_advantage_factor if match.league_profile else 0.08

    goals_scale, home_edge_adj = 1.0, 0.0
    if apply_learned:
        try:
            from bet_placer.ml.params import load_params
            lp = load_params()
            goals_scale = float(lp.get("goals_scale", 1.0))
            home_edge_adj = float(lp.get("home_edge_adj", 0.0))
            # Best path: real Elo + goal model learned from 49k historical games.
            elo = lp.get("elo") or {}
            gm = lp.get("goal_model") or {}
            if elo and gm:
                from bet_placer.data.team_names import canon_team
                from bet_placer.ml.historical import lambdas_from_elo
                he = elo.get(canon_team(match.home_team))
                ae = elo.get(canon_team(match.away_team))
                if he is not None and ae is not None:
                    # World Cup is played at neutral venues → minimal home edge.
                    return lambdas_from_elo(he, ae, gm, neutral=True)
        except Exception:
            pass

    rated = match.home_team in TEAM_RATINGS and match.away_team in TEAM_RATINGS
    if rated:
        hr = get_team_rating(match.home_team)
        ar = get_team_rating(match.away_team)
        diff = (hr - ar) / 100.0            # quality gap, ~ -0.5..0.5 at the WC
        sup = diff * 3.4 + ha * 3.0 + home_edge_adj  # goal supremacy incl. home edge
        total = (league_avg - min(0.45, abs(diff) * 0.6)) * goals_scale
        hs = 1.0 / (1.0 + math.exp(-sup))    # home's share of the goals
        return max(0.2, total * hs), max(0.2, total * (1.0 - hs))

    # Generic stats-based fallback.
    h, a = match.home_stats, match.away_stats
    home_attack = h.xg or h.goals_scored
    home_defense = h.xga or h.goals_conceded
    away_attack = a.xg or a.goals_scored
    away_defense = a.xga or a.goals_conceded
    home_lambda = (home_attack + away_defense) / 2 * 0.55 * (league_avg / 2.6) * (1 + ha)
    away_lambda = (away_attack + home_defense) / 2 * 0.45 * (league_avg / 2.6)
    return max(0.3, home_lambda), max(0.3, away_lambda)


def score_matrix(home_lambda: float, away_lambda: float, max_goals: int = 6) -> np.ndarray:
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            matrix[i, j] = poisson.pmf(i, home_lambda) * poisson.pmf(j, away_lambda)
    return matrix / matrix.sum()


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
