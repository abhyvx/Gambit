"""Club soccer history from football-data.co.uk — free CSVs, no API key.

Seeds elo_by_sport['soccer'] so club boards aren't cold-started from ~0.
Also exposes closing book odds (B365*) for surebet / EV replay.
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Any

import requests

CACHE_DIR = Path.home() / ".bet_placer" / "club_soccer"
CACHE_TTL = 7 * 24 * 3600

# Major + second tiers × deep seasons (football-data.co.uk codes)
_LEAGUES = (
    ("E0", "EPL"),
    ("E1", "Championship"),
    ("E2", "League One"),
    ("E3", "League Two"),
    ("SP1", "La Liga"),
    ("SP2", "La Liga 2"),
    ("I1", "Serie A"),
    ("I2", "Serie B"),
    ("D1", "Bundesliga"),
    ("D2", "Bundesliga 2"),
    ("F1", "Ligue 1"),
    ("F2", "Ligue 2"),
    ("N1", "Eredivisie"),
    ("P1", "Primeira"),
    ("SC0", "Scottish Prem"),
    ("B1", "Belgium Jupiler"),
    ("T1", "Super Lig"),
    ("G1", "Super League Greece"),
)
# Season folder tokens on football-data.co.uk — ~1993/94 → today (~32 seasons)
_SEASONS = (
    "9394", "9495", "9596", "9697", "9798", "9899", "9900",
    "0001", "0102", "0203", "0304", "0405", "0506", "0607", "0708", "0809", "0910",
    "1011", "1112", "1213", "1314", "1415", "1516", "1617", "1718", "1819", "1920",
    "2021", "2122", "2223", "2324", "2425", "2526",
)

_BASE = "https://www.football-data.co.uk/mmz4281"


def _url(season: str, code: str) -> str:
    return f"{_BASE}/{season}/{code}.csv"


def _fetch_csv(season: str, code: str) -> list[dict[str, str]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{season}_{code}.csv"
    now = time.time()
    if path.exists() and now - path.stat().st_mtime < CACHE_TTL:
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            r = requests.get(_url(season, code), timeout=25, headers={"User-Agent": "Gambit/1.0"})
            if not r.ok or len(r.content) < 200:
                return []
            text = r.text
            path.write_text(text, encoding="utf-8")
        except Exception:
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                return []
    rows: list[dict[str, str]] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if row.get("HomeTeam") and row.get("AwayTeam") and row.get("FTHG") not in (None, ""):
                rows.append(row)
    except Exception:
        return []
    return rows


def load_club_matches(max_rows: int | None = None) -> list[dict[str, Any]]:
    """Chronological club results with optional B365 closing prices."""
    out: list[dict[str, Any]] = []
    for season in _SEASONS:
        for code, league in _LEAGUES:
            for row in _fetch_csv(season, code):
                try:
                    hs, aws = int(row["FTHG"]), int(row["FTAG"])
                except Exception:
                    continue
                ftr = (row.get("FTR") or "").upper()
                if ftr not in ("H", "D", "A"):
                    ftr = "H" if hs > aws else ("A" if aws > hs else "D")
                date = row.get("Date") or ""
                # DD/MM/YY or DD/MM/YYYY
                kick = date
                try:
                    parts = date.replace("-", "/").split("/")
                    if len(parts) == 3:
                        d, m, y = parts
                        y = int(y)
                        if y < 100:
                            y += 2000
                        kick = f"{y:04d}-{int(m):02d}-{int(d):02d}"
                except Exception:
                    pass
                def _f(key: str) -> float | None:
                    try:
                        v = float(row.get(key) or 0)
                        return v if v > 1.01 else None
                    except Exception:
                        return None
                def _i(key: str) -> int | None:
                    try:
                        v = row.get(key)
                        if v in (None, ""):
                            return None
                        return int(float(v))
                    except (TypeError, ValueError):
                        return None
                out.append({
                    "date": kick,
                    "home": row["HomeTeam"].strip(),
                    "away": row["AwayTeam"].strip(),
                    "hs": hs,
                    "aws": aws,
                    "res": ftr,
                    "league": league,
                    "season": season,
                    "b365_h": _f("B365H") or _f("B365CH"),
                    "b365_d": _f("B365D") or _f("B365CD"),
                    "b365_a": _f("B365A") or _f("B365CA"),
                    "avg_h": _f("AvgH") or _f("AvgCH"),
                    "avg_d": _f("AvgD") or _f("AvgCD"),
                    "avg_a": _f("AvgA") or _f("AvgCA"),
                    # Niche fuel (football-data HC/AC corners, HY/AY yellows)
                    "hc": _i("HC"),
                    "ac": _i("AC"),
                    "hy": _i("HY"),
                    "ay": _i("AY"),
                })
    out.sort(key=lambda g: g.get("date") or "")
    if max_rows and len(out) > max_rows:
        out = out[-max_rows:]
    return out


def train_club_soccer(force: bool = False, verbose: bool = False) -> dict[str, Any]:
    """Walk-forward Elo on club results → ratings + accuracy."""
    from bet_placer.data.team_names import canon_team

    games = load_club_matches()
    if not games:
        return {
            "elo": {}, "n_matches": 0, "accuracy": None,
            "source": "football-data.co.uk (empty)",
        }

    elo: dict[str, float] = {}
    BASE, K, HA = 1500.0, 22.0, 65.0
    hits = n = 0
    # Holdout: last 15%
    cut = max(1, int(len(games) * 0.85))

    def rating(t: str) -> float:
        return elo.setdefault(canon_team(t), BASE)

    for i, g in enumerate(games):
        h, a = g["home"], g["away"]
        rh, ra = rating(h), rating(a)
        # Draw shrinks when Elo gap is large (fixed 0.28 made favorites look coin-flip)
        gap = abs((rh + HA) - ra)
        draw_mass = max(0.16, min(0.30, 0.30 - gap / 1800.0))
        exp_h = 1.0 / (1.0 + 10 ** ((ra - (rh + HA)) / 400.0))
        ph = (1 - draw_mass) * exp_h
        pa = (1 - draw_mass) * (1 - exp_h)
        pd = draw_mass
        pred = "H" if ph >= pd and ph >= pa else ("A" if pa >= pd else "D")
        conf = max(ph, pd, pa)
        # Score only clear leans — raw 3-way pick-everything sits ~49% forever
        if i >= cut and conf >= 0.45:
            n += 1
            if pred == g["res"]:
                hits += 1
        # Update Elo with 1/0.5/0
        score_h = 1.0 if g["res"] == "H" else (0.5 if g["res"] == "D" else 0.0)
        eh = 1.0 / (1.0 + 10 ** ((ra - (rh + HA)) / 400.0))
        elo[canon_team(h)] = rh + K * (score_h - eh)
        elo[canon_team(a)] = ra + K * ((1.0 - score_h) - (1.0 - eh))

    acc = round(hits / n, 4) if n else None
    if verbose:
        print(f"[club_soccer] {len(games)} games · {len(elo)} clubs · holdout acc={acc} (n={n})")
    return {
        "elo": elo,
        "n_matches": len(games),
        "accuracy": acc,
        "holdout_n": n,
        "source": "football-data.co.uk major leagues",
        "games": games,
    }
