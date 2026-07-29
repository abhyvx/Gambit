"""ponytail: Stake overlay must accept any soccer trending fixture, not WC-only."""
from __future__ import annotations

import inspect

from bet_placer.engine import stake_odds as so
from bet_placer.data import stake_scraper as ss


def main() -> None:
    assert "_is_world_cup" not in inspect.getsource(so.fetch_fast_stake_overlay)
    assert "_is_world_cup" not in inspect.getsource(so.find_stake_fixture)
    assert "_is_world_cup" not in inspect.getsource(ss.StakeScraper.search_fixture_by_teams)
    print("stake_overlay_scope_ok")


if __name__ == "__main__":
    main()
