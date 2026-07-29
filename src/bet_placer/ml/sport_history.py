"""Deep history for basketball + cricket (teams and players).

Soccer already has martj42 internationals in historical.py. This module fills the
same gap for the other two sports from open corpora:

  basketball teams  — FiveThirtyEight nbaallelo.csv (1946→2015)
  basketball players — NocturneBear NBA box scores (2010–2024)
  cricket teams + players — Cricsheet CSV2 info files (T20I/ODI/Tests + franchises)

Walk-forward Elo only (pre-match predict → then update). Cached under
~/.bet_placer/sport_history with a weekly refresh.
"""

from __future__ import annotations

import csv
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from bet_placer.data.team_names import canon_team
from bet_placer.ml.board_train import BASE, HOME_ADV, K, _pick, _predict, _update

CACHE = Path.home() / ".bet_placer" / "sport_history"
TTL_DAYS = 7

NBA_ELO_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/data/master/nba-elo/nbaallelo.csv"
)
NBA_BOX_URLS = (
    "https://raw.githubusercontent.com/NocturneBear/NBA-Data-2010-2024/main/"
    "regular_season_box_scores_2010_2024_part_1.csv",
    "https://raw.githubusercontent.com/NocturneBear/NBA-Data-2010-2024/main/"
    "regular_season_box_scores_2010_2024_part_2.csv",
    "https://raw.githubusercontent.com/NocturneBear/NBA-Data-2010-2024/main/"
    "regular_season_box_scores_2010_2024_part_3.csv",
    "https://raw.githubusercontent.com/NocturneBear/NBA-Data-2010-2024/main/"
    "play_off_box_scores_2010_2024.csv",
)

# ponytail: info.csv only (not ball-by-ball) — enough for winner + XI; ceiling is
# no runs/wickets skill split. Upgrade: aggregate from ball CSVs per player.
CRIC_ZIPS = (
    ("t20i", "https://cricsheet.org/downloads/t20s_male_csv2.zip"),
    ("odi", "https://cricsheet.org/downloads/odis_male_csv2.zip"),
    ("test", "https://cricsheet.org/downloads/tests_male_csv2.zip"),
    ("ipl", "https://cricsheet.org/downloads/ipl_male_csv2.zip"),
    ("bbl", "https://cricsheet.org/downloads/bbl_male_csv2.zip"),
    ("psl", "https://cricsheet.org/downloads/psl_male_csv2.zip"),
    ("cpl", "https://cricsheet.org/downloads/cpl_male_csv2.zip"),
    ("blast", "https://cricsheet.org/downloads/ntb_male_csv2.zip"),
)

PLAYER_SHARE_K = 18.0  # smaller than team K — roster noise


