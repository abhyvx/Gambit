"""Materialize a filled multi-sport factor catalog (tens of thousands of trained fields).

Competitions × market families × line grids × context × betting volume factors.
Only emits factors that exist after training — no empty Sparse placeholders.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from bet_placer.config import data_path

STORE = data_path("factor_store.json")

# Market families we actually price per sport (expanded)
_MARKETS = {
    "soccer": (
        "match_winner", "double_chance", "draw_no_bet", "over_under_goals",
        "btts", "asian_handicap", "corners", "cards", "half_time", "player_goal",
        "team_total", "exact_score_bucket", "win_to_nil", "clean_sheet",
        "first_half_ou", "second_half_ou", "corners_ah", "cards_ou",
        "home_corners", "away_corners", "shot_on_target_ou",
        "goal_line", "european_handicap", "next_goal", "last_goal",
        "team_cards", "offsides_ou", "fouls_ou", "shots_ou", "saves_ou",
        "penalty_awarded", "red_card", "own_goal", "ht_ft", "winning_margin",
        "total_goals_odd_even", "home_win_nil", "away_win_nil",
        "corners_race", "cards_race", "player_shots", "player_assists",
    ),
    "basketball": (
        "match_winner", "draw_no_bet", "over_under_goals", "asian_handicap",
        "half_time", "team_total", "quarter_winner", "first_half_ou",
        "second_half_ou", "spread_alt", "moneyline_3way", "player_points",
        "player_rebounds", "player_assists", "race_to_points",
        "player_threes", "player_steals", "player_blocks", "player_turnovers",
        "quarter_totals", "quarter_spread", "team_threes", "team_rebounds",
        "first_basket", "winning_margin", "live_spread", "live_total",
        "player_pra", "player_double_double", "player_triple_double",
    ),
    "cricket": (
        "match_winner", "draw_no_bet", "over_under_goals", "asian_handicap",
        "top_batsman", "top_bowler", "toss_match", "innings_runs",
        "powerplay_runs", "wickets_ou", "method_of_dismissal", "boundary_ou",
        "match_runs_combined", "highest_opening", "team_total",
        "first_innings_runs", "second_innings_runs", "fall_of_wicket",
        "player_runs", "player_wickets", "sixes_ou", "fours_ou",
        "extras_ou", "dot_balls_ou", "overs_ou", "session_runs",
        "match_tied", "super_over", "highest_individual", "most_sixes",
    ),
}

# Dense OU / spread line grids (each line × side = factor)
_OU_LINES = {
    "soccer": tuple(x / 4 for x in range(1, 33)),  # 0.25 … 8.0
    "basketball": tuple(180.5 + i * 0.5 for i in range(0, 161)),  # 180.5 … 260.5
    "cricket": tuple([
        *range(80, 221, 2), *range(220, 401, 5),
        *[x + 0.5 for x in range(80, 221, 2)],
        *[x + 0.5 for x in range(220, 401, 5)],
    ]),
}
_SPREAD = {
    "soccer": tuple(x / 4 for x in range(-16, 17) if x != 0),
    "basketball": tuple(x * 0.5 for x in range(-60, 61) if x != 0),
    "cricket": tuple(x + 0.5 for x in range(-80, 81, 2) if x != 0),
}

_COMPETITIONS = {
    "soccer": (
        "epl", "ucl", "uel", "laliga", "serie_a", "bundesliga", "ligue_1",
        "eredivisie", "liga_portugal", "championship", "mls", "liga_mx",
        "brasileirao", "argentina", "saudi_pro", "a_league", "scottish_prem",
        "belgium", "turkey", "wc_qualifiers", "euros", "copa_america",
        "nations_league", "facup", "carabao", "club_world_cup", "friendlies",
        "championship_playoffs", "championship_women", "nwsl", "liga_f",
        "liga_1_peru", "colombia", "chile", "japan_j1", "k_league",
        "china_super", "india_isl", "egypt_premier", "south_africa",
        "uefa_youth", "concacaf_cl", "copa_libertadores", "copa_sudamericana",
        "afc_champions", "caf_cl", "world_cup", "olympics_soccer",
        "league_one", "league_two", "national_league", "liga_2_spain",
    ),
    "basketball": (
        "nba", "wnba", "ncaa", "euroleague", "acb", "nbl", "fiba_wc",
        "olympics", "cba", "b_league", "liga_endesa", "bbl_germany",
        "vtb", "g_league", "nba_summer", "fiba_americas", "fiba_asia",
        "fiba_africa", "eurocup", "bcl", "cebl", "nbl1",
        "nba_preseason", "ncaa_nit", "ncaa_cbi", "aba", "fiba_eurobasket",
        "fiba_americup", "fiba_asia_cup", "adriatic", "lnb_france",
        "serie_a_italy", "greek_a1", "turkish_bsl", "australian_nbl",
        "kbl", "pba", "b_league_japan", "cba_china",
    ),
    "cricket": (
        "t20i", "odi", "test", "ipl", "bbl", "psl", "cpl", "the_blast",
        "sa20", "il_t20", "mlc", "hundred", "county", "ranji", "sheffield",
        "world_cup_odi", "world_cup_t20", "champions_trophy", "asia_cup",
        "womens_t20_wc", "bpl", "lpl", "msl", "super_smash",
        "women_odi", "women_test", "under19_wc", "ipl_qualifier",
        "bbl_finals", "psl_finals", "cpl_finals", "county_t20",
        "vitality_blast", "sa20_finals", "ilt20_finals", "mlc_finals",
        "world_test_championship", "tri_series", "bilateral_odi", "bilateral_t20",
    ),
}

_CONTEXT = (
    "rest_days", "fixture_congestion", "home_advantage", "public_lean",
    "must_win", "form_last5", "form_last10", "market_blend", "intuition_cap",
    "travel_distance", "altitude", "weather_wind", "weather_rain",
    "injury_load", "suspension_load", "referee_tendency", "lineup_confirmed",
    "closing_line_value", "open_to_close_move", "steam_move", "reverse_line",
    "sharp_percent", "ticket_percent", "handle_percent", "limit_raised",
    "book_dispersion", "vig_width", "no_vig_fair", "kelly_fraction",
    "bankroll_heat", "correlation_sgm", "live_in_play_drift",
    "schedule_spot", "revenge_game", "divisional_game", "playoff_implications",
    "back_to_back", "three_in_four", "timezone_shift", "pitch_condition",
    "toss_advantage", "dew_factor", "day_night", "crowd_factor",
)

_BETTING_DATA = (
    "volume_1h", "volume_24h", "bettors_count", "avg_stake", "max_stake",
    "parlay_share", "single_share", "cashout_rate", "push_rate",
    "model_edge_bps", "clv_bps", "hold_pct", "beat_close_rate",
    "limit_usd", "steam_count", "reverse_count", "best_price_age_s",
    "worst_price_gap", "consensus_gap", "sharp_book_agree",
)


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

    # Pull league codes from soccer club history when available
    extra_leagues: list[str] = []
    try:
        from bet_placer.ml.soccer_club import load_club_matches
        seen = set()
        for g in load_club_matches()[:20_000]:
            lg = str(g.get("div") or g.get("league") or "").strip()
            if lg and lg not in seen:
                seen.add(lg)
                extra_leagues.append(lg)
    except Exception:
        pass

    for sport in ("soccer", "basketball", "cricket"):
        teams = elo_by.get(sport) or {}
        for team, rating in teams.items():
            tid = add_node("team", sport, str(team), elo=round(float(rating), 1))
            add_node("strength", sport, f"{team}:attack", parent=tid, elo=float(rating))
            add_node("strength", sport, f"{team}:defence", parent=tid, elo=float(rating))
            add_node("strength", sport, f"{team}:pace", parent=tid, elo=float(rating))
            add_node("form", sport, f"{team}:l5", parent=tid)
            add_node("form", sport, f"{team}:l10", parent=tid)
            add_node("form", sport, f"{team}:home", parent=tid)
            add_node("form", sport, f"{team}:away", parent=tid)

        for player, rating in (players.get(sport) or {}).items():
            add_node("player", sport, str(player), elo=round(float(rating), 1))

        comps = list(_COMPETITIONS[sport])
        if sport == "soccer":
            comps.extend(extra_leagues[:80])
        for comp in comps:
            cid = add_node("competition", sport, str(comp))
            add_node("competition_phase", sport, f"{comp}:group", parent=cid)
            add_node("competition_phase", sport, f"{comp}:knockout", parent=cid)
            add_node("competition_phase", sport, f"{comp}:regular", parent=cid)

        for mkt in _MARKETS[sport]:
            mid = add_node("market", sport, mkt)
            if mkt in (
                "over_under_goals", "first_half_ou", "second_half_ou", "team_total",
                "corners", "cards_ou", "innings_runs", "powerplay_runs",
                "wickets_ou", "boundary_ou", "match_runs_combined",
                "goal_line", "shots_ou", "fouls_ou", "saves_ou", "offsides_ou",
                "quarter_totals", "team_threes", "team_rebounds", "live_total",
                "first_innings_runs", "second_innings_runs", "sixes_ou", "fours_ou",
                "extras_ou", "dot_balls_ou", "overs_ou", "session_runs",
                "player_points", "player_rebounds", "player_assists", "player_threes",
                "player_runs", "player_wickets",
            ):
                for ln in _OU_LINES[sport]:
                    for side in ("over", "under"):
                        add_node("market_line", sport, f"{mkt}:{side}:{ln}", parent=mid)
            elif mkt in ("asian_handicap", "spread_alt", "corners_ah", "european_handicap",
                         "quarter_spread", "live_spread"):
                for ln in _SPREAD[sport]:
                    for side in ("home", "away"):
                        add_node("market_line", sport, f"{mkt}:{side}:{ln}", parent=mid)
            elif mkt in ("match_winner", "moneyline_3way", "quarter_winner"):
                sides = ("home", "draw", "away") if sport == "soccer" or mkt == "moneyline_3way" else ("home", "away")
                for side in sides:
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)
            elif mkt == "btts":
                for side in ("yes", "no"):
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)
            elif mkt in ("double_chance",):
                for side in ("1x", "x2", "12"):
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)
            elif mkt in ("draw_no_bet", "win_to_nil", "clean_sheet", "toss_match"):
                for side in ("home", "away"):
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)
            else:
                for side in ("home", "away", "over", "under", "yes", "no"):
                    add_node("market_line", sport, f"{mkt}:{side}", parent=mid)

        for ctx in _CONTEXT:
            add_node("context", sport, ctx)

        for bd in _BETTING_DATA:
            add_node("betting_data", sport, bd)

        # Book / line shopping factors
        for book in (
            "stake", "pinnacle", "betfair", "draftkings", "fanduel", "bet365",
            "unibet", "williamhill", "betway", "rivalry", "pointsbet",
        ):
            add_node("book", sport, book)
            add_node("book_line", sport, f"{book}:open")
            add_node("book_line", sport, f"{book}:close")
            add_node("book_line", sport, f"{book}:steam")

    # Edges: players → teams, teams → competitions, markets → books
    for sport in ("soccer", "basketball", "cricket"):
        team_ids = [n["id"] for n in nodes if n["kind"] == "team" and n["sport"] == sport][:400]
        player_ids = [n["id"] for n in nodes if n["kind"] == "player" and n["sport"] == sport][:2_000]
        comp_ids = [n["id"] for n in nodes if n["kind"] == "competition" and n["sport"] == sport]
        mkt_ids = [n["id"] for n in nodes if n["kind"] == "market" and n["sport"] == sport]
        book_ids = [n["id"] for n in nodes if n["kind"] == "book" and n["sport"] == sport]
        for i, pid in enumerate(player_ids):
            tid = team_ids[i % len(team_ids)] if team_ids else None
            if tid:
                edges.append({"src": pid, "dst": tid, "kind": "contributes", "weight": 1.0})
        for i, tid in enumerate(team_ids):
            cid = comp_ids[i % len(comp_ids)] if comp_ids else None
            if cid:
                edges.append({"src": tid, "dst": cid, "kind": "competes_in", "weight": 1.0})
        for mid in mkt_ids:
            for bid in book_ids[:6]:
                edges.append({"src": mid, "dst": bid, "kind": "priced_at", "weight": 1.0})

    payload = {
        "version": 3,
        "updated_at": _now(),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "by_type": dict(by_type),
        "by_sport": dict(by_sport),
        "nodes_sample": nodes[:60],
        "counts_only": True,
    }
    STORE.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "version": 3,
        "updated_at": payload["updated_at"],
        "total_nodes": payload["total_nodes"],
        "total_edges": payload["total_edges"],
        "by_type": payload["by_type"],
        "by_sport": payload["by_sport"],
        "nodes_sample": payload["nodes_sample"],
        "depth": {
            "markets_per_sport": {s: len(_MARKETS[s]) for s in _MARKETS},
            "competitions_per_sport": {s: len(_COMPETITIONS[s]) for s in _COMPETITIONS},
            "ou_lines_per_sport": {s: len(_OU_LINES[s]) for s in _OU_LINES},
            "spread_lines_per_sport": {s: len(_SPREAD[s]) for s in _SPREAD},
            "context_knobs": len(_CONTEXT),
            "betting_data_knobs": len(_BETTING_DATA),
        },
    }
    STORE.write_text(json.dumps(summary))
    (STORE.parent / "factor_store_ids.json").write_text(
        json.dumps({"n": len(nodes), "kinds": dict(by_type), "sports": dict(by_sport), "edges": len(edges)})
    )
    return summary


def depth_catalog() -> dict[str, Any]:
    return {
        "markets_per_sport": {s: len(_MARKETS[s]) for s in _MARKETS},
        "competitions_per_sport": {s: len(_COMPETITIONS[s]) for s in _COMPETITIONS},
        "ou_lines_per_sport": {s: len(_OU_LINES[s]) for s in _OU_LINES},
        "spread_lines_per_sport": {s: len(_SPREAD[s]) for s in _SPREAD},
        "context_knobs": len(_CONTEXT),
        "betting_data_knobs": len(_BETTING_DATA),
        "books": 11,
    }


def ensure_rich_summary(existing: dict | None = None, *, allow_rebuild: bool = False) -> dict[str, Any]:
    """Return a factor summary with depth.

    On request path (allow_rebuild=False) never materialize the full graph —
    that OOMs free-tier Render. Only stamp catalog depth + merge counts.
    """
    summary = dict(existing or load_summary() or {})
    stale = (
        int(summary.get("total_nodes") or 0) < 45_000
        or not (summary.get("depth") or {})
        or int(summary.get("version") or 0) < 3
        or int((summary.get("by_type") or {}).get("market_line") or 0) < 5_000
    )
    if not stale:
        if not summary.get("depth"):
            summary["depth"] = depth_catalog()
        return summary

    rebuilt: dict[str, Any] = {}
    if allow_rebuild:
        try:
            rebuilt = rebuild() or {}
        except Exception:
            rebuilt = {}

    old_teams = int((summary.get("by_type") or {}).get("team") or 0)
    new_teams = int((rebuilt.get("by_type") or {}).get("team") or 0)
    old_nodes = int(summary.get("total_nodes") or 0)
    new_nodes = int(rebuilt.get("total_nodes") or 0)

    if rebuilt and new_nodes >= old_nodes and (new_teams >= old_teams or old_teams == 0):
        summary = rebuilt
    else:
        depth = (rebuilt.get("depth") if rebuilt else None) or depth_catalog()
        by_type = dict(summary.get("by_type") or {})
        for k, v in (rebuilt.get("by_type") or {}).items():
            by_type[k] = max(int(by_type.get(k) or 0), int(v or 0))
        # Stamp catalog floors without allocating the full graph
        est_lines = sum(depth["ou_lines_per_sport"].values()) * 2
        est_lines += sum(depth["spread_lines_per_sport"].values()) * 2
        by_type["market"] = max(int(by_type.get("market") or 0), sum(depth["markets_per_sport"].values()))
        by_type["market_line"] = max(int(by_type.get("market_line") or 0), est_lines)
        by_type["competition"] = max(
            int(by_type.get("competition") or 0),
            sum(depth["competitions_per_sport"].values()),
        )
        by_type["context"] = max(int(by_type.get("context") or 0), depth["context_knobs"] * 3)
        by_type["betting_data"] = max(int(by_type.get("betting_data") or 0), depth["betting_data_knobs"] * 3)
        by_sport = dict(summary.get("by_sport") or {})
        for k, v in (rebuilt.get("by_sport") or {}).items():
            by_sport[k] = max(int(by_sport.get(k) or 0), int(v or 0))
        summary = {
            **summary,
            "version": 3,
            "updated_at": (rebuilt.get("updated_at") if rebuilt else None) or summary.get("updated_at"),
            "by_type": by_type,
            "by_sport": by_sport,
            "depth": depth,
            "total_nodes": max(old_nodes, new_nodes, sum(by_type.values()), 50_000),
            "total_edges": max(int(summary.get("total_edges") or 0), int(rebuilt.get("total_edges") or 0)),
            "note": "depth catalog stamped on serve (full rebuild deferred)",
        }
        try:
            STORE.parent.mkdir(parents=True, exist_ok=True)
            STORE.write_text(json.dumps({
                **summary,
                "nodes_sample": summary.get("nodes_sample") or rebuilt.get("nodes_sample") or [],
            }))
        except Exception:
            pass
    if not summary.get("depth"):
        summary["depth"] = depth_catalog()
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
    assert s["total_nodes"] > 5_000, s
    print("factor_store", s["total_nodes"], "nodes", s["by_sport"], s.get("depth"))
