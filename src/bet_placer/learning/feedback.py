from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from bet_placer.config import get_settings
from bet_placer.models.types import ModelPerformance, ValueBet


class FeedbackLoop:
    """
    Continuous learning: track predictions vs outcomes, update model weights.
  Persists to data/learning_history.json
    """

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or Path("data/learning_history.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._history: list[dict] = self._load()

    def record_prediction(self, bet: ValueBet, model_contributions: dict[str, float]) -> None:
        self._history.append(
            {
                "match_id": bet.match_id,
                "market": bet.market.value,
                "selection": bet.selection,
                "line": bet.line,
                "true_probability": bet.true_probability,
                "odds": bet.decimal_odds,
                "ev": bet.expected_value,
                "model_contributions": model_contributions,
                "recorded_at": datetime.utcnow().isoformat(),
                "result": None,
                "profit": None,
            }
        )
        self._save()

    def record_result(self, match_id: str, market: str, selection: str, won: bool, profit: float) -> None:
        for entry in self._history:
            if (
                entry["match_id"] == match_id
                and entry["market"] == market
                and entry["selection"] == selection
                and entry["result"] is None
            ):
                entry["result"] = "win" if won else "loss"
                entry["profit"] = profit
        self._save()
        self._update_weights()

    def get_performance_summary(self) -> dict:
        settled = [e for e in self._history if e["result"] is not None]
        if not settled:
            return {"total_bets": 0, "roi": 0.0, "win_rate": 0.0}
        wins = sum(1 for e in settled if e["result"] == "win")
        total_profit = sum(e.get("profit", 0) or 0 for e in settled)
        return {
            "total_bets": len(settled),
            "wins": wins,
            "win_rate": wins / len(settled),
            "total_profit": total_profit,
            "roi": total_profit / len(settled),
        }

    def _update_weights(self) -> None:
        """Adjust ensemble weights based on model Brier scores on settled bets."""
        settled = [e for e in self._history if e["result"] is not None]
        if len(settled) < 20:
            return
        model_errors: dict[str, list[float]] = {}
        for entry in settled:
            actual = 1.0 if entry["result"] == "win" else 0.0
            for model, pred in entry.get("model_contributions", {}).items():
                error = (pred - actual) ** 2
                model_errors.setdefault(model, []).append(error)
        performances: list[ModelPerformance] = []
        for name, errors in model_errors.items():
            brier = sum(errors) / len(errors)
            weight = 1.0 / (brier + 0.01)
            performances.append(ModelPerformance(model_name=name, brier_score=brier, weight=weight))
        total_w = sum(p.weight for p in performances)
        # Weights persisted for next session — user can copy to .env or config
        weights = {p.model_name: p.weight / total_w for p in performances}
        weights_path = self.storage_path.parent / "model_weights.json"
        weights_path.write_text(json.dumps(weights, indent=2))

    def _load(self) -> list[dict]:
        if self.storage_path.exists():
            return json.loads(self.storage_path.read_text())
        return []

    def _save(self) -> None:
        self.storage_path.write_text(json.dumps(self._history, indent=2))
