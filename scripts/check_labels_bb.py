"""ponytail: labels + BB/cricket OU lottery gate."""
from types import SimpleNamespace

from bet_placer.markets.labels import format_market_label, market_category, _total_unit
from bet_placer.models.enums import MarketType
from bet_placer.engine.market_advisor import _ou_line_is_lottery


def main() -> None:
    assert _total_unit(2.5) == "goals"
    assert _total_unit(112.5, "basketball_nba") == "points"
    assert _total_unit(164.5, "cricket_t20") == "runs"

    lab = format_market_label(
        MarketType.OVER_UNDER_GOALS, "home_over", 112.5, "Lakers", "Celtics",
        sport="basketball_nba",
    )
    assert "Lakers" in lab and "Over" in lab and "points" in lab, lab
    assert market_category("over_under_goals", 224.5, "basketball_nba") == "Totals"
    assert market_category("over_under_goals", 2.5, "soccer_epl") == "Goals"

    bb = SimpleNamespace(sport_key="basketball_nba", id="", league="NBA")
    ck = SimpleNamespace(sport_key="cricket_t20", id="", league="T20")
    soc = SimpleNamespace(sport_key="soccer_epl", id="", league="EPL")
    assert _ou_line_is_lottery(soc, 3.5)
    assert not _ou_line_is_lottery(bb, 224.5)
    assert not _ou_line_is_lottery(ck, 164.5)
    print("labels_bb_ou ok")


if __name__ == "__main__":
    main()
