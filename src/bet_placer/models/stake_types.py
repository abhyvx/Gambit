from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from bet_placer.models.enums import MarketType, MatchContext, Selection


class Verdict(str, Enum):
    BET = "bet"           # Clear edge — place selective bets
    SKIP = "skip"         # No edge or too risky — avoid
    CAUTION = "caution"   # Mixed signals — only bet top pick with small stake


@dataclass
class StakeOutcome:
    id: str
    name: str
    odds: float
    active: bool = True
    payout_multiplier: float | None = None
    market_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StakeMarket:
    id: str
    name: str
    group: str
    outcomes: list[StakeOutcome]
    line: float | None = None
    specifiers: str = ""
    template: str = ""
    status: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StakeFixture:
    id: str
    name: str
    home_team: str
    away_team: str
    sport: str
    league: str
    status: str
    kickoff: datetime | None
    markets: list[StakeMarket] = field(default_factory=list)
    total_bet_value: float = 0.0
    total_bet_count: int = 0
    total_user_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BettorPick:
    fixture_name: str
    outcome_name: str
    odds: float
    amount_usd: float
    user_name: str
    is_highroller: bool = False
    sport: str = ""
    timestamp: datetime | None = None


@dataclass
class BettorConsensus:
    """Real-time Stake bettor sentiment derived from live bet feed."""
    fixture_name: str
    home_team: str
    away_team: str
    total_volume_usd: float
    pick_distribution: dict[str, float]  # outcome -> % of volume
    pick_count_distribution: dict[str, int]
    highroller_side: str | None
    highroller_volume_usd: float
    sharp_indicator: float  # -1 to 1: positive = sharp money on our likely edge side
    public_side: str | None  # most bet volume
    contrarian_signal: float  # positive = public on one side we might fade
    recent_picks: list[BettorPick] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class WebConsensus:
    """Internet-wide prediction consensus (Reddit, forums, search snippets)."""
    fixture_name: str
    home_pick_pct: float
    draw_pick_pct: float
    away_pick_pct: float
    over_25_pct: float
    btts_yes_pct: float
    source_count: int
    confidence: float  # how much data we found
    dominant_narrative: str
    sources: list[str] = field(default_factory=list)
    fade_public: bool = False  # True when public consensus is extreme


@dataclass
class MatchVerdict:
    verdict: Verdict
    headline: str
    reasoning: list[str]
    best_bet: str | None
    consensus_alignment: str  # "aligned", "neutral", "against", "contrarian_edge"
    stake_markets_scanned: int
    value_bets_found: int
    risk_flags: list[str] = field(default_factory=list)
