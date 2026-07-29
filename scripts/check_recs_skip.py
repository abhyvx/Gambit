"""ponytail: empty Stake catalog falls back to model pool; style comfort used."""
from __future__ import annotations

from bet_placer.engine.bet_portfolio import _should_skip_match, COMFORTABLE_WIN
from bet_placer.engine.bettor_style import BettorStyle


def main() -> None:
    # Style floors differ from the hardcoded comfort constant.
    assert BettorStyle(goal="fun", risk="high").min_probability() < COMFORTABLE_WIN
    assert BettorStyle(goal="preserve", risk="low").min_probability() >= 0.55

    # Empty plans → skip; match_card worth_taking → don't skip.
    assert _should_skip_match({}) is True
    assert _should_skip_match({
        "match_card": [{"worth_taking": True, "hit_probability": 0.2}],
    }) is False
    assert _should_skip_match({
        "singles_focus": [{
            "legs": [{"our_probability": 0.50}],
            "hit_probability": 0.50,
            "likely_profit_inr": 10,
            "ev_pct": 5,
        }],
    }, comfort=0.56) is True
    print("recs_skip_ok")


if __name__ == "__main__":
    main()
