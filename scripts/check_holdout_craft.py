"""ponytail: holdout + champion craft self-check.

Run: PYTHONPATH=src python3 scripts/check_holdout_craft.py
"""
from __future__ import annotations


def main() -> None:
    from bet_placer.ml.craft_train import (
        FLOOR_P, TARGET_ACC, HOLDOUT_KEY, CHAMPION_KEY,
        _ensure_holdout, _recent_finished, _split_holdout,
    )
    from bet_placer.ml.craft_store import get_meta
    assert FLOOR_P >= 0.60 and TARGET_ACC >= 0.60

    pool = _recent_finished(3_000)
    h1 = _ensure_holdout(pool, per_sport=200)
    h2 = _ensure_holdout(pool, per_sport=200)
    assert h1.get("ids") == h2.get("ids"), "holdout must be frozen across calls"
    train, ev = _split_holdout(pool, h1)
    assert ev, "holdout eval empty"
    assert not set(g["id"] for g in train) & set(g["id"] for g in ev), "train/eval leak"

    meta = get_meta(HOLDOUT_KEY) or {}
    assert meta.get("ids"), meta

    # Champion helpers importable
    from bet_placer.ml.craft_nn import CraftNet, CHAMPION_PATH
    net = CraftNet()
    assert hasattr(net, "save_champion") and hasattr(net, "load_champion")

    print("check_holdout_craft ok", {
        "holdout_n": meta.get("n"),
        "eval_games": len(ev),
        "train_games": len(train),
        "champion_meta": bool(get_meta(CHAMPION_KEY)),
        "champion_weights": CHAMPION_PATH.exists(),
        "floor": FLOOR_P,
    })


if __name__ == "__main__":
    main()
