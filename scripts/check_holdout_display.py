"""ponytail: holdout display must not treat empty epochs as 0% ROI."""
from bet_placer.ml.model_insights import _live_holdout_roi


def main() -> None:
    assert _live_holdout_roi({"bets": 0, "holdout_roi": 0.0, "holdout_accuracy": None}) is None
    assert _live_holdout_roi({"bets": 12, "holdout_roi": 0.031, "holdout_accuracy": 0.7}) == 0.031
    print("ok")


if __name__ == "__main__":
    main()
