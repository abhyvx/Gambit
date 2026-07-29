"""Background craft worker — run on GitHub Actions or any host, not inside the API.

  PYTHONPATH=src python3 scripts/run_craft_worker.py --epochs 20
  PYTHONPATH=src python3 scripts/run_craft_worker.py --full-model  # retrain + craft

Downloads ESPN/history only — does not burn Odds API credits.
"""
from __future__ import annotations

import argparse
import logging
import os


def main() -> None:
    os.environ.setdefault("CRAFT_WORKER", "1")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Craft ROI worker (holdout-evaluated)")
    p.add_argument("--epochs", type=int, default=0, help="Max craft epochs (0 = unlimited until gates)")
    p.add_argument("--full-model", action="store_true", help="Full tracker.train() before craft")
    p.add_argument("--target-roi", type=float, default=0.25)
    p.add_argument("--target-acc", type=float, default=0.60)
    args = p.parse_args()

    if args.full_model:
        from bet_placer.ml.tracker import train
        print("=== FULL MODEL RETRAIN (all sports, no per-team patches) ===")
        rep = train(verbose=True)
        print(
            "trained_on", rep.get("trained_on"),
            "boards", rep.get("trained_on_boards"),
        )

    from bet_placer.ml.craft_store import get_meta, set_meta
    from bet_placer.ml.craft_train import train_until_roi

    # Clear bogus bests from old sentinel runs
    best = get_meta("best_roi") or {}
    if float(best.get("roi") or -1) < 0 or float(best.get("accuracy") or 0) < args.target_acc:
        set_meta("best_roi", {})

    prev = get_meta("train_status") or {}
    set_meta("train_status", {
        **prev,
        "state": "running",
        "owner": "craft_worker",
        "target_roi": args.target_roi,
        "target_accuracy": args.target_acc,
        "unlimited": args.epochs <= 0,
        "note": "holdout-evaluated · learns from losses · sport ledger · notes in craft_notes.log",
    })

    cap = None if args.epochs <= 0 else args.epochs
    print(f"=== CRAFT ({'unlimited' if cap is None else f'max {cap}'} epochs, holdout frozen) ===")
    print("Notes → ~/.bet_placer/craft_notes.log")
    out = train_until_roi(
        target_roi=args.target_roi,
        target_acc=args.target_acc,
        max_epochs=cap,
        verbose=True,
    )
    print("DONE", {
        "hit_target": out.get("hit_target"),
        "best_roi": (out.get("best") or {}).get("roi"),
        "best_acc": (out.get("best") or {}).get("accuracy"),
        "epochs": len(out.get("history") or []),
    })


if __name__ == "__main__":
    main()
