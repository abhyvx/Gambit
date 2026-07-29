"""Factor graph — the real prediction core (not team Elo alone).

World-class edge comes from estimating P(outcome | context) with an explicit
factor graph, then pricing against the market and grading by closing-line value.

Nodes (entities)
  team, player, manager, referee, club, competition, venue, weather,
  schedule (rest/travel/congestion), ideology (press/block/transition),
  public_money, injury_status

Edges (effects)
  player → team attack/defence contribution
  manager → tactical prior + substitution patterns
  referee → card/penalty rate, home bias
  venue + weather → totals / pace
  schedule → fatigue / rotation risk
  ideology matchup → style clash (press vs sit-deep)

Inference (target)
  Hierarchical Bayesian / variational updates so lower leagues with sparse
  data borrow strength from parent competition + similar playstyles.
  Match state → market probabilities via sport adapters (soccer Poisson /
  basketball possessions / cricket run models).

Decision layer
  User utility (style) × calibrated probs × odds → portfolio policy
  (bandit / constrained Kelly). Not "show everything".

Learning signal
  Closing line value (CLV) and settled P&L beat raw accuracy as the
  objective. Retrain factors when CLV is negative after vig.

This module defines the schema. Training pipelines fill it over time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    TEAM = "team"
    PLAYER = "player"
    MANAGER = "manager"
    REFEREE = "referee"
    CLUB = "club"
    COMPETITION = "competition"
    VENUE = "venue"
    WEATHER = "weather"
    SCHEDULE = "schedule"
    IDEOLOGY = "ideology"
    PUBLIC = "public"
    INJURY = "injury"


class EdgeType(str, Enum):
    PLAYS_FOR = "plays_for"
    MANAGES = "manages"
    OFFICIATES = "officiates"
    HOSTS = "hosts"
    STYLE = "style"
    FATIGUE = "fatigue"
    MARKET = "market"
    CONTRIBUTES = "contributes"


@dataclass
class FactorNode:
    id: str
    kind: NodeType
    name: str
    sport: str = "soccer"
    attrs: dict[str, Any] = field(default_factory=dict)
    # learned latent (filled by trainer)
    embedding: list[float] | None = None


@dataclass
class FactorEdge:
    src: str
    dst: str
    kind: EdgeType
    weight: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchContext:
    """Everything that should condition a single-match prediction."""
    sport: str
    competition: str
    home_team_id: str
    away_team_id: str
    kickoff_iso: str | None = None
    venue_id: str | None = None
    referee_id: str | None = None
    home_manager_id: str | None = None
    away_manager_id: str | None = None
    home_xi: list[str] = field(default_factory=list)
    away_xi: list[str] = field(default_factory=list)
    weather: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    injuries: list[str] = field(default_factory=list)
    market_odds: dict[str, float] = field(default_factory=dict)


# Factors we train on — resume / hackathon story, also the build checklist.
TRAINING_CORPORA = (
    "club_top_flight",      # EPL, La Liga, …
    "club_lower_league",    # Championship, Serie B, …
    "international",        # WC, Euro, friendlies
    "club_world",           # CWC, continental cups
    "friendlies",
    "youth_u21",            # sparse — hierarchical borrow
)

SPORT_ADAPTERS = ("soccer", "basketball", "cricket")


def empty_graph() -> dict[str, Any]:
    return {"nodes": [], "edges": [], "version": 1}


if __name__ == "__main__":
    g = empty_graph()
    assert g["version"] == 1
    assert NodeType.REFEREE.value == "referee"
    print("factor_graph schema ok", len(TRAINING_CORPORA), "corpora,", len(SPORT_ADAPTERS), "sports")
