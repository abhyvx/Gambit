"""Analyze real-time Stake bettor activity for consensus signals."""

from __future__ import annotations

import re
from collections import defaultdict

from bet_placer.models.stake_types import BettorConsensus, BettorPick, StakeFixture


def analyze_bettor_consensus(
    fixture: StakeFixture,
    live_bets: list[BettorPick],
    highroller_bets: list[BettorPick],
) -> BettorConsensus:
    home, away = fixture.home_team, fixture.away_team
    fixture_key = _normalize_fixture_name(fixture.name)

    relevant = [
        b for b in live_bets + highroller_bets
        if _matches_fixture(b.fixture_name, home, away, fixture_key)
    ]
    hr_relevant = [b for b in highroller_bets if _matches_fixture(b.fixture_name, home, away, fixture_key)]

    volume_by_outcome: dict[str, float] = defaultdict(float)
    count_by_outcome: dict[str, int] = defaultdict(int)

    for pick in relevant:
        side = _classify_pick(pick.outcome_name, home, away)
        volume_by_outcome[side] += pick.amount_usd
        count_by_outcome[side] += 1

    total_vol = sum(volume_by_outcome.values()) or 1.0
    pick_distribution = {k: v / total_vol for k, v in volume_by_outcome.items()}

    hr_vol: dict[str, float] = defaultdict(float)
    for pick in hr_relevant:
        side = _classify_pick(pick.outcome_name, home, away)
        hr_vol[side] += pick.amount_usd

    public_side = max(volume_by_outcome, key=volume_by_outcome.get) if volume_by_outcome else None
    highroller_side = max(hr_vol, key=hr_vol.get) if hr_vol else None
    hr_total = sum(hr_vol.values())

    notes: list[str] = []
    contrarian_signal = 0.0
    sharp_indicator = 0.0

    if public_side and pick_distribution.get(public_side, 0) > 0.65:
        notes.append(f"Public money heavy on {public_side} ({pick_distribution[public_side]:.0%} of volume)")
        contrarian_signal = pick_distribution[public_side] - 0.5

    if highroller_side and highroller_side != public_side:
        notes.append(f"Highrollers leaning {highroller_side} vs public on {public_side}")
        sharp_indicator = 0.15
    elif highroller_side == public_side and hr_total > 1000:
        notes.append(f"Sharp and public aligned on {public_side}")
        sharp_indicator = 0.08

    if fixture.total_bet_value > 50000:
        notes.append(f"High Stake volume: ${fixture.total_bet_value:,.0f} on this match")

    return BettorConsensus(
        fixture_name=fixture.name,
        home_team=home,
        away_team=away,
        total_volume_usd=total_vol,
        pick_distribution=dict(pick_distribution),
        pick_count_distribution=dict(count_by_outcome),
        highroller_side=highroller_side,
        highroller_volume_usd=hr_total,
        sharp_indicator=sharp_indicator,
        public_side=public_side,
        contrarian_signal=contrarian_signal,
        recent_picks=relevant[:15],
        notes=notes,
    )


def consensus_pick_for_selection(selection: str, home: str, away: str) -> str:
    """Map our internal selection to consensus bucket."""
    if selection in ("home", "draw", "away"):
        return selection
    if selection == "over":
        return "over"
    if selection == "under":
        return "under"
    if selection == "yes":
        return "btts_yes"
    if selection == "no":
        return "btts_no"
    return selection


def consensus_supports_bet(consensus: BettorConsensus, selection: str, market: str) -> float:
    """
    Returns -1 to +1 signal.
    Positive = bettor consensus supports our pick.
    Negative = consensus against (but we may still fade public).
    """
    bucket = consensus_pick_for_selection(selection, consensus.home_team, consensus.away_team)
    public_pct = consensus.pick_distribution.get(bucket, 0)

    if market == "match_winner":
        if public_pct > 0.55:
            return 0.1  # aligned with public
        if consensus.highroller_side == bucket:
            return 0.2
        if consensus.public_side and consensus.public_side != bucket and consensus.contrarian_signal > 0.15:
            return 0.12  # contrarian edge — public on other side
        return -0.05

    return 0.0


def _normalize_fixture_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def _matches_fixture(fixture_name: str, home: str, away: str, key: str) -> bool:
    fn = _normalize_fixture_name(fixture_name)
    if key in fn or fn in key:
        return True
    h = home.lower()
    a = away.lower()
    return h in fn and a in fn


def _classify_pick(outcome_name: str, home: str, away: str) -> str:
    n = outcome_name.lower()
    if "over" in n:
        return "over"
    if "under" in n:
        return "under"
    if "yes" in n and "both" in n:
        return "btts_yes"
    if "draw" in n or n == "x":
        return "draw"
    if home.lower() in n:
        return "home"
    if away.lower() in n:
        return "away"
    home_words = [w for w in home.lower().split() if len(w) > 3]
    away_words = [w for w in away.lower().split() if len(w) > 3]
    if any(w in n for w in home_words):
        return "home"
    if any(w in n for w in away_words):
        return "away"
    return outcome_name.lower()
