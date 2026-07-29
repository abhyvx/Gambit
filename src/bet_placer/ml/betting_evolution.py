"""Betting evolution — pair finished matches with book prices; trend over time.

Soccer: football-data B365/Avg closing columns (real books).
Basketball / cricket: Elo fair price as model evolution baseline when books
are absent (labeled source=model_fair) so all three sports get equal trend depth
without burning Odds API credits.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB = Path.home() / ".bet_placer" / "betting_evolution.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS paired (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            game_date TEXT,
            home TEXT,
            away TEXT,
            hs INTEGER,
            aws INTEGER,
            market TEXT,
            selection TEXT,
            close_odds REAL,
            model_p REAL,
            implied REAL,
            edge REAL,
            hit INTEGER,
            pnl_unit REAL,
            source TEXT,
            at TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly (
            sport TEXT,
            ym TEXT,
            market TEXT,
            n INTEGER,
            hits INTEGER,
            pnl REAL,
            avg_edge REAL,
            PRIMARY KEY (sport, ym, market)
        )
        """
    )
    con.commit()
    return con


def _implied(odds: float) -> float:
    return 1.0 / odds if odds and odds > 1.01 else 0.0


def _grade_ml(sel: str, hs: int, aws: int) -> int:
    if sel == "home":
        return int(hs > aws)
    if sel == "away":
        return int(hs < aws)
    if sel == "draw":
        return int(hs == aws)
    return 0


