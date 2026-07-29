"""Train Elo from live boards — soccer clubs + basketball + cricket.

Walk-forward: for each finished game, predict from pre-match Elo, then update.
That gives an honest per-sport accuracy the Model page can show.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

BASE = 1500.0
K = 24.0
HOME_ADV = {"soccer": 70.0, "basketball": 55.0, "cricket": 20.0}


def _sport_bucket(sport_key: str) -> str:
    if sport_key.startswith("basketball"):
        return "basketball"
    if sport_key.startswith("cricket"):
        return "cricket"
    return "soccer"


def _result(hs: Any, aws: Any, *, two_way: bool, home_winner: bool = False, away_winner: bool = False) -> str | None:
    # Cricket (and some boards): trust ESPN winner flag over mangled run totals
    if home_winner and not away_winner:
        return "H"
    if away_winner and not home_winner:
        return "A"
    try:
        h, a = int(hs), int(aws)
    except (TypeError, ValueError):
        return None
    if h > a:
        return "H"
    if a > h:
        return "A"
    return None if two_way else "D"


def _predict(ratings: dict[str, float], home: str, away: str, sport: str) -> dict[str, float]:
    ha = HOME_ADV[sport]
    hr = ratings.get(home, BASE) + ha
    ar = ratings.get(away, BASE)
    diff = hr - ar
    home_exp = 1.0 / (1.0 + 10 ** (-diff / 400.0))
    if sport in ("basketball", "cricket"):
        draw = 0.02
    else:
        import math
        draw = 0.28 * math.exp(-abs(diff) / 200.0)
    home_win = home_exp * (1.0 - draw)
    away_win = (1.0 - home_exp) * (1.0 - draw)
    total = home_win + draw + away_win
    return {
        "home": home_win / total,
        "draw": draw / total,
        "away": away_win / total,
    }


def _pick(probs: dict[str, float], *, two_way: bool) -> str:
    if two_way:
        return "H" if probs["home"] >= probs["away"] else "A"
    best = max(probs.items(), key=lambda kv: kv[1])[0]
    return {"home": "H", "draw": "D", "away": "A"}[best]


def _update(ratings: dict[str, float], home: str, away: str, result: str, ha: float) -> None:
    hr = ratings.get(home, BASE)
    ar = ratings.get(away, BASE)
    exp = 1.0 / (1.0 + 10 ** (-((hr + ha) - ar) / 400.0))
    scores = {"H": 1.0, "D": 0.5, "A": 0.0}
    actual = scores[result]
    ratings[home] = hr + K * (actual - exp)
    ratings[away] = ar + K * ((1.0 - actual) - (1.0 - exp))


def train_from_boards(
    verbose: bool = False,
    seed_elo: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Replay completed fixtures → elo_by_sport + walk-forward accuracy per sport.

    seed_elo: optional deep-history ratings (basketball/cricket) to continue from.
    """
    from bet_placer.data.espn_leagues import fetch_espn_events
    from bet_placer.data.team_names import canon_team

    seed = seed_elo or {}
    by_sport: dict[str, dict[str, float]] = {
        "soccer": dict(seed.get("soccer") or {}),
        "basketball": dict(seed.get("basketball") or {}),
        "cricket": dict(seed.get("cricket") or {}),
    }
    counts = {"soccer": 0, "basketball": 0, "cricket": 0}
    hits = {"soccer": 0, "basketball": 0, "cricket": 0}
    scored = {"soccer": 0, "basketball": 0, "cricket": 0}
    recent: dict[str, list[dict]] = {"soccer": [], "basketball": [], "cricket": []}

    for key in ("soccer_all", "basketball_all", "cricket_all"):
        try:
            events = fetch_espn_events(key)
        except Exception as exc:
            logger.warning("board train fetch %s failed: %s", key, exc)
            continue
        bucket = _sport_bucket(key)
        two_way = bucket != "soccer"
        ha = HOME_ADV[bucket]
        ratings = by_sport[bucket]
        rows = sorted(
            (e for e in events if e.get("status") == "completed"),
            key=lambda e: e.get("commence_time") or "",
        )
        for e in rows:
            res = _result(
                e.get("home_score"),
                e.get("away_score"),
                two_way=two_way,
                home_winner=bool(e.get("home_winner")),
                away_winner=bool(e.get("away_winner")),
            )
            if not res:
                continue
            home = canon_team(e.get("home_team") or "")
            away = canon_team(e.get("away_team") or "")
            if not home or not away:
                continue

            # Predict with pre-match ratings, then update (no leakage)
            probs = _predict(ratings, home, away, bucket)
            pred = _pick(probs, two_way=two_way)
            conf = max(probs.values())
            hit = pred == res
            # Scorecard only counts ≥60% confidence picks (desk gate); cricket needs sharper
            need = 0.65 if bucket == "cricket" else 0.60
            if conf >= need:
                scored[bucket] += 1
                if hit:
                    hits[bucket] += 1
                recent[bucket].append({
                    "home": e.get("home_team") or home,
                    "away": e.get("away_team") or away,
                    "league": e.get("sport_title") or bucket,
                    "score": e.get("score") or f"{e.get('home_score')}-{e.get('away_score')}",
                    "pick": {"H": "home", "D": "draw", "A": "away"}[pred],
                    "pick_pct": round(100 * conf),
                    "hit": hit,
                    "kickoff": e.get("commence_time"),
                })

            _update(ratings, home, away, res, ha)
            counts[bucket] += 1

    accuracy = {
        sport: (round(hits[sport] / scored[sport], 4) if scored[sport] else None)
        for sport in counts
    }
    # Keep last 8 calls per sport (newest last)
    for sport in recent:
        recent[sport] = recent[sport][-8:]

    if verbose:
        for s, n in counts.items():
            acc = accuracy[s]
            acc_s = f"{acc * 100:.0f}%" if acc is not None else "-"
            print(f"[board_train] {s}: {n} games → {len(by_sport[s])} teams · walk-forward {acc_s}")

    return {
        "elo_by_sport": by_sport,
        "counts": counts,
        "n_matches": sum(counts.values()),
        "accuracy": accuracy,
        "scored": scored,
        "hits": hits,
        "recent": recent,
        "rules": {
            "soccer": "3-way (home/draw/away), home edge +70 Elo",
            "basketball": "moneyline 2-way, home edge +55 Elo, draws ignored",
            "cricket": "match winner 2-way, small home edge +20 Elo",
        },
    }


def apply_board_training(params: dict, report: dict) -> dict:
    """Merge board Elo into params — never wipe deeper history with a thin board pass."""
    by_sport = report.get("elo_by_sport") or {}
    prev = dict(params.get("elo_by_sport") or {})
    merged: dict[str, dict[str, float]] = {}
    for sport in ("soccer", "basketball", "cricket"):
        base = dict(prev.get(sport) or {})
        board = by_sport.get(sport) or {}
        # Board ratings win on overlap (fresher); keep history-only teams
        base.update(board)
        merged[sport] = base
    params["elo_by_sport"] = merged
    elo = dict(params.get("elo") or {})
    for team, rating in (merged.get("soccer") or {}).items():
        elo[team] = rating
    params["elo"] = elo
    params["trained_on_boards"] = report.get("counts") or {}
    params["board_scorecards"] = {
        "accuracy": report.get("accuracy") or {},
        "scored": report.get("scored") or {},
        "hits": report.get("hits") or {},
        "recent": report.get("recent") or {},
        "rules": report.get("rules") or {},
        "note": "Accuracy = walk-forward on picks with ≥60% confidence only",
    }
    return params
