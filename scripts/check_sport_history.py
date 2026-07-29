"""ponytail: sport_history parses cricket info + wires apply helpers without a full download."""
from __future__ import annotations

from bet_placer.ml.sport_history import (
    _mdy_to_iso,
    _parse_info_csv,
    apply_sport_history,
)


def main() -> None:
    assert _mdy_to_iso("11/1/1946") == "1946-11-01"
    sample = """version,2.3.0
info,team,Australia
info,team,Sri Lanka
info,date,2017/02/17
info,winner,Sri Lanka
info,player,Australia,AJ Finch
info,player,Sri Lanka,DAS Gunaratne
"""
    m = _parse_info_csv(sample)
    assert m is not None
    assert m["res"] == "A"
    assert m["date"] == "2017-02-17"
    assert "AJ Finch" in m["home_players"]

    applied = apply_sport_history(
        {},
        {
            "elo_by_sport": {"basketball": {"Lakers": 1600.0}, "cricket": {"India": 1700.0}},
            "player_elo": {"basketball": {"LeBron James": 1650.0}, "cricket": {"V Kohli": 1680.0}},
            "counts": {"basketball": 100, "cricket": 200},
            "player_counts": {"basketball": 1, "cricket": 1},
            "accuracy": {"basketball": 0.6, "cricket": 0.55},
            "sources": {},
        },
    )
    assert applied["elo_by_sport"]["basketball"]["Lakers"] == 1600.0
    assert applied["player_elo"]["cricket"]["V Kohli"] == 1680.0
    assert applied["trained_on_sport_history"]["cricket"] == 200
    print("sport_history_ok")


if __name__ == "__main__":
    main()
