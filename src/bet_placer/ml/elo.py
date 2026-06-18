from __future__ import annotations

from bet_placer.models.types import Match


class EloModel:
    """Simple ELO-based match outcome model."""

    K = 32
    HOME_ADVANTAGE = 100

    def __init__(self):
        self.ratings: dict[str, float] = {}

    def get_rating(self, team: str) -> float:
        return self.ratings.get(team, 1500.0)

    def predict(self, match: Match) -> dict[str, float]:
        home_r = self.get_rating(match.home_team) + self.HOME_ADVANTAGE
        away_r = self.get_rating(match.away_team)
        diff = home_r - away_r
        home_exp = 1 / (1 + 10 ** (-diff / 400))
        away_exp = 1 - home_exp
        # Draw probability from goal difference compression
        draw = 0.28 * np_exp(-abs(diff) / 200)
        home_win = home_exp * (1 - draw)
        away_win = away_exp * (1 - draw)
        total = home_win + draw + away_win
        return {
            "home": home_win / total,
            "draw": draw / total,
            "away": away_win / total,
        }

    def update(self, home: str, away: str, result: str) -> None:
        """result: 'H', 'D', or 'A'"""
        home_r = self.get_rating(home)
        away_r = self.get_rating(away)
        home_exp = 1 / (1 + 10 ** (-(home_r + self.HOME_ADVANTAGE - away_r) / 400))
        scores = {"H": 1.0, "D": 0.5, "A": 0.0}
        actual = scores[result]
        self.ratings[home] = home_r + self.K * (actual - home_exp)
        self.ratings[away] = away_r + self.K * ((1 - actual) - (1 - home_exp))


def np_exp(x: float) -> float:
    import math
    return math.exp(x)
