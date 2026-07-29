"""ponytail: board train returns walk-forward accuracy for all 3 sports."""
from __future__ import annotations

from bet_placer.ml.board_train import apply_board_training, train_from_boards
from bet_placer.ml.params import DEFAULT_PARAMS


def main() -> None:
    rep = train_from_boards()
    assert set(rep["elo_by_sport"]) >= {"soccer", "basketball", "cricket"}
    assert set(rep["accuracy"]) >= {"soccer", "basketball", "cricket"}
    p = apply_board_training(dict(DEFAULT_PARAMS), rep)
    assert "board_scorecards" in p
    assert "accuracy" in p["board_scorecards"]
    print("board_train_ok", rep.get("counts"), rep.get("accuracy"))


if __name__ == "__main__":
    main()
