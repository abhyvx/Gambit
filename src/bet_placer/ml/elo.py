from __future__ import annotations

from bet_placer.models.types import Match


def _league_blob(match: Match) -> str:
    return f"{getattr(match, 'league', '')} {getattr(match, 'id', '')}".lower()


def _sport_from_match(match: Match) -> str:
    key = str(getattr(match, "sport_key", "") or getattr(match, "id", "") or "").lower()
    # Prefer explicit sport_key prefix — avoids "test"/"odi" substring traps in league names
    if key.startswith("basketball") or key.startswith("nba") or key.startswith("wnba"):
        return "basketball"
    if key.startswith("cricket"):
        return "cricket"
    if key.startswith("soccer") or key.startswith("football"):
        return "soccer"
    blob = f"{key} {_league_blob(match)}"
    if any(k in blob for k in ("nba", "wnba", "ncaa", "fiba", "nbl", "basketball")):
        return "basketball"
    # Word-ish cricket markers (avoid bare "test" matching "contest" / league "Test")
    if any(k in blob for k in ("cricket", "ipl", "t20", "t20i", " bbl", "bbl ", "hundred", "psl", "cpl")):
        return "cricket"
    if "odi" in blob.split() or "test match" in blob or "test cricket" in blob:
        return "cricket"
    return "soccer"


class EloModel:
    """ELO match outcomes — loads learned ratings from model params when present."""

    K = 32
    HOME_ADVANTAGE = 100

    def __init__(self):
        self.ratings: dict[str, float] = {}
        self._by_sport: dict[str, dict[str, float]] = {}
        self._load_learned()

    def _load_learned(self) -> None:
        try:
            from bet_placer.data.team_names import canon_team
            from bet_placer.ml.params import load_params
            p = load_params()
            elo = p.get("elo") or {}
            self.ratings = {canon_team(k): float(v) for k, v in elo.items() if v}
            self._by_sport = {
                s: {canon_team(k): float(v) for k, v in (tbl or {}).items() if v}
                for s, tbl in (p.get("elo_by_sport") or {}).items()
            }
        except Exception:
            self._by_sport = {}

    def get_rating(self, team: str, sport: str | None = None) -> float:
        from bet_placer.data.team_names import canon_team
        key = canon_team(team)
        if sport and sport in (self._by_sport or {}):
            hit = self._by_sport[sport].get(key)
            if hit is not None:
                return hit
        return self.ratings.get(key, 1500.0)

    def predict(self, match: Match) -> dict[str, float]:
        sport = _sport_from_match(match)
        home_r = self.get_rating(match.home_team, sport) + (
            55 if sport == "basketball" else 20 if sport == "cricket" else self.HOME_ADVANTAGE
        )
        away_r = self.get_rating(match.away_team, sport)
        diff = home_r - away_r
        home_exp = 1 / (1 + 10 ** (-diff / 400))
        away_exp = 1 - home_exp
        if sport in ("basketball", "cricket"):
            draw = 0.02  # rare / n/a — keep tiny mass for normalize
        else:
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
