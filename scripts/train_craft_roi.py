#!/usr/bin/env python3
"""Train craft until ROI gates clear. Restarts on crash so training keeps going."""
from __future__ import annotations

import traceback
from time import sleep

from bet_placer.ml.craft_store import set_meta
from bet_placer.ml.craft_train import TARGET_ACC, TARGET_ROI, train_until_roi


def main() -> None:
    while True:
        set_meta("train_status", {
            "state": "running",
            "epoch": 0,
            "target_roi": TARGET_ROI,
            "target_accuracy": TARGET_ACC,
            "unlimited": True,
            "note": "≥10k/sport · overall≥25% · each sport ROI>0 · monthly not red · boards+paired",
        })
        try:
            result = train_until_roi(
                target_roi=TARGET_ROI,
                target_acc=TARGET_ACC,
                max_epochs=None,
                bankroll=10_000,
                match_budget=200,
                verbose=True,
            )
            best = result.get("best") or {}
            print(
                "DONE hit_target=", result.get("hit_target"),
                "best_roi=", best.get("roi"),
                "best_acc=", best.get("accuracy"),
                "epoch=", best.get("epoch"),
                "bets=", best.get("bets"),
                "gates=", result.get("gates"),
                flush=True,
            )
            if result.get("hit_target"):
                return
            # Finished without hit only if capped — keep going
            print("gates not cleared — restarting loop", flush=True)
            sleep(2)
        except Exception:
            traceback.print_exc()
            print("craft crash — restarting in 5s", flush=True)
            sleep(5)


if __name__ == "__main__":
    main()
