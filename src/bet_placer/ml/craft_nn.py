"""Small neural net that ranks match gems — sklearn MLP on hand features.

Learns P(hit) from graded paper tickets so craft selection isn't a fixed formula.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from bet_placer.config import data_path

WEIGHTS_PATH = data_path("craft_nn.joblib")
CHAMPION_PATH = data_path("craft_nn_champion.joblib")

_SPORT = {"soccer": 0.0, "basketball": 1.0, "cricket": 2.0}
_KIND = {
    "spotlight": 0.0, "easy_money": 1.0, "niche": 2.0, "card_leg": 3.0, "single": 4.0,
}
_MARKET = {
    "match_winner": 0.0, "moneyline": 0.0, "btts": 1.0, "over_under_goals": 2.0,
    "asian_handicap": 3.0, "handicap": 3.0, "draw_no_bet": 4.0, "double_chance": 5.0,
}


def gem_features(gem: dict, *, sport: str = "soccer") -> list[float]:
    p = float(gem.get("our_probability") or gem.get("true_probability") or 0.5)
    odds = float(gem.get("odds") or gem.get("decimal_odds") or 1.9)
    edge = float(gem.get("edge_pct") or 0) / 100.0
    if not edge and odds > 1:
        edge = p - (1.0 / odds)
    kind = _KIND.get(gem.get("gem_kind") or "single", 4.0)
    market = _MARKET.get((gem.get("market") or "").lower(), 6.0)
    line = gem.get("line")
    line_v = float(line) if line is not None else 0.0
    score = float(gem.get("gem_score") or 1.0)
    return [
        p,
        min(odds, 12.0) / 12.0,
        max(-0.3, min(0.3, edge)),
        kind / 4.0,
        market / 6.0,
        _SPORT.get(sport, 0.0) / 2.0,
        abs(line_v) / 50.0,
        min(score, 2.5) / 2.5,
        1.0 if p >= 0.62 else 0.0,
        1.0 if (gem.get("market") or "") in ("btts", "over_under_goals", "asian_handicap") else 0.0,
    ]


class CraftNet:
    """MLP hit-probability model. Falls back to logistic of gem_score if untrained."""

    def __init__(self):
        self.model = None
        self.n_trained = 0
        self.last_loss = None
        self._load()

    def _load(self) -> None:
        try:
            import joblib
            if not WEIGHTS_PATH.exists():
                return
            blob = joblib.load(WEIGHTS_PATH)
            self.model = blob.get("model")
            self.n_trained = int(blob.get("n_trained") or 0)
            self.last_loss = blob.get("loss")
        except Exception:
            self.model = None

    def save(self, path: Path | None = None) -> None:
        if self.model is None:
            return
        import joblib
        dest = path or WEIGHTS_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self.model, "n_trained": self.n_trained, "loss": self.last_loss},
            dest,
        )

    def save_champion(self) -> None:
        self.save(CHAMPION_PATH)

    def load_champion(self) -> bool:
        try:
            import joblib
            if not CHAMPION_PATH.exists():
                return False
            blob = joblib.load(CHAMPION_PATH)
            self.model = blob.get("model")
            self.n_trained = int(blob.get("n_trained") or 0)
            self.last_loss = blob.get("loss")
            self.save()  # keep live weights = champion
            return self.model is not None
        except Exception:
            return False

    def predict_proba(self, gem: dict, *, sport: str = "soccer") -> float:
        x = np.array([gem_features(gem, sport=sport)], dtype=float)
        if self.model is not None:
            try:
                return float(self.model.predict_proba(x)[0][1])
            except Exception:
                pass
        p = float(gem.get("our_probability") or 0.5)
        s = float(gem.get("gem_score") or 1.0)
        return float(max(0.05, min(0.95, 0.35 * p + 0.35 * min(s, 2) / 2 + 0.15)))

    def fit_tickets(self, tickets: list[dict]) -> float | None:
        rows = [
            t for t in tickets
            if t.get("status") in ("won", "lost") and t.get("our_probability") is not None
        ]
        if len(rows) < 24:
            return None
        # Don't let a pile of losers dominate — balance wins with equal hardest losses
        wins = [t for t in rows if t.get("status") == "won"]
        losses = [t for t in rows if t.get("status") == "lost"]
        if wins and losses:
            losses = sorted(
                losses,
                key=lambda t: -float(t.get("our_probability") or 0),
            )
            # Keep all wins; match with up to 1.25× losses (learn from near-misses)
            n_loss = min(len(losses), max(len(wins), int(len(wins) * 1.25)))
            rows = wins + losses[:n_loss]
        from sklearn.metrics import log_loss
        from sklearn.neural_network import MLPClassifier

        X = np.array([
            gem_features(t, sport=t.get("sport") or "soccer") for t in rows
        ], dtype=float)
        y = np.array([1 if t.get("status") == "won" else 0 for t in rows], dtype=int)
        if len(set(y.tolist())) < 2:
            return None
        clf = MLPClassifier(
            hidden_layer_sizes=(32, 16),
            activation="relu",
            solver="adam",
            alpha=1e-3,
            learning_rate_init=0.01,
            max_iter=250,
            random_state=7,
            early_stopping=len(rows) >= 80,
            validation_fraction=0.15 if len(rows) >= 80 else 0.1,
        )
        clf.fit(X, y)
        self.model = clf
        self.n_trained = len(rows)
        try:
            proba = clf.predict_proba(X)[:, 1]
            self.last_loss = float(log_loss(y, proba, labels=[0, 1]))
        except Exception:
            self.last_loss = None
        self.save()
        return self.last_loss