def _fetch(url: str, dest: Path, *, force: bool = False) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    stale = (
        force
        or not dest.exists()
        or (time.time() - dest.stat().st_mtime > TTL_DAYS * 86400)
    )
    if stale:
        req = Request(url, headers={"User-Agent": "bet-placer/1.0"})
        with urlopen(req, timeout=120) as r, dest.open("wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    return dest


def _mdy_to_iso(s: str) -> str:
    """11/1/1946 or 11/01/1946 → 1946-11-01."""
    s = (s or "").strip()
    if not s:
        return ""
    if "-" in s and s[4:5] == "-":
        return s[:10]
    parts = s.replace("-", "/").split("/")
    if len(parts) != 3:
        return s
    m, d, y = parts
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _share_players(
    ratings: dict[str, float],
    winners: list[str],
    losers: list[str],
    *,
    actual: float,
) -> None:
    """Nudge every listed player by a share of the match result vs BASE."""
    if not winners and not losers:
        return
    w_mean = (
        sum(ratings.get(p, BASE) for p in winners) / len(winners) if winners else BASE
    )
    l_mean = (
        sum(ratings.get(p, BASE) for p in losers) / len(losers) if losers else BASE
    )
    exp = 1.0 / (1.0 + 10 ** (-(w_mean - l_mean) / 400.0))
    delta = PLAYER_SHARE_K * (actual - exp)
    if winners:
        step = delta / len(winners)
        for p in winners:
            ratings[p] = ratings.get(p, BASE) + step
    if losers:
        step = delta / len(losers)
        for p in losers:
            ratings[p] = ratings.get(p, BASE) - step


# ── Basketball ──────────────────────────────────────────────────────────────


def load_nba_team_games(force: bool = False) -> list[dict]:
    path = _fetch(NBA_ELO_URL, CACHE / "nbaallelo.csv", force=force)
    games: list[dict] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("_iscopy", "0") not in ("0", "0.0", ""):
                continue
            if (row.get("game_location") or "").upper() != "H":
                continue
            home = canon_team(row.get("fran_id") or row.get("team_id") or "")
            away = canon_team(row.get("opp_fran") or row.get("opp_id") or "")
            if not home or not away:
                continue
            try:
                hs = int(float(row["pts"]))
                aws = int(float(row["opp_pts"]))
            except (KeyError, ValueError, TypeError):
                continue
            if hs == aws:
                continue  # 2-way moneyline
            games.append({
                "date": _mdy_to_iso(row.get("date_game") or ""),
                "home": home,
                "away": away,
                "hs": hs,
                "as": aws,
                "league": row.get("lg_id") or "NBA",
            })
    games.sort(key=lambda g: g["date"])
    return games


def load_nba_player_games(force: bool = False) -> list[dict]:
    """One record per game: home/away rosters + winner side."""
    by_game: dict[str, dict[str, Any]] = {}
    for i, url in enumerate(NBA_BOX_URLS):
        path = _fetch(url, CACHE / f"nba_box_{i}.csv", force=force)
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                gid = str(row.get("gameId") or row.get("GAME_ID") or "")
                if not gid:
                    continue
                mins = (row.get("minutes") or row.get("MIN") or "").strip()
                if not mins or mins.upper().startswith("DNP"):
                    continue
                name = (row.get("personName") or row.get("PLAYER_NAME") or "").strip()
                team = canon_team(
                    row.get("teamTricode")
                    or row.get("teamName")
                    or row.get("TEAM_ABBREVIATION")
                    or ""
                )
                if not name or not team:
                    continue
                try:
                    pts = float(row.get("points") or row.get("PTS") or 0)
                except (TypeError, ValueError):
                    pts = 0.0
                g = by_game.setdefault(
                    gid,
                    {"date": (row.get("game_date") or row.get("GAME_DATE") or "")[:10],
                     "teams": {}},
                )
                t = g["teams"].setdefault(team, {"players": [], "pts": 0.0})
                t["players"].append(name)
                t["pts"] += pts

    out: list[dict] = []
    for gid, g in by_game.items():
        teams = list(g["teams"].items())
        if len(teams) != 2:
            continue
        (t1, s1), (t2, s2) = teams
        if s1["pts"] == s2["pts"]:
            continue
        if s1["pts"] > s2["pts"]:
            win, lose = t1, t2
        else:
            win, lose = t2, t1
        out.append({
            "date": g["date"],
            "home": win,  # designation irrelevant for 2-way player share
            "away": lose,
            "winners": s1["players"] if win == t1 else s2["players"],
            "losers": s2["players"] if win == t1 else s1["players"],
        })
    out.sort(key=lambda r: r["date"])
    return out


def train_basketball(force: bool = False) -> dict[str, Any]:
    ha = HOME_ADV["basketball"]
    ratings: dict[str, float] = {}
    hits = scored = 0
    for g in load_nba_team_games(force=force):
        probs = _predict(ratings, g["home"], g["away"], "basketball")
        pred = _pick(probs, two_way=True)
        res = "H" if g["hs"] > g["as"] else "A"
        scored += 1
        hits += int(pred == res)
        _update(ratings, g["home"], g["away"], res, ha)

    players: dict[str, float] = {}
    p_games = 0
    for g in load_nba_player_games(force=force):
        _share_players(players, g["winners"], g["losers"], actual=1.0)
        p_games += 1

    return {
        "elo": {t: round(v, 1) for t, v in ratings.items()},
        "players": {p: round(v, 1) for p, v in players.items()},
        "n_matches": scored,
        "n_player_games": p_games,
        "accuracy": round(hits / scored, 4) if scored else None,
        "source": "FiveThirtyEight nbaallelo + NocturneBear box scores",
    }


# ── Cricket ─────────────────────────────────────────────────────────────────


def _parse_info_csv(text: str) -> dict[str, Any] | None:
    teams: list[str] = []
    players: list[tuple[str, str]] = []
    date = winner = outcome = ""
    for raw in text.splitlines():
        if not raw.startswith("info,"):
            continue
        # csv-aware enough for quoted commas in rare fields
        try:
            parts = next(csv.reader([raw]))
        except Exception:
            continue
        if len(parts) < 3 or parts[0] != "info":
            continue
        key = parts[1]
        if key == "team":
            teams.append(parts[2])
        elif key == "date":
            date = parts[2].replace("/", "-")
        elif key == "winner":
            winner = parts[2]
        elif key == "outcome":
            outcome = parts[2]
        elif key == "player" and len(parts) >= 4:
            players.append((parts[2], parts[3]))
    if len(teams) < 2 or not date:
        return None
    w = (winner or "").strip().lower()
    o = (outcome or "").strip().lower()
    if not w or w in ("no result", "draw", "tie", "tied") or "no result" in o or "draw" in o:
        return None
    home, away = teams[0], teams[1]
    if w == home.lower():
        res = "H"
    elif w == away.lower():
        res = "A"
    else:
        ch, ca, cw = canon_team(home), canon_team(away), canon_team(winner)
        if cw == ch:
            res = "H"
        elif cw == ca:
            res = "A"
        else:
            return None
    by_team: dict[str, list[str]] = defaultdict(list)
    for t, p in players:
        by_team[t].append(p)
    return {
        "date": date,
        "home": canon_team(home),
        "away": canon_team(away),
        "res": res,
        "home_players": by_team.get(home, []),
        "away_players": by_team.get(away, []),
    }


def load_cricket_matches(force: bool = False) -> list[dict]:
    rows: list[dict] = []
    for key, url in CRIC_ZIPS:
        path = _fetch(url, CACHE / f"cricket_{key}.zip", force=force)
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if not name.endswith("_info.csv"):
                    continue
                try:
                    text = zf.read(name).decode("utf-8", errors="replace")
                except Exception:
                    continue
                m = _parse_info_csv(text)
                if not m:
                    continue
                m["league"] = key
                rows.append(m)
    rows.sort(key=lambda r: r["date"])
    return rows


def train_cricket(force: bool = False) -> dict[str, Any]:
    ha = HOME_ADV["cricket"]
    ratings: dict[str, float] = {}
    players: dict[str, float] = {}
    hits = scored = 0
    for g in load_cricket_matches(force=force):
        home, away, res = g["home"], g["away"], g["res"]
        if not home or not away:
            continue
        probs = _predict(ratings, home, away, "cricket")
        pred = _pick(probs, two_way=True)
        scored += 1
        hits += int(pred == res)
        _update(ratings, home, away, res, ha)

        winners = g["home_players"] if res == "H" else g["away_players"]
        losers = g["away_players"] if res == "H" else g["home_players"]
        _share_players(players, winners, losers, actual=1.0)

    return {
        "elo": {t: round(v, 1) for t, v in ratings.items()},
        "players": {p: round(v, 1) for p, v in players.items()},
        "n_matches": scored,
        "n_player_games": scored,
        "accuracy": round(hits / scored, 4) if scored else None,
        "source": "Cricsheet T20I/ODI/Tests + IPL/BBL/PSL/CPL/Blast",
    }


# ── Public entry ────────────────────────────────────────────────────────────


def train_sport_history(force: bool = False, verbose: bool = False) -> dict[str, Any]:
    bb = train_basketball(force=force)
    ck = train_cricket(force=force)
    soccer_club: dict[str, Any] = {}
    soccer_players: dict[str, Any] = {"players": {}, "n_matches": 0, "n_player_games": 0}
    try:
        from bet_placer.ml.soccer_club import train_club_soccer
        soccer_club = train_club_soccer(force=force, verbose=verbose)
    except Exception as exc:
        if verbose:
            print(f"[sport_history] club soccer skipped: {exc}")
        soccer_club = {"elo": {}, "n_matches": 0, "accuracy": None, "source": "unavailable"}
    try:
        from bet_placer.ml.soccer_players import train_soccer_players
        soccer_players = train_soccer_players(force=force, verbose=verbose, max_matches=2500)
    except Exception as exc:
        if verbose:
            print(f"[sport_history] soccer players skipped: {exc}")

    if verbose:
        print(
            f"[sport_history] basketball: {bb['n_matches']} team games · "
            f"{len(bb['elo'])} franchises · {len(bb['players'])} players · "
            f"acc={bb['accuracy']}"
        )
        print(
            f"[sport_history] cricket: {ck['n_matches']} matches · "
            f"{len(ck['elo'])} sides · {len(ck['players'])} players · "
            f"acc={ck['accuracy']}"
        )
        if soccer_club.get("n_matches"):
            print(
                f"[sport_history] soccer clubs: {soccer_club['n_matches']} games · "
                f"{len(soccer_club.get('elo') or {})} clubs · acc={soccer_club.get('accuracy')}"
            )
        if soccer_players.get("players"):
            print(
                f"[sport_history] soccer players: {len(soccer_players['players'])} · "
                f"matches={soccer_players.get('n_matches')} · "
                f"acc={soccer_players.get('accuracy')}"
            )
    return {
        "elo_by_sport": {
            "basketball": bb["elo"],
            "cricket": ck["elo"],
            "soccer": soccer_club.get("elo") or {},
        },
        "player_elo": {
            "basketball": bb["players"],
            "cricket": ck["players"],
            "soccer": soccer_players.get("players") or {},
        },
        "counts": {
            "basketball": bb["n_matches"],
            "cricket": ck["n_matches"],
            "soccer": soccer_club.get("n_matches") or 0,
        },
        "player_games": {
            "basketball": bb["n_player_games"],
            "cricket": ck["n_player_games"],
            "soccer": soccer_players.get("n_player_games") or 0,
        },
        "player_counts": {
            "basketball": len(bb["players"]),
            "cricket": len(ck["players"]),
            "soccer": len(soccer_players.get("players") or {}),
        },
        "accuracy": {
            "basketball": bb["accuracy"],
            "cricket": ck["accuracy"],
            "soccer": soccer_club.get("accuracy"),
        },
        "sources": {
            "basketball": bb["source"],
            "cricket": ck["source"],
            "soccer": soccer_club.get("source") or "football-data.co.uk",
            "soccer_players": soccer_players.get("source") or "statsbomb",
        },
        "n_matches": bb["n_matches"] + ck["n_matches"] + int(soccer_club.get("n_matches") or 0),
    }


def apply_sport_history(params: dict, report: dict) -> dict:
    by = report.get("elo_by_sport") or {}
    elo_by = dict(params.get("elo_by_sport") or {})
    for sport in ("basketball", "cricket", "soccer"):
        if by.get(sport):
            elo_by[sport] = dict(by.get(sport) or {})
    params["elo_by_sport"] = elo_by
    params["player_elo"] = report.get("player_elo") or {}
    params["sport_history"] = {
        "counts": report.get("counts") or {},
        "player_games": report.get("player_games") or {},
        "player_counts": report.get("player_counts") or {},
        "accuracy": report.get("accuracy") or {},
        "sources": report.get("sources") or {},
    }
    params["trained_on_sport_history"] = report.get("counts") or {}
    return params
