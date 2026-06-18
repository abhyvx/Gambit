from __future__ import annotations

import numpy as np

from bet_placer.ml.poisson import expected_goals
from bet_placer.models.types import Match


def simulate_match(match: Match, n_simulations: int = 10000) -> dict[str, float]:
    hl, al = expected_goals(match)
    home_goals = np.random.poisson(hl, n_simulations)
    away_goals = np.random.poisson(al, n_simulations)

    home_wins = np.sum(home_goals > away_goals)
    draws = np.sum(home_goals == away_goals)
    away_wins = np.sum(home_goals < away_goals)
    over_25 = np.sum(home_goals + away_goals > 2.5)
    btts = np.sum((home_goals > 0) & (away_goals > 0))

    n = n_simulations
    return {
        "home": home_wins / n,
        "draw": draws / n,
        "away": away_wins / n,
        "over_2.5": over_25 / n,
        "under_2.5": 1 - over_25 / n,
        "btts_yes": btts / n,
        "btts_no": 1 - btts / n,
    }
