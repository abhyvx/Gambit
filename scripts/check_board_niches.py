"""ponytail: self-check for board fuel + niche ≥60% floors. Run: PYTHONPATH=src python3 scripts/check_board_niches.py"""
from __future__ import annotations


def main() -> None:
    from bet_placer.data.espn_leagues import _cricket_score
    assert _cricket_score("142 & 342") == 484
    assert _cricket_score("125/7") == 125

    from bet_placer.ml.craft_train import FLOOR_P, TARGET_ACC
    assert FLOOR_P >= 0.60 and TARGET_ACC >= 0.60

    from bet_placer.ml.params import load_params
    params = load_params(force=True)
    boards = params.get("trained_on_boards") or {}
    assert int(boards.get("basketball") or 0) >= 500, boards
    assert int(boards.get("cricket") or 0) >= 100, boards
    teams = (params.get("elo_by_sport") or {}).get("basketball") or {}
    assert len(teams) >= 200, f"BB teams {len(teams)} (need NCAA/WNBA depth)"

    acc = (params.get("board_scorecards") or {}).get("accuracy") or {}
    for sport, a in acc.items():
        if a is None:
            continue
        assert float(a) >= 0.60, (sport, a)

    from bet_placer.ml.craft_store import get_meta
    mr = get_meta("market_replay_cache") or params.get("market_replay") or {}
    by_m = mr.get("by_market") or {}
    for need in ("asian_handicap", "draw_no_bet", "corners", "cards", "double_chance"):
        assert need in by_m and int(by_m[need].get("n") or 0) > 0, need
    for name, row in by_m.items():
        n = int(row.get("n") or 0)
        a = row.get("accuracy")
        if n and a is not None:
            assert float(a) >= 0.60, (name, n, a)
    print("check_board_niches ok", {
        "boards": boards,
        "bb_teams": len(teams),
        "board_acc": acc,
        "niches": {k: (by_m[k].get("n"), by_m[k].get("accuracy")) for k in
                   ("asian_handicap", "draw_no_bet", "corners", "cards", "double_chance")},
    })


if __name__ == "__main__":
    main()
