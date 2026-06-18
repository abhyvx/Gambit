from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bet_placer.models.enums import MarketType, MatchContext, Selection


@dataclass
class TeamStats:
    name: str
    goals_scored: float = 0.0
    goals_conceded: float = 0.0
    xg: float = 0.0
    xga: float = 0.0
    shots: float = 0.0
    shots_on_target: float = 0.0
    possession: float = 0.0
    passing_accuracy: float = 0.0
    corners: float = 0.0
    cards: float = 0.0
    fouls: float = 0.0
    pressing_actions: float = 0.0
    set_piece_goals: float = 0.0
    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0
    league_position: int = 0
    form_last_5: list[str] = field(default_factory=list)  # W/D/L
    form_last_10: list[str] = field(default_factory=list)
    form_last_20: list[str] = field(default_factory=list)


@dataclass
class PlayerStatus:
    name: str
    position: str
    injured: bool = False
    suspended: bool = False
    minutes_last_5: float = 0.0
    goals: int = 0
    assists: int = 0
    xg: float = 0.0
    xa: float = 0.0
    form_rating: float = 0.0  # 0-10
    is_key_player: bool = False


@dataclass
class TacticalProfile:
    formation: str = "4-3-3"
    style: str = "balanced"  # possession, counter, high_press, low_block
    avg_possession: float = 50.0
    press_intensity: float = 5.0  # 1-10
    cross_frequency: float = 5.0
    transition_speed: float = 5.0
    set_piece_strength: float = 5.0
    manager_tenure_matches: int = 0
    tactical_flexibility: float = 5.0  # 1-10


@dataclass
class ExternalFactors:
    weather: str = "clear"
    temperature_c: float = 15.0
    wind_speed_kmh: float = 0.0
    humidity_pct: float = 50.0
    rest_days_home: int = 7
    rest_days_away: int = 7
    travel_distance_km: float = 0.0
    timezone_change: int = 0
    fixture_congestion_home: float = 0.0  # 0-1
    fixture_congestion_away: float = 0.0
    crowd_intensity: float = 5.0  # 1-10
    pitch_quality: float = 7.0


@dataclass
class RefereeProfile:
    name: str
    avg_cards_per_match: float = 4.0
    avg_penalties_per_match: float = 0.25
    home_bias: float = 0.0  # -1 to 1
    foul_strictness: float = 5.0  # 1-10


@dataclass
class LeagueProfile:
    name: str
    avg_goals_per_match: float = 2.6
    avg_corners: float = 10.0
    avg_cards: float = 4.0
    home_advantage_factor: float = 0.12  # added to home win prob
    pace: float = 5.0  # 1-10
    defensive_strength: float = 5.0
    variance: float = 0.3


@dataclass
class HeadToHead:
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0
    avg_goals: float = 2.5
    recent_results: list[str] = field(default_factory=list)  # e.g. ["H", "D", "A"]
    btts_rate: float = 0.5
    over_25_rate: float = 0.5


@dataclass
class ChemistrySignals:
    morale_home: float = 5.0  # 1-10
    morale_away: float = 5.0
    momentum_home: float = 5.0
    momentum_away: float = 5.0
    media_pressure_home: float = 5.0
    media_pressure_away: float = 5.0
    new_signings_impact_home: float = 0.0  # -1 to 1
    new_signings_impact_away: float = 0.0
    manager_support_home: float = 5.0
    manager_support_away: float = 5.0
    notes: list[str] = field(default_factory=list)


@dataclass
class OddsSnapshot:
    bookmaker: str
    market: MarketType
    selection: str
    line: float | None  # e.g. 2.5 for O/U
    decimal_odds: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MarketOdds:
    market: MarketType
    selection: str
    line: float | None
    best_odds: float
    avg_odds: float
    implied_probability: float
    opening_odds: float | None = None
    closing_odds: float | None = None
    bookmaker_count: int = 1
    steam_move: bool = False
    reverse_line_movement: bool = False


@dataclass
class Match:
    id: str
    home_team: str
    away_team: str
    league: str
    kickoff: datetime
    home_stats: TeamStats
    away_stats: TeamStats
    home_tactics: TacticalProfile
    away_tactics: TacticalProfile
    home_players: list[PlayerStatus] = field(default_factory=list)
    away_players: list[PlayerStatus] = field(default_factory=list)
    external: ExternalFactors = field(default_factory=ExternalFactors)
    referee: RefereeProfile | None = None
    league_profile: LeagueProfile | None = None
    h2h: HeadToHead = field(default_factory=HeadToHead)
    chemistry: ChemistrySignals = field(default_factory=ChemistrySignals)
    context: MatchContext = MatchContext.NORMAL
    market_odds: list[MarketOdds] = field(default_factory=list)
    sentiment_score_home: float = 0.0  # -1 to 1
    sentiment_score_away: float = 0.0


@dataclass
class ProbabilityEstimate:
    market: MarketType
    selection: str
    line: float | None
    probability: float
    model_contributions: dict[str, float] = field(default_factory=dict)
    intuition_adjustment: float = 0.0
    confidence: float = 0.5


@dataclass
class ValueBet:
    match_id: str
    match_label: str
    market: MarketType
    selection: str
    line: float | None
    decimal_odds: float
    implied_probability: float
    true_probability: float
    expected_value: float
    expected_roi: float
    kelly_stake_pct: float
    confidence: float
    risk_score: float
    variance: float
    rank_score: float
    explanation: str
    factors: list[str] = field(default_factory=list)
    kickoff: datetime | None = None


@dataclass
class ModelPerformance:
    model_name: str
    brier_score: float = 0.0
    log_loss: float = 0.0
    roi: float = 0.0
    bet_count: int = 0
    weight: float = 1.0


@dataclass
class AnalysisResult:
    match: Match
    probabilities: list[ProbabilityEstimate]
    value_bets: list[ValueBet]
    top_bets: list[ValueBet]
    metadata: dict[str, Any] = field(default_factory=dict)