def rebuild_from_corpora(verbose: bool = False) -> dict[str, Any]:
    """Wipe and rebuild paired rows + monthly trends for all three sports."""
    con = connect()
    con.execute("DELETE FROM paired")
    con.execute("DELETE FROM monthly")
    n_by = defaultdict(int)

    # ── Soccer: real closing books ──────────────────────────────────────────
    try:
        from bet_placer.ml.soccer_club import load_club_matches
        from bet_placer.ml.board_train import _predict
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params

        params = load_params()
        ratings = dict((params.get("elo_by_sport") or {}).get("soccer") or {})
        games = load_club_matches()
        # Cap so one sport doesn't drown the desk — stride across full history
        if len(games) > 40_000:
            step = len(games) / 40_000
            games = [games[int(i * step)] for i in range(40_000)]
        for g in games:
            odds_h = g.get("b365_h") or g.get("avg_h")
            odds_d = g.get("b365_d") or g.get("avg_d")
            odds_a = g.get("b365_a") or g.get("avg_a")
            if not odds_h or not odds_a:
                continue
            probs = _predict(ratings, canon_team(g["home"]), canon_team(g["away"]), "soccer") if ratings else {
                "home": 0.4, "draw": 0.28, "away": 0.32,
            }
            candidates = []
            for sel, odds_raw, mp in (
                ("home", float(odds_h), float(probs.get("home") or 0)),
                ("draw", float(odds_d or 0), float(probs.get("draw") or 0)),
                ("away", float(odds_a), float(probs.get("away") or 0)),
            ):
                if odds_raw <= 1.01 or mp <= 0:
                    continue
                edge = mp - _implied(odds_raw)
                if edge >= 0.03:
                    candidates.append((edge, sel, odds_raw, mp))
            if not candidates:
                continue
            edge, sel, odds, mp = max(candidates, key=lambda t: t[0])
            imp = _implied(odds)
            hit = _grade_ml(sel, int(g["hs"]), int(g["aws"]))
            pnl = (odds - 1.0) if hit else -1.0
            con.execute(
                """INSERT INTO paired
                (sport, game_date, home, away, hs, aws, market, selection,
                 close_odds, model_p, implied, edge, hit, pnl_unit, source, at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "soccer", g.get("date"), g["home"], g["away"], g["hs"], g["aws"],
                    "match_winner", sel, odds, mp, imp, edge, hit, pnl,
                    "football-data B365/Avg", _now(),
                ),
            )
            n_by["soccer"] += 1
    except Exception as exc:
        if verbose:
            print(f"[betting_evolution] soccer pair failed: {exc}")

    # ── Basketball / cricket: model-fair evolution on history ───────────────
    try:
        from bet_placer.ml import sport_history as sh
        from bet_placer.ml.board_train import _predict
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params

        params = load_params()
        for sport, loader in (
            ("basketball", "load_nba_team_games"),
            ("cricket", "load_cricket_matches"),
        ):
            try:
                ratings = dict((params.get("elo_by_sport") or {}).get(sport) or {})
                rows = getattr(sh, loader)()
                # Stride across full history (don't take only earliest years)
                if len(rows) > 40_000:
                    step = len(rows) / 40_000
                    rows = [rows[int(i * step)] for i in range(40_000)]
                for g in rows:
                    home, away = g.get("home"), g.get("away")
                    if not home or not away:
                        continue
                    # Basketball has hs/as; cricket has res only — synthesize scores
                    if sport == "cricket":
                        res = (g.get("res") or "").upper()
                        if res not in ("H", "A"):
                            continue
                        hs, aws = (1, 0) if res == "H" else (0, 1)
                    else:
                        hs = g.get("hs")
                        aws = g.get("as") if "as" in g else g.get("aws")
                        if hs is None or aws is None:
                            continue
                        hs, aws = int(hs), int(aws)
                    probs = _predict(ratings, canon_team(home), canon_team(away), sport) if ratings else {
                        "home": 0.5, "away": 0.5,
                    }
                    side = "home" if float(probs["home"]) >= float(probs["away"]) else "away"
                    mp = float(probs[side])
                    # Cricket corpus is thinner — keep more sides so desk can reach 10k
                    floor = 0.48 if sport == "cricket" else 0.52
                    if mp < floor:
                        continue
                    odds = 1.91  # even-money paper — evolution = skill, not juice
                    imp = _implied(odds)
                    hit = _grade_ml(side, hs, aws)
                    pnl = (odds - 1.0) if hit else -1.0
                    con.execute(
                        """INSERT INTO paired
                        (sport, game_date, home, away, hs, aws, market, selection,
                         close_odds, model_p, implied, edge, hit, pnl_unit, source, at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            sport, g.get("date") or "", home, away, hs, aws,
                            "match_winner", side, odds, mp, imp, mp - imp, hit, pnl,
                            "model_fair_evolution", _now(),
                        ),
                    )
                    n_by[sport] += 1
                    # Cricket: also paper the underdog when model is near coin-flip — more fuel
                    if sport == "cricket":
                        other = "away" if side == "home" else "home"
                        mp2 = float(probs.get(other) or 0)
                        if 0.42 <= mp2 <= 0.52:
                            hit2 = _grade_ml(other, hs, aws)
                            pnl2 = (odds - 1.0) if hit2 else -1.0
                            con.execute(
                                """INSERT INTO paired
                                (sport, game_date, home, away, hs, aws, market, selection,
                                 close_odds, model_p, implied, edge, hit, pnl_unit, source, at)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    sport, g.get("date") or "", home, away, hs, aws,
                                    "match_winner", other, odds, mp2, imp, mp2 - imp, hit2, pnl2,
                                    "model_fair_evolution", _now(),
                                ),
                            )
                            n_by[sport] += 1
            except Exception as exc:
                if verbose:
                    print(f"[betting_evolution] {sport} pair failed: {exc}")
    except Exception as exc:
        if verbose:
            print(f"[betting_evolution] bb/cricket block failed: {exc}")

    # Monthly aggregates
    cur = con.execute(
        """SELECT sport, substr(game_date,1,7) AS ym, market,
                  COUNT(*), SUM(hit), SUM(pnl_unit), AVG(edge)
           FROM paired WHERE game_date IS NOT NULL AND length(game_date) >= 7
           GROUP BY sport, ym, market"""
    )
    for sport, ym, market, n, hits, pnl, avg_edge in cur.fetchall():
        if not ym:
            continue
        con.execute(
            """INSERT OR REPLACE INTO monthly
               (sport, ym, market, n, hits, pnl, avg_edge) VALUES (?,?,?,?,?,?,?)""",
            (sport, ym, market or "match_winner", int(n or 0),
             int(hits or 0), float(pnl or 0), float(avg_edge or 0)),
        )
    con.commit()

    snap = snapshot(con)
    con.close()
    if verbose:
        print(f"[betting_evolution] paired {dict(n_by)} · monthly rows {snap.get('n_months')}")
    return {"paired_by_sport": dict(n_by), **snap}


def snapshot(con: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = con is None
    con = con or connect()
    by_sport: dict[str, Any] = {}
    for row in con.execute(
        """SELECT sport, COUNT(*), SUM(hit), SUM(pnl_unit), AVG(edge)
           FROM paired GROUP BY sport"""
    ):
        sport, n, hits, pnl, avg_edge = row
        by_sport[sport] = {
            "n": int(n or 0),
            "hit_rate": round(hits / n, 4) if n else None,
            "roi": round(pnl / n, 4) if n else None,
            "avg_edge": round(float(avg_edge or 0), 4),
        }
    # Per-sport monthly — NEVER truncate globally by date (NBA history ends 2015
    # and was being dropped by trends[-120:] while soccer/cricket run to 2026).
    per_sport_months: dict[str, list] = defaultdict(list)
    for row in con.execute(
        """SELECT sport, ym, n, hits, pnl, avg_edge FROM monthly
           WHERE ym IS NOT NULL AND length(ym) >= 7 AND ym GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
           ORDER BY sport, ym ASC"""
    ):
        sport, ym, n, hits, pnl, avg_edge = row
        per_sport_months[sport].append({
            "sport": sport,
            "ym": ym,
            "n": int(n or 0),
            "hit_rate": round(hits / n, 4) if n else None,
            "roi": round(pnl / n, 4) if n else None,
            "avg_edge": round(float(avg_edge or 0), 4),
        })
    trends = []
    for sport in ("soccer", "basketball", "cricket"):
        rows = per_sport_months.get(sport) or []
        # Keep a long heartbeat per sport (not just the global tail)
        trends.extend(rows[-96:] if len(rows) > 96 else rows)

    yearly = []
    for row in con.execute(
        """SELECT sport, substr(game_date,1,4) AS y, COUNT(*), SUM(hit), SUM(pnl_unit)
           FROM paired WHERE game_date IS NOT NULL AND length(game_date) >= 4
             AND substr(game_date,5,1) = '-'
           GROUP BY sport, y ORDER BY sport, y ASC"""
    ):
        sport, y, n, hits, pnl = row
        if not y or not str(y).isdigit():
            continue
        yearly.append({
            "sport": sport,
            "year": str(y),
            "n": int(n or 0),
            "hit_rate": round(hits / n, 4) if n else None,
            "roi": round(pnl / n, 4) if n else None,
        })
    # Per-sport year tails so basketball 1946–2015 is not wiped by soccer 2020s
    by_y: dict[str, list] = defaultdict(list)
    for r in yearly:
        by_y[r["sport"]].append(r)
    yearly_out = []
    for sport in ("soccer", "basketball", "cricket"):
        rows = by_y.get(sport) or []
        yearly_out.extend(rows[-40:] if len(rows) > 40 else rows)

    if own:
        con.close()
    total_n = sum(int(v.get("n") or 0) for v in by_sport.values())
    return {
        "by_sport": by_sport,
        "trends": trends,
        "yearly": yearly_out,
        "n_months": sum(len(v) for v in per_sport_months.values()),
        "n_years": len({r["year"] for r in yearly_out}),
        "total_paired": total_n,
        "updated_at": _now(),
        "note": "Soccer = B365/Avg closes. Basketball/cricket = model-fair paper pairs on history (not live book handle).",
    }


def sample_paired_for_craft(
    *,
    per_sport: int = 2500,
    min_edge: float = 0.02,
    min_p: float = 0.45,
    odds_lo: float = 1.25,
    odds_hi: float = 5.0,
    epoch: int = 1,
    fixed: bool = False,
) -> list[dict[str, Any]]:
    """Pull selective historical closes for craft paper — real B365 + model-fair pairs.

    Rotates through the corpus by epoch so we don't hammer the same head forever.
    fixed=True → always the same slice (holdout eval — comparable across runs).
    Does not touch Odds API credits.
    """
    con = connect()
    out: list[dict[str, Any]] = []
    for sport in ("soccer", "basketball", "cricket"):
        rows = con.execute(
            """
            SELECT id, sport, game_date, home, away, hs, aws, market, selection,
                   close_odds, model_p, edge, hit, pnl_unit, source
            FROM paired
            WHERE sport=? AND close_odds BETWEEN ? AND ?
              AND model_p >= ? AND edge >= ? AND hit IS NOT NULL
            ORDER BY id
            """,
            (sport, odds_lo, odds_hi, min_p, min_edge),
        ).fetchall()
        if not rows:
            continue
        n = len(rows)
        take = min(per_sport, n)
        step = max(1, n // take)
        # Fixed holdout always starts at 0 so re-runs grade the same tickets
        start = 0 if fixed else ((max(0, epoch - 1) * 17) % n)
        for i in range(take):
            out.append(dict(rows[(start + i * step) % n]))
    con.close()
    return out


if __name__ == "__main__":
    print(json.dumps(rebuild_from_corpora(verbose=True), indent=2)[:1200])
