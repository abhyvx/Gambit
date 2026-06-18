"""Serialize analysis results to JSON-safe dicts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum

from bet_placer.engine.probability import rank_all_bets


def to_json(obj):
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj):
        return {k: to_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    return obj


def serialize_pipeline_results(results: list[dict]) -> dict:
    analyses = [r["analysis"] for r in results]
    top_bets = rank_all_bets(analyses, top_n=20)

    return {
        "from_live_stake": results[0]["from_live_stake"] if results else False,
        "match_count": len(results),
        "matches": [serialize_match_result(r) for r in results],
        "top_bets": [serialize_value_bet(b) for b in top_bets],
    }


def serialize_match_result(item: dict) -> dict:
    fixture = item["fixture"]
    analysis = item["analysis"]
    return {
        "fixture_id": fixture.id,
        "name": fixture.name,
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "league": fixture.league,
        "sport": fixture.sport,
        "kickoff": fixture.kickoff.isoformat() if fixture.kickoff else None,
        "stake_volume": fixture.total_bet_value,
        "stake_users": fixture.total_user_count,
        "stake_bet_count": fixture.total_bet_count,
        "verdict": to_json(item["verdict"]),
        "bettor_consensus": to_json(item["bettor_consensus"]),
        "web_consensus": to_json(item["web_consensus"]),
        "markets": [
            {
                "name": m.name,
                "group": m.group,
                "line": m.line,
                "outcomes": [
                    {"id": o.id, "name": o.name, "odds": o.odds}
                    for o in m.outcomes
                ],
            }
            for m in fixture.markets
        ],
        "probabilities": [to_json(p) for p in analysis.probabilities],
        "value_bets": [serialize_value_bet(b) for b in analysis.value_bets],
        "top_bets": [serialize_value_bet(b) for b in analysis.top_bets],
    }


def serialize_value_bet(bet) -> dict:
    return {
        "match_id": bet.match_id,
        "match_label": bet.match_label,
        "market": bet.market.value if hasattr(bet.market, "value") else bet.market,
        "selection": bet.selection,
        "line": bet.line,
        "decimal_odds": bet.decimal_odds,
        "implied_probability": bet.implied_probability,
        "true_probability": bet.true_probability,
        "expected_value": bet.expected_value,
        "expected_roi": bet.expected_roi,
        "kelly_stake_pct": bet.kelly_stake_pct,
        "confidence": bet.confidence,
        "risk_score": bet.risk_score,
        "rank_score": bet.rank_score,
        "explanation": bet.explanation,
        "kickoff": bet.kickoff.isoformat() if bet.kickoff else None,
    }
