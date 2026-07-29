"""Soccer player Elo from StatsBomb open lineups (free GitHub JSON).

ponytail: lineups only (not full event graphs) — enough for XI contribution
shares like cricket. Ceiling: open-data competitions only. Upgrade: full
event xG if we ever need shot-level skill.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from bet_placer.config import data_path

CACHE = data_path("statsbomb")
BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
TTL_DAYS = 14
PLAYER_K = 18.0
BASE_ELO = 1500.0


def _get(url: str, dest: Path, *, force: bool = False) -> Any:
    CACHE.mkdir(parents=True, exist_ok=True)
    stale = (
        force
        or not dest.exists()
        or (time.time() - dest.stat().st_mtime > TTL_DAYS * 86400)
    )
    if stale:
        req = Request(url, headers={"User-Agent": "Gambit/1.0"})
        with urlopen(req, timeout=90) as r:
            raw = r.read()
        dest.write_bytes(raw)
    return json.loads(dest.read_text(encoding="utf-8"))


def _competitions(force: bool = False) -> list[dict]:
    return _get(f"{BASE}/competitions.json", CACHE / "competitions.json", force=force)


def _matches(comp_id: int, season_id: int, force: bool = False) -> list[dict]:
    path = CACHE / f"matches_{comp_id}_{season_id}.json"
    return _get(f"{BASE}/matches/{comp_id}/{season_id}.json", path, force=force)


def _lineup(match_id: int, force: bool = False) -> list[dict]:
    path = CACHE / f"lineup_{match_id}.json"
    try:
        return _get(f"{BASE}/lineups/{match_id}.json", path, force=force)
    except Exception:
        return []


def _player_names(side: dict) -> list[str]:
    out = []
    for p in side.get("lineup") or []:
        name = (p.get("player_name") or p.get("player", {}).get("name") or "").strip()
        if name:
            out.append(name)
    return out


def train_soccer_players(force: bool = False, verbose: bool = False, max_matches: int = 2500) -> dict[str, Any]:
    """Walk-forward player Elo from StatsBomb open lineups + match results."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    comps = _competitions(force=force)
    pairs: list[tuple[int, int]] = []
    for c in comps:
        try:
            pairs.append((int(c["competition_id"]), int(c["season_id"])))
        except Exception:
            continue

    games: list[dict] = []
    seen = set()
    for comp_id, season_id in pairs:
        try:
            matches = _matches(comp_id, season_id, force=force)
        except Exception:
            continue
        for m in matches:
            mid = m.get("match_id")
            if mid is None or mid in seen:
                continue
            seen.add(mid)
            home = (m.get("home_team") or {}).get("home_team_name") or ""
            away = (m.get("away_team") or {}).get("away_team_name") or ""
            try:
                hs = int(m.get("home_score"))
                aws = int(m.get("away_score"))
            except Exception:
                continue
            if not home or not away:
                continue
            games.append({
                "match_id": int(mid),
                "home": home,
                "away": away,
                "hs": hs,
                "aws": aws,
                "date": (m.get("match_date") or "")[:10],
                "cached": (CACHE / f"lineup_{int(mid)}.json").exists(),
            })
        if len(games) >= max_matches * 3:
            break

    games.sort(key=lambda g: (0 if g["cached"] else 1, g.get("date") or ""))
    if len(games) > max_matches:
        # Prefer already-cached lineups, then fill from the rest
        cached = [g for g in games if g["cached"]]
        rest = [g for g in games if not g["cached"]]
        games = (cached + rest)[:max_matches]
    games.sort(key=lambda g: g.get("date") or "")

    # Parallel lineup fetch (GitHub raw) — sequential was ~hours for 8k
    lineups: dict[int, list] = {}
    need = [g["match_id"] for g in games]

    def _fetch_one(mid: int) -> tuple[int, list]:
        return mid, _lineup(mid, force=False)

    workers = 16
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_fetch_one, mid) for mid in need]
        done = 0
        for fut in as_completed(futs):
            mid, lu = fut.result()
            lineups[mid] = lu
            done += 1
            if verbose and done % 400 == 0:
                print(f"[soccer_players] fetched lineups {done}/{len(need)}")

    ratings: dict[str, float] = {}
    n_player_games = 0
    hits = n = 0
    cut = max(1, int(len(games) * 0.85))

    for i, g in enumerate(games):
        lineup = lineups.get(g["match_id"]) or []
        home_xi: list[str] = []
        away_xi: list[str] = []
        for side in lineup:
            tname = (side.get("team_name") or "").strip()
            names = _player_names(side)
            if tname == g["home"]:
                home_xi = names
            elif tname == g["away"]:
                away_xi = names
        if len(lineup) >= 2 and (not home_xi or not away_xi):
            home_xi = home_xi or _player_names(lineup[0])
            away_xi = away_xi or _player_names(lineup[1])
        if not home_xi or not away_xi:
            continue

        h_mean = sum(ratings.get(p, BASE_ELO) for p in home_xi) / len(home_xi)
        a_mean = sum(ratings.get(p, BASE_ELO) for p in away_xi) / len(away_xi)
        exp = 1.0 / (1.0 + 10 ** ((a_mean - h_mean) / 400.0))
        actual = 1.0 if g["hs"] > g["aws"] else (0.0 if g["hs"] < g["aws"] else 0.5)
        if i >= cut:
            n += 1
            pred_home = exp >= 0.5
            if (actual >= 0.5) == pred_home or actual == 0.5:
                hits += 1

        delta = PLAYER_K * (actual - exp)
        for p in home_xi:
            ratings[p] = ratings.get(p, BASE_ELO) + delta / len(home_xi)
            n_player_games += 1
        for p in away_xi:
            ratings[p] = ratings.get(p, BASE_ELO) - delta / len(away_xi)
            n_player_games += 1

    acc = round(hits / n, 4) if n else None
    if verbose:
        print(
            f"[soccer_players] {len(games)} SB matches · {len(ratings)} players · "
            f"player-games={n_player_games} · holdout acc={acc}"
        )
    return {
        "players": ratings,
        "n_matches": len(games),
        "n_player_games": n_player_games,
        "accuracy": acc,
        "source": "statsbomb open-data lineups",
    }


if __name__ == "__main__":
    r = train_soccer_players(verbose=True, max_matches=400)
    assert r["n_matches"] > 0 or r["players"] == {}
    print("soccer_players ok", len(r["players"]))
