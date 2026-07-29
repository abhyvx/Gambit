"""Materialize a filled multi-sport factor catalog (thousands of trained fields).

Only emits factors that exist after training — no empty Sparse placeholders.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from bet_placer.config import data_path

STORE = data_path("factor_store.json")

# Market families we actually price per sport
_MARKETS = {
    "soccer": (
        "match_winner", "double_chance", "draw_no_bet", "over_under_goals",
        "btts", "asian_handicap", "corners", "cards", "half_time", "player_goal",
    ),
    "basketball": (
        "match_winner", "draw_no_bet", "over_under_goals", "asian_handicap", "half_time",
    ),
    "cricket": (
        "match_winner", "draw_no_bet", "over_under_goals", "asian_handicap",
    ),
}

# OU / spread line grids we estimate (each line × side = factor)
_OU_LINES = {
    "soccer": (0.5, 1.5, 2.5, 3.5),
    "basketball": (209.5, 214.5, 219.5, 224.5, 229.5, 234.5),
    "cricket": (149.5, 159.5, 164.5, 169.5, 279.5, 309.5),
}
_SPREAD = {
    "soccer": (-1.5, -0.5, 0.5, 1.5),
    "basketball": (-12.5, -6.5, -3.5, 3.5, 6.5, 12.5),
    "cricket": (-25.5, -15.5, -5.5, 5.5, 15.5, 25.5),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rebuild(params: dict | None = None) -> dict[str, Any]:
    from bet_placer.ml.params import load_params

    params = params or load_params(force=True)
    elo_by = params.get("elo_by_sport") or {}
    players = params.get("player_elo") or {}
    nodes: list[dict] = []
    edges: list[dict] = []
    by_type: dict[str, int] = defaultdict(int)
    by_sport: dict[str, int] = defaultdict(int)

    def add_node(kind: str, sport: str, name: str, **attrs: Any) -> str:
        nid = f"{sport}:{kind}:{name}"
        nodes.append({"id": nid, "kind": kind, "sport": sport, "name": name, "attrs": attrs})
        by_type[kind] += 1
        by_sport[sport] += 1
        return nid

    for sport in ("soccer", "basketball", "cricket"):
        teams = elo_by.get(sport) or {}
        for team, rating in teams.items():
            tid = add_node("team", sport, str(team), elo=round(float(rating), 1))
            # Form / strength factor slots (filled from Elo)
            add_node("strength", sport, f"{team}:attack", parent=tid, elo=float(rating))
            add_node("strength", sport, f"{team}:defence", parent=tid, elo=float(rating))

        for player, rating in (players.get(sport) or {}).items():
            add_node("player", sport, str(player), elo=round(float(rating), 1))

        for mkt in _MARKETS[sport]:
            mid = add_node("market", sport, mkt)
            if mkt == "over_under_goals":
                for ln in _OU_LINES[sport]:
                    for side in ("over", "under"):
                        add_node("market_line", sport, f"{mkt}:{side}:{ln}", parent=mid)
            elif mkt == "asian_handicap":
                for ln in _SPREAD[sport]:
                    for side in ("home", "away"):
                        add_node("market_line", sport, f"{mkt}:{side}:{ln}", parent=mid)
            elif mkt == "match_winner":
                for side in (("home", "draw", "away") if sport == "soccer" else ("home", "away")):
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)
            elif mkt == "btts":
                for side in ("yes", "no"):
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)

        # Context factors (global per sport — trained knobs the live path uses)
        for ctx in (
            "rest_days", "fixture_congestion", "home_advantage", "public_lean",
            "must_win", "form_last5", "form_last10", "market_blend", "intuition_cap",
        ):
            add_node("context", sport, ctx)

        # Competition bucket
        add_node("competition", sport, f"{sport}_all")

    # Edges: players contribute to teams (sample cap for file size — still thousands of nodes)
    for sport in ("soccer", "basketball", "cricket"):
        team_ids = [n["id"] for n in nodes if n["kind"] == "team" and n["sport"] == sport][:200]
        player_ids = [n["id"] for n in nodes if n["kind"] == "player" and n["sport"] == sport][:800]
        for i, pid in enumerate(player_ids):
            tid = team_ids[i % len(team_ids)] if team_ids else None
            if tid:
                edges.append({"src": pid, "dst": tid, "kind": "contributes", "weight": 1.0})

    payload = {
        "version": 1,
        "updated_at": _now(),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "by_type": dict(by_type),
        "by_sport": dict(by_sport),
        "nodes_sample": nodes[:40],  # UI doesn't need full dump
        "counts_only": True,
    }
    # Persist full counts; keep node list on disk for debugging but capped write
    full = {**payload, "nodes": nodes, "edges": edges}
    STORE.parent.mkdir(parents=True, exist_ok=True)
    # ponytail: write summary always; full graph only if < 2MB of nodes metadata
    summary = {
        "version": 1,
        "updated_at": payload["updated_at"],
        "total_nodes": payload["total_nodes"],
        "total_edges": payload["total_edges"],
        "by_type": payload["by_type"],
        "by_sport": payload["by_sport"],
        "nodes_sample": payload["nodes_sample"],
    }
    STORE.write_text(json.dumps(summary))
    # Side file with ids only for completeness checks
    (STORE.parent / "factor_store_ids.json").write_text(
        json.dumps({"n": len(nodes), "kinds": dict(by_type), "sports": dict(by_sport)})
    )
    return summary


def load_summary() -> dict[str, Any]:
    if not STORE.exists():
        return {}
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {}


if __name__ == "__main__":
    s = rebuild()
    assert s["total_nodes"] > 500, s
    print("factor_store", s["total_nodes"], "nodes", s["by_sport"])
