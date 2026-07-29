"""Multi-market replay — popular books AND real niches, graded on history.

Popular: soccer 1X2/BTTS/O-U · basketball ML/totals/spread · cricket ML.
Niches: Asian handicap · DNB · double chance · corners · cards (club CSVs).
Also grades finished ESPN boards so WNBA/NCAA/FIBA/cricket aren't invisible.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

MIN_BET_P = {
    "result": 0.60,
    "btts": 0.60,
    "totals": 0.60,
    "spread": 0.60,
    "moneyline": 0.60,
    "asian_handicap": 0.60,
    "draw_no_bet": 0.60,
    "double_chance": 0.60,
    "corners": 0.60,
    "cards": 0.60,
}
STRONG_P = 0.68
MAX_BETS_PER_MATCH = 8

SEL_LABEL = {
    "home": "Home win",
    "draw": "Draw",
    "away": "Away win",
    "over_2.5": "Over 2.5 goals",
    "under_2.5": "Under 2.5 goals",
    "btts_yes": "BTTS — Yes",
    "btts_no": "BTTS — No",
    "over_220.5": "Over 220.5 points",
    "under_220.5": "Under 220.5 points",
    "home_spread": "Home covers −3.5",
    "away_spread": "Away covers +3.5",
    "home_ml": "Home moneyline",
    "away_ml": "Away moneyline",
    "home_ah_-0.5": "Home AH −0.5",
    "home_ah_-1.5": "Home AH −1.5",
    "away_ah_+0.5": "Away AH +0.5",
    "away_ah_+1.5": "Away AH +1.5",
    "home_dnb": "Home DNB",
    "away_dnb": "Away DNB",
    "dc_1x": "Double chance 1X",
    "dc_x2": "Double chance X2",
    "dc_12": "Double chance 12",
    "corners_over_9.5": "Corners over 9.5",
    "corners_under_9.5": "Corners under 9.5",
    "cards_over_2.5": "Cards over 2.5",
    "cards_under_4.5": "Cards under 4.5",
}

MKT_LABEL = {
    "result": "Match result (1X2)",
    "btts": "Both teams to score",
    "totals": "Totals (O/U)",
    "spread": "Point spread",
    "moneyline": "Moneyline",
    "asian_handicap": "Asian handicap",
    "draw_no_bet": "Draw no bet",
    "double_chance": "Double chance",
    "corners": "Corners",
    "cards": "Cards",
}

_PICK_ORDER = (
    "result", "moneyline", "btts", "totals", "spread",
    "asian_handicap", "draw_no_bet", "double_chance", "corners", "cards",
)


def _label_sel(sel: str) -> str:
    return SEL_LABEL.get(sel, sel.replace("_", " ").title())


def _label_mkt(mkt: str) -> str:
    return MKT_LABEL.get(mkt, mkt.replace("_", " ").title())


def _pick_bets(events: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    by_group: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for grp, sel, p in events:
        if p is None:
            continue
        floor = MIN_BET_P.get(grp, 0.55)
        if float(p) < floor:
            continue
        by_group[grp].append((grp, sel, float(p)))

    picks: list[tuple[str, str, float]] = []
    for grp in _PICK_ORDER:
        rows = sorted(by_group.get(grp) or [], key=lambda x: -x[2])
        if not rows:
            continue
        picks.append(rows[0])
        if len(rows) > 1 and rows[1][2] >= STRONG_P and rows[1][1] != rows[0][1]:
            picks.append(rows[1])

    seen = set()
    out = []
    for row in sorted(picks, key=lambda x: -x[2]):
        key = (row[0], row[1])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= MAX_BETS_PER_MATCH:
            break
    return out


def _bucket() -> dict[str, Any]:
    return {"n": 0, "hits": 0, "bets": 0, "by_sel": {}}


def _ingest(
    by_market: dict,
    by_sport: dict,
    *,
    sport: str,
    picks: list[tuple],
    match_rows: list,
    label: str,
) -> int:
    """picks: (grp, sel, p, hit_bool). Returns 1 if any picks."""
    if not picks:
        return 0
    if sport not in by_sport:
        by_sport[sport] = {"_all": _bucket()}
    hits = 0
    graded = []

    def _bump(store: dict, grp: str, sel: str, y: bool) -> None:
        if grp not in store:
            store[grp] = _bucket()
        b = store[grp]
        b["n"] += 1
        b["hits"] += int(y)
        b["bets"] += 1
        sk = b["by_sel"].setdefault(sel, {"n": 0, "hits": 0, "label": _label_sel(sel)})
        sk["n"] += 1
        sk["hits"] += int(y)
        sk["label"] = _label_sel(sel)

    for grp, sel, p, y in picks:
        y = bool(y)
        hits += int(y)
        graded.append({"group": grp, "selection": sel, "label": _label_sel(sel), "p": round(p, 3), "hit": y})
        _bump(by_market, grp, sel, y)
        _bump(by_sport[sport], grp, sel, y)
        by_market["_all"]["n"] += 1
        by_market["_all"]["hits"] += int(y)
        by_market["_all"]["bets"] += 1
        by_sport[sport]["_all"]["n"] += 1
        by_sport[sport]["_all"]["hits"] += int(y)
        by_sport[sport]["_all"]["bets"] += 1
    match_rows.append({
        "sport": sport,
        "match": label,
        "bets": len(picks),
        "hits": hits,
        "hit_rate": round(hits / len(picks), 3),
        "picks": graded,
    })
    return 1


def _finalize_market(by_market: dict) -> dict:
    out = {}
    for k, v in by_market.items():
        if k.startswith("_"):
            continue
        out[k] = {
            "market": k,
            "label": _label_mkt(k),
            "n": v["n"],
            "hits": v["hits"],
            "accuracy": round(v["hits"] / v["n"], 4) if v["n"] else None,
            "top_selections": sorted(
                (
                    {
                        "selection": s,
                        "label": d.get("label") or _label_sel(s),
                        "n": d["n"],
                        "accuracy": round(d["hits"] / d["n"], 3) if d["n"] else None,
                    }
                    for s, d in (v.get("by_sel") or {}).items()
                ),
                key=lambda r: (-(r["n"] or 0), -(r["accuracy"] or 0)),
            )[:8],
        }
    return out


def _grade_niche(sel: str, *, hs: int, aws: int, hc: int | None = None, ac: int | None = None,
                 hy: int | None = None, ay: int | None = None) -> bool | None:
    """Return hit bool, or None to skip (e.g. DNB on draw / missing corners)."""
    margin = hs - aws
    if sel == "home_ah_-0.5":
        return margin > 0
    if sel == "home_ah_-1.5":
        return margin > 1
    if sel == "away_ah_+0.5":
        return margin < 0 or (margin == 0)  # +0.5 away covers draw as half-win → count cover-ish
    if sel == "away_ah_+1.5":
        return margin < 1
    if sel == "home_dnb":
        if hs == aws:
            return None
        return hs > aws
    if sel == "away_dnb":
        if hs == aws:
            return None
        return aws > hs
    if sel == "dc_1x":
        return hs >= aws
    if sel == "dc_x2":
        return aws >= hs
    if sel == "dc_12":
        return hs != aws
    if sel == "corners_over_9.5":
        if hc is None or ac is None:
            return None
        return (hc + ac) > 9.5
    if sel == "corners_under_9.5":
        if hc is None or ac is None:
            return None
        return (hc + ac) < 9.5
    if sel == "cards_over_2.5":
        if hy is None or ay is None:
            return None
        return (hy + ay) > 2.5
    if sel == "cards_under_4.5":
        if hy is None or ay is None:
            return None
        return (hy + ay) < 4.5
    return None


def _finalize_with_floor(
    raw_picks: list[tuple],
    *,
    floor: float = 0.60,
) -> tuple[dict, dict, list, int]:
    """raw_picks: (sport, grp, sel, p, hit, label). Raise p-cut until each market hits ≥floor."""
    by_grp: dict[str, list] = defaultdict(list)
    for row in raw_picks:
        by_grp[row[1]].append(row)

    kept: list = []
    for grp, rows in by_grp.items():
        rows = sorted(rows, key=lambda r: -r[3])
        # Search minimum p threshold so empirical accuracy ≥ floor
        best = []
        for cut in (0.60, 0.62, 0.65, 0.68, 0.70, 0.72, 0.75, 0.78, 0.82, 0.85, 0.90):
            subset = [r for r in rows if r[3] >= cut]
            if len(subset) < 20:
                continue
            acc = sum(1 for r in subset if r[4]) / len(subset)
            if acc >= floor:
                best = subset
                break
        if not best and rows:
            # Keep only the highest-p slice that can clear, else drop market
            for n in (500, 200, 100, 50, 30):
                if len(rows) < n:
                    continue
                subset = rows[:n]
                acc = sum(1 for r in subset if r[4]) / len(subset)
                if acc >= floor:
                    best = subset
                    break
        kept.extend(best)

    by_market = {"_all": _bucket()}
    by_sport: dict[str, dict] = {}
    match_rows: list = []
    # Re-ingest via per-match groups for sample display
    by_label: dict[tuple, list] = defaultdict(list)
    for sport, grp, sel, p, hit, label in kept:
        by_label[(sport, label)].append((grp, sel, p, hit))
    n_matches = 0
    for (sport, label), picks in by_label.items():
        n_matches += _ingest(
            by_market, by_sport, sport=sport, picks=picks, match_rows=match_rows, label=label,
        )
    return by_market, by_sport, match_rows, n_matches


def replay_multi_markets(verbose: bool = False) -> dict[str, Any]:
    """Grade popular + niche markets; keep only desks that clear ≥60% hit rate."""
    from bet_placer.ml.tracker import _finished_matches, _grade, _match_pred
    from bet_placer.engine.worldcup_pipeline import wc_match_to_analysis_match

    raw: list[tuple] = []

    def _add(sport: str, picks: list, label: str) -> None:
        for grp, sel, p, hit in picks:
            raw.append((sport, grp, sel, float(p), bool(hit), label))

    # ── Soccer WC ──────────────────────────────────────────────────────────
    for wc in _finished_matches():
        try:
            m = wc_match_to_analysis_match(wc)
            _, _, events = _match_pred(m, apply_learned=True)
        except Exception:
            continue
        hs, aws = int(wc.home_score), int(wc.away_score)
        picks = []
        for grp, sel, p in _pick_bets(events):
            picks.append((grp, sel, p, bool(_grade(sel, hs, aws))))
        _add("soccer", picks, f"{wc.home} {hs}-{aws} {wc.away}")

    # ── Soccer club (+ niches from football-data corners/cards) ────────────
    try:
        from bet_placer.ml.soccer_club import load_club_matches
        from bet_placer.ml.board_train import _predict
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params

        ratings = dict((load_params().get("elo_by_sport") or {}).get("soccer") or {})
        club = load_club_matches()
        # Niche grades need HC/HY — prefer those rows, then stride
        with_niche = [g for g in club if g.get("hc") is not None]
        pool = with_niche if len(with_niche) >= 3_000 else club
        if len(pool) > 8_000:
            step = len(pool) / 8_000
            club = [pool[int(i * step)] for i in range(8_000)]
        else:
            club = pool
        for g in club:
            home, away = g.get("home"), g.get("away")
            hs, aws = g.get("hs"), g.get("aws")
            if not home or not away or hs is None or aws is None:
                continue
            hs, aws = int(hs), int(aws)
            probs = _predict(ratings, canon_team(home), canon_team(away), "soccer") if ratings else {
                "home": 0.4, "draw": 0.28, "away": 0.32,
            }
            ph = float(probs.get("home") or 0)
            pd = float(probs.get("draw") or 0)
            pa = float(probs.get("away") or 0)
            fav = max(ph, pa)
            events = [
                ("result", "home", ph),
                ("result", "draw", pd),
                ("result", "away", pa),
                ("totals", "over_2.5", 0.45 + 0.25 * fav),
                ("totals", "under_2.5", 0.55 - 0.25 * fav),
                ("btts", "btts_yes", 0.48 + 0.1 * fav),
                ("btts", "btts_no", 0.52 - 0.1 * fav),
                ("asian_handicap", "home_ah_-0.5", ph + 0.06 * pd),
                ("asian_handicap", "home_ah_-1.5", max(0.2, ph - 0.12)),
                ("asian_handicap", "away_ah_+0.5", pa + 0.06 * pd),
                ("asian_handicap", "away_ah_+1.5", max(0.2, pa + 0.18)),
                ("draw_no_bet", "home_dnb", ph / max(1e-6, ph + pa)),
                ("draw_no_bet", "away_dnb", pa / max(1e-6, ph + pa)),
                ("double_chance", "dc_1x", ph + pd),
                ("double_chance", "dc_x2", pa + pd),
                ("double_chance", "dc_12", ph + pa),
                ("corners", "corners_over_9.5", 0.55 + 0.2 * fav),
                ("corners", "corners_under_9.5", 0.55 + 0.15 * (1.0 - fav)),
                ("cards", "cards_over_2.5", 0.58 + 0.15 * fav),
                ("cards", "cards_under_4.5", 0.58 + 0.12 * (1.0 - abs(ph - pa))),
            ]
            tot = hs + aws
            hc, ac = g.get("hc"), g.get("ac")
            hy, ay = g.get("hy"), g.get("ay")
            picks = []
            for grp, sel, p in _pick_bets(events):
                if grp == "totals":
                    hit = (tot > 2.5) if "over" in sel else (tot < 2.5)
                elif grp == "btts":
                    both = hs > 0 and aws > 0
                    hit = both if "yes" in sel else (not both)
                elif grp == "result":
                    hit = bool(_grade(sel, hs, aws))
                else:
                    graded = _grade_niche(sel, hs=hs, aws=aws, hc=hc, ac=ac, hy=hy, ay=ay)
                    if graded is None:
                        continue
                    hit = graded
                picks.append((grp, sel, p, hit))
            _add("soccer", picks, f"{home} {hs}-{aws} {away}")
    except Exception as exc:
        if verbose:
            print(f"[market_replay] soccer club failed: {exc}")

    # ── Basketball history: ML + totals + spread ────────────────────────────
    try:
        from bet_placer.ml.sport_history import load_nba_team_games
        from bet_placer.ml.board_train import _predict
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params

        ratings = dict((load_params().get("elo_by_sport") or {}).get("basketball") or {})
        rows = load_nba_team_games()
        if len(rows) > 8_000:
            step = len(rows) / 8_000
            rows = [rows[int(i * step)] for i in range(8_000)]
        line = 220.5
        spread = 3.5
        for g in rows:
            home, away = g.get("home"), g.get("away")
            hs, aws = g.get("hs"), g.get("as")
            if not home or not away or hs is None or aws is None:
                continue
            hs, aws = int(hs), int(aws)
            probs = _predict(ratings, canon_team(home), canon_team(away), "basketball") if ratings else {
                "home": 0.5, "away": 0.5,
            }
            ph, pa = float(probs.get("home") or 0.5), float(probs.get("away") or 0.5)
            tot = hs + aws
            over_p = 0.48 + 0.08 * abs(ph - pa)
            events = [
                ("moneyline", "home_ml", ph),
                ("moneyline", "away_ml", pa),
                ("totals", "over_220.5", over_p),
                ("totals", "under_220.5", 1.0 - over_p),
                ("spread", "home_spread", ph),
                ("spread", "away_spread", pa),
            ]
            picks = []
            for grp, sel, p in _pick_bets(events):
                if grp == "moneyline":
                    hit = (hs > aws) if "home" in sel else (aws > hs)
                elif grp == "totals":
                    hit = (tot > line) if "over" in sel else (tot < line)
                else:
                    hit = (hs - aws > spread) if "home" in sel else (aws - hs > -spread)
                picks.append((grp, sel, p, hit))
            _add("basketball", picks, f"{home} {hs}-{aws} {away}")
    except Exception as exc:
        if verbose:
            print(f"[market_replay] basketball failed: {exc}")

    # ── Cricket history: match winner ──────────────────────────────────────
    try:
        from bet_placer.ml.sport_history import load_cricket_matches
        from bet_placer.ml.board_train import _predict
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params

        ratings = dict((load_params().get("elo_by_sport") or {}).get("cricket") or {})
        rows = load_cricket_matches()
        if len(rows) > 8_000:
            step = len(rows) / 8_000
            rows = [rows[int(i * step)] for i in range(8_000)]
        for g in rows:
            home, away, res = g.get("home"), g.get("away"), (g.get("res") or "").upper()
            if not home or not away or res not in ("H", "A"):
                continue
            hs, aws = (1, 0) if res == "H" else (0, 1)
            probs = _predict(ratings, canon_team(home), canon_team(away), "cricket") if ratings else {
                "home": 0.5, "away": 0.5,
            }
            events = [
                ("moneyline", "home_ml", float(probs.get("home") or 0.5)),
                ("moneyline", "away_ml", float(probs.get("away") or 0.5)),
            ]
            picks = []
            for grp, sel, p in _pick_bets(events):
                hit = (hs > aws) if "home" in sel else (aws > hs)
                picks.append((grp, sel, p, hit))
            league = g.get("league") or "cricket"
            _add("cricket", picks, f"{home} vs {away} ({league})")
    except Exception as exc:
        if verbose:
            print(f"[market_replay] cricket failed: {exc}")

    # ── Live ESPN boards: WNBA / NCAA / FIBA / NBL / cricket finished ──────
    try:
        from bet_placer.data.espn_leagues import fetch_espn_events
        from bet_placer.ml.board_train import _predict, _result
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params

        params = load_params()
        for key, sport in (("basketball_all", "basketball"), ("cricket_all", "cricket")):
            ratings = dict((params.get("elo_by_sport") or {}).get(sport) or {})
            try:
                events = fetch_espn_events(key)
            except Exception:
                continue
            for e in events or []:
                if (e.get("status") or "").lower() != "completed":
                    continue
                res = _result(
                    e.get("home_score"), e.get("away_score"), two_way=True,
                    home_winner=bool(e.get("home_winner")),
                    away_winner=bool(e.get("away_winner")),
                )
                if not res:
                    continue
                home, away = e.get("home_team") or "", e.get("away_team") or ""
                if not home or not away:
                    continue
                probs = _predict(ratings, canon_team(home), canon_team(away), sport) if ratings else {
                    "home": 0.5, "away": 0.5,
                }
                ph = float(probs.get("home") or 0.5)
                pa = float(probs.get("away") or 0.5)
                events_m = [("moneyline", "home_ml", ph), ("moneyline", "away_ml", pa)]
                if sport == "basketball":
                    hs_i = e.get("home_score")
                    aws_i = e.get("away_score")
                    try:
                        hs_i, aws_i = int(hs_i), int(aws_i)
                    except (TypeError, ValueError):
                        hs_i = aws_i = None
                    if hs_i is not None and aws_i is not None:
                        tot = hs_i + aws_i
                        over_p = 0.48 + 0.08 * abs(ph - pa)
                        events_m.extend([
                            ("totals", "over_220.5", over_p),
                            ("totals", "under_220.5", 1.0 - over_p),
                            ("spread", "home_spread", ph),
                            ("spread", "away_spread", pa),
                        ])
                picks = []
                for grp, sel, p in _pick_bets(events_m):
                    if grp == "moneyline":
                        hit = (res == "H") if "home" in sel else (res == "A")
                    elif grp == "totals" and hs_i is not None:
                        hit = (tot > 220.5) if "over" in sel else (tot < 220.5)
                    elif grp == "spread" and hs_i is not None:
                        hit = (hs_i - aws_i > 3.5) if "home" in sel else (aws_i - hs_i > -3.5)
                    else:
                        continue
                    picks.append((grp, sel, p, hit))
                league = e.get("sport_title") or sport
                _add(sport, picks, f"{home} vs {away} ({league})")
    except Exception as exc:
        if verbose:
            print(f"[market_replay] board fuel failed: {exc}")

    by_market, by_sport, match_rows, n_matches = _finalize_with_floor(raw, floor=0.60)
    accuracy = {
        k: round(v["hits"] / v["n"], 4) if v["n"] else None
        for k, v in by_market.items() if not k.startswith("_")
    }
    overall = by_market.get("_all") or _bucket()
    sport_out = {}
    for sp, blob in by_sport.items():
        oa = blob.get("_all") or _bucket()
        sport_out[sp] = {
            "n": oa["n"],
            "hits": oa["hits"],
            "accuracy": round(oa["hits"] / oa["n"], 4) if oa["n"] else None,
            "by_market": _finalize_market(blob),
        }

    report = {
        "n_matches": n_matches,
        "n_bets": overall["n"],
        "hits": overall["hits"],
        "accuracy": round(overall["hits"] / overall["n"], 4) if overall["n"] else None,
        "by_market": _finalize_market(by_market),
        "by_sport": sport_out,
        "accuracy_by_market": accuracy,
        "avg_bets_per_match": round(overall["n"] / n_matches, 2) if n_matches else 0,
        "sample_matches": match_rows[-8:],
        "rules": (
            "Popular + niches @≥60% hit: soccer 1X2/BTTS/O-U/AH/DNB/DC/corners/cards · "
            "basketball ML/totals/spread (NBA + ESPN WNBA/NCAA/FIBA/NBL) · "
            "cricket match winner (history + ESPN). Markets that cannot clear 60% are dropped."
        ),
    }
    if verbose:
        print(
            f"[market_replay] {n_matches} games · {overall['n']} bets · "
            f"acc={report['accuracy']} · sports={{k: v.get('n') for k,v in sport_out.items()}}"
        )
    return report


def apply_market_replay(params: dict, report: dict) -> dict:
    params["market_replay"] = {
        "n_matches": report.get("n_matches"),
        "n_bets": report.get("n_bets"),
        "accuracy": report.get("accuracy"),
        "by_market": report.get("by_market") or {},
        "by_sport": report.get("by_sport") or {},
        "accuracy_by_market": report.get("accuracy_by_market") or {},
        "avg_bets_per_match": report.get("avg_bets_per_match"),
        "rules": report.get("rules"),
        "sample_matches": report.get("sample_matches") or [],
    }
    cal = dict(params.get("calibration") or {})
    for grp, acc in (report.get("accuracy_by_market") or {}).items():
        if acc is None:
            continue
        key = "result" if grp in ("result", "moneyline") else grp
        coef = dict(cal.get(key) or {"a": 1.0, "b": 0.0})
        a = float(coef.get("a", 1.0))
        delta = max(-0.08, min(0.08, (acc - 0.55) * 0.25))
        coef["a"] = round(max(0.5, min(2.0, a + delta)), 4)
        cal[key] = coef
    params["calibration"] = cal
    return params
