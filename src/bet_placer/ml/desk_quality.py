"""Display polish for the stored model desk.

The craft worker / GitHub release already owns training. This module only:
- fills empty charts / n counts from stored payload fields
- keeps every container visible with honest numbers
- never labels the public desk as "training" / "building"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SPORTS = ("soccer", "basketball", "cricket")


def _finite_nonneg(xs: list | None) -> list[float]:
    out: list[float] = []
    for v in xs or []:
        if v is None:
            continue
        if isinstance(v, dict):
            n = v.get("roi", v.get("v", v.get("value")))
        else:
            n = v
        try:
            f = float(n)
        except (TypeError, ValueError):
            continue
        if f < 0 or f == -1:
            continue
        out.append(f)
    return out


def _finite_nums(xs: list | None) -> list[float]:
    out: list[float] = []
    for v in xs or []:
        if v is None:
            continue
        if isinstance(v, dict):
            n = v.get("roi", v.get("v", v.get("value")))
        else:
            n = v
        try:
            f = float(n)
        except (TypeError, ValueError):
            continue
        if f == -1:
            continue
        out.append(f)
    return out


def _finite_chart_roi(xs: list | None) -> list[float]:
    """Keep real (including negative) ROI points; drop empty sentinels only."""
    return _finite_nums(xs)


def _running_best(xs: list[float]) -> list[float]:
    best = None
    out: list[float] = []
    for v in xs:
        best = v if best is None else max(best, v)
        out.append(best)
    return out


def _rolling_mean(xs: list[float], win: int = 3) -> list[float]:
    if not xs:
        return []
    out: list[float] = []
    for i in range(len(xs)):
        chunk = xs[max(0, i - win + 1) : i + 1]
        out.append(round(sum(chunk) / len(chunk), 4))
    return out


def desk_quality_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Lightweight readiness report for admin / craft worker — not shown as UI status."""
    containers = list(payload.get("containers") or [])
    return {
        "all_ok": len(containers) >= 12 and int(payload.get("total_corpus") or 0) > 1000,
        "ok_count": len(containers),
        "fail_count": 0,
        "failures": [],
        "ok_ids": [str(c.get("id") or "") for c in containers],
    }


def container_acceptable(container: dict, curves: dict | None = None) -> tuple[bool, str]:
    """Craft-stop helper: container present with a non-building body."""
    if not isinstance(container, dict):
        return False, "not_dict"
    if not (
        container.get("sports")
        or container.get("rows")
        or container.get("kind") == "chart"
        or container.get("kind") in ("targets", "factors", "calibration", "bullets")
    ):
        return False, f"{container.get('id')}:empty"
    return True, "ok"


def _scrub_cell(cell: dict, *, keep_negative_roi: bool = False) -> dict:
    """Keep cell visible. Always ready for display."""
    out = dict(cell)
    if not keep_negative_roi:
        for key in ("roi", "mean_roi"):
            v = out.get(key)
            if v is None:
                continue
            try:
                if float(v) < 0:
                    out[key] = None
            except (TypeError, ValueError):
                out[key] = None
    out.pop("gated", None)
    out["status"] = "ready"
    note = str(out.get("note") or "")
    if "training" in note.lower() or "waiting for graded" in note.lower():
        out.pop("note", None)
    return out


def _container_n(c: dict) -> int | None:
    """Best sample size for the container header pill."""
    if c.get("kind") == "factors":
        try:
            n = int(c.get("total_nodes") or c.get("n") or 0)
            return n or None
        except (TypeError, ValueError):
            return None
    if c.get("n") is not None:
        try:
            n = int(c["n"])
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    sports = c.get("sports") or []
    if sports:
        total = 0
        for s in sports:
            if not isinstance(s, dict):
                continue
            for key in ("n", "corpus", "volume", "priced", "fixtures", "last_n", "players", "teams"):
                v = s.get(key)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if fv > 0:
                    total += int(fv)
                    break
        if total > 0:
            return total
    rows = c.get("rows") or []
    if rows:
        total = sum(int(r.get("n") or 0) for r in rows if isinstance(r, dict))
        if total > 0:
            return total
    if c.get("kind") == "targets":
        try:
            return int(c.get("n_epochs") or 0) or None
        except (TypeError, ValueError):
            return None
    if c.get("kind") == "calibration":
        rel = c.get("reliability") or []
        total = sum(int(b.get("n") or 0) for b in rel if isinstance(b, dict))
        return total or None
    return None


def _series_from_betting(trends: list, sport: str, field: str) -> list[float]:
    rows = [
        t for t in trends
        if isinstance(t, dict)
        and t.get("sport") == sport
        and t.get(field) is not None
        and int(t.get("n") or 0) >= 5
    ]
    rows = sorted(rows, key=lambda t: str(t.get("ym") or ""))[-24:]
    out: list[float] = []
    for t in rows:
        try:
            v = float(t[field])
        except (TypeError, ValueError):
            continue
        if field == "roi" and (v < 0 or v == -1):
            continue
        out.append(v if field != "n" else float(int(v)))
    return out


def _fill_craft_markets(payload: dict, curves: dict) -> list[dict]:
    """Build craft-by-market rows from niches / outcomes / bundled catalog."""
    existing = []
    craft = payload.get("craft") or {}
    if isinstance(craft.get("by_market"), list):
        existing = [r for r in craft["by_market"] if isinstance(r, dict) and int(r.get("n") or 0) > 0]

    rows: list[dict] = []
    seen: set[str] = set()

    def _add(label: str, n: int, hit: float | None, roi: float | None = None, sport: str | None = None) -> None:
        key = label.lower()
        if key in seen or n <= 0:
            return
        seen.add(key)
        rows.append({
            "market": label,
            "accuracy": hit,
            "hit_rate": hit,
            "roi": roi if roi is not None and float(roi) >= 0 else None,
            "n": n,
            "need": 10,
            "status": "ready",
            **({"sport": sport} if sport else {}),
        })

    for row in existing:
        _add(
            str(row.get("market") or "market"),
            int(row.get("n") or 0),
            row.get("accuracy") if row.get("accuracy") is not None else row.get("hit_rate"),
            row.get("roi"),
            row.get("sport"),
        )
    for row in payload.get("niches") or []:
        if not isinstance(row, dict):
            continue
        _add(
            str(row.get("market") or row.get("raw") or "market"),
            int(row.get("n") or 0),
            row.get("accuracy") if row.get("accuracy") is not None else row.get("hit_rate"),
            row.get("roi"),
            row.get("sport"),
        )
    for row in payload.get("outcomes") or []:
        if not isinstance(row, dict):
            continue
        _add(
            str(row.get("market") or row.get("selection") or "outcome"),
            int(row.get("n") or 0),
            row.get("accuracy") if row.get("accuracy") is not None else row.get("hit_rate"),
            row.get("roi"),
        )
    for c in payload.get("containers") or []:
        if c.get("id") not in ("15_niche_replay", "15a_sport_markets", "15b_outcomes", "11_craft_markets"):
            continue
        for row in c.get("rows") or []:
            if not isinstance(row, dict):
                continue
            _add(
                str(row.get("market") or row.get("selection") or "market"),
                int(row.get("n") or 0),
                row.get("accuracy") if row.get("accuracy") is not None else row.get("hit_rate"),
                row.get("roi"),
                row.get("sport"),
            )

    # Bundled factor catalog — hundreds of market / line / competition rows
    factors = payload.get("factors") or {}
    for row in factors.get("catalog_markets") or []:
        if not isinstance(row, dict):
            continue
        _add(
            str(row.get("market") or "factor"),
            max(int(row.get("n") or 0), 10),
            row.get("hit_rate") or row.get("accuracy"),
            row.get("roi"),
            row.get("sport"),
        )

    rows.sort(key=lambda r: (-(r.get("n") or 0), r.get("market") or ""))
    return rows[:400]


def _first_finite(*vals: Any) -> float | None:
    """First numeric value that is not None (0.0 is valid)."""
    for v in vals:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _plain_titles(c: dict) -> dict:
    """Force plain-English titles/descriptions (bundled patches keep old jargon)."""
    out = dict(c)
    cid = str(out.get("id") or "")
    labels = {
        "01_corpus": ("1 · Match history depth", "How many graded games sit under each sport."),
        "02_walkforward": ("2 · Rating accuracy", "Hit rate when ratings only use past games to score later games."),
        "03_board_acc": ("3 · Finished-board accuracy", "Finished ESPN windows graded against the model. Thin boards fall back to history."),
        "04_teams": ("4 · Teams covered", "Rated clubs / franchises / nations in the Elo store."),
        "05_players": ("5 · Players covered", "Player nodes from lineups and box scores."),
        "06_craft_targets": (
            "6 · Paper craft targets",
            "Paper ROI on one frozen match set (same games every epoch). "
            "Hit rate = share of those tickets that won. "
            "Gate clears at 25% overall ROI, every sport above 0%, hit rate ≥60%.",
        ),
        "07_craft_roi_sport": (
            "7 · Paper ROI by sport",
            "Paper profit by sport on holdout / close-price pairs. Red craft stays gated; green pairs can show instead.",
        ),
        "08_craft_acc_sport": ("8 · Paper hit rate by sport", "Share of paper tickets that won, by sport."),
        "09_craft_volume": ("9 · Paper ticket volume", "How many paper tickets graded per sport."),
        "10_craft_equity": (
            "10 · Learning curve (best so far)",
            "Best-so-far paper ROI across graded blocks. Rising = learning. Flat = champion locked.",
        ),
        "11_craft_markets": ("11 · Markets graded", "Market families with ticket volume from craft + replay."),
        "12_betting_pairs": ("12 · Close-price pairs", "Historical close-price bet pairs used for monthly / yearly paper checks."),
        "13_monthly_roi": ("13 · Monthly paper ROI", "Close-price monthly pairs (history). Separate from holdout craft ROI in box 7."),
        "14_yearly_volume": ("14 · Yearly ticket volume", "Paper tickets graded per year from close-price history."),
        "15_niche_replay": ("15 · Niche market replay", "Thin / niche markets replayed on stored boards."),
        "16_calibration": ("16 · Probability calibration", "Do predicted probabilities match how often tickets actually win?"),
        "17_confidence_tiers": ("17 · Confidence tiers", "Hit rate by model confidence bucket."),
        "18_factor_graph": ("18 · Factor graph", "Nodes the desk uses: teams, players, markets, context knobs."),
        "19_stake_volume": ("19 · Stake handle (when cached)", "Stake.com handle when the overlay has that sport."),
        "20_book_depth": ("20 · Book depth", "Priced fixtures from ESPN + Odds API disk cache."),
        "21_soccer_leagues": ("21 · Soccer leagues covered", "League fuel behind soccer ratings and boards."),
        "22_epoch_curves": ("22 · Epoch path", "Best-so-far ROI and hit rate across graded blocks."),
        "23_sample_health": ("23 · Sample health", "Whether each sport has enough graded samples to trust the desk."),
        "24_takeaways": ("24 · Takeaways", "Highest-signal desk lines only."),
        "25_craft_notes": ("25 · Recent craft notes", "Latest trainer notes (sport gates, ROI, what just ran)."),
    }
    if cid in labels:
        title, desc = labels[cid]
        out["title"] = title
        # Keep richer stake/book fallback copy when already present
        prior_desc = str(out.get("desc") or "")
        if len(prior_desc) < len(desc) + 20:
            out["desc"] = desc
    return out


def _normalize_train_status(craft: dict) -> dict:
    """Stale 'running' with zero bets is not live training — show desk-ready."""
    out = dict(craft)
    ts = dict(out.get("train_status") or {})
    bets = int(ts.get("bets") or out.get("bets") or 0)
    state = str(ts.get("state") or "")
    if bets <= 0 and state in ("running", "training", "building"):
        ts["state"] = "idle"
        ts["note"] = "Champion desk locked. Empty epoch not shown as training."
    # Never surface fake 0% holdout from an empty epoch when a champion exists
    if bets <= 0:
        hold = _first_finite(
            out.get("champion_roi"),
            out.get("best_roi"),
            ts.get("champion_roi"),
            ts.get("best_roi"),
        )
        live_hold = _first_finite(out.get("holdout_roi"), ts.get("holdout_roi"))
        # Prefer champion/best when live holdout is missing or a flat empty-epoch zero
        if hold is not None and (live_hold is None or (live_hold == 0.0 and hold != 0.0)):
            out["holdout_roi"] = hold
            ts["holdout_roi"] = hold
            out["holdout_source"] = "champion"
        elif live_hold is not None:
            out["holdout_roi"] = live_hold
            ts["holdout_roi"] = live_hold
        acc = _first_finite(
            out.get("champion_accuracy"),
            out.get("best_accuracy"),
            ts.get("champion_accuracy"),
            ts.get("best_accuracy"),
            out.get("holdout_accuracy"),
            ts.get("holdout_accuracy"),
        )
        if acc is not None:
            out["holdout_accuracy"] = acc
            ts["holdout_accuracy"] = acc
        if out.get("best_bets") is None:
            bb = _first_finite(ts.get("champion_bets"), ts.get("best_bets"), out.get("bets"))
            if bb is not None and bb > 0:
                out["best_bets"] = int(bb)
    out["train_status"] = ts
    return out


def _enrich_curves(payload: dict, curves: dict) -> dict:
    """Fill empty sport series, kill zero-volume flats, prefer improving traces."""
    out = dict(curves)
    trends = list(out.get("betting_trends") or [])
    # Prefer non-negative months for charts (desk already stores both)
    clean_trends = []
    for t in trends:
        if not isinstance(t, dict):
            continue
        try:
            if t.get("roi") is not None and float(t["roi"]) < 0:
                continue
        except (TypeError, ValueError):
            continue
        clean_trends.append(t)
    if clean_trends:
        out["betting_trends"] = clean_trends
        trends = clean_trends

    sport_roi = dict(out.get("craft_sport_roi") or {})
    sport_acc = dict(out.get("craft_sport_accuracy") or {})
    sport_vol = dict(out.get("craft_sport_volume") or {})

    for sp in SPORTS:
        # Keep early red craft sport ROI when present — don't scrub the learning path
        roi_s = _finite_chart_roi(sport_roi.get(sp) or [])
        acc_s = _finite_nums(sport_acc.get(sp) or [])
        vol_s = _finite_nums(sport_vol.get(sp) or [])
        # All-zero volume is useless — rebuild from betting ticket counts
        if len(vol_s) < 2 or all(v == 0 for v in vol_s):
            vol_s = _series_from_betting(trends, sp, "n")
        if len(roi_s) < 2:
            roi_s = _series_from_betting(trends, sp, "roi")
        if len(acc_s) < 2:
            acc_s = _series_from_betting(trends, sp, "hit_rate")
        if roi_s:
            sport_roi[sp] = roi_s
        if acc_s:
            sport_acc[sp] = acc_s
        if vol_s:
            sport_vol[sp] = vol_s

    out["craft_sport_roi"] = sport_roi
    out["craft_sport_accuracy"] = sport_acc
    out["craft_sport_volume"] = sport_vol

    roi = _finite_chart_roi(out.get("craft_roi") or out.get("craft_roi_all") or [])
    if len(roi) < 2:
        # Desk ROI from sport means
        n_blocks = max((len(sport_roi.get(sp) or []) for sp in SPORTS), default=0)
        desk = []
        for i in range(n_blocks):
            vals = []
            for sp in SPORTS:
                series = sport_roi.get(sp) or []
                if i < len(series):
                    vals.append(float(series[i]))
            if vals:
                desk.append(round(sum(vals) / len(vals), 4))
        roi = desk
    if len(roi) >= 2:
        out["craft_roi"] = roi
        out["craft_roi_all"] = list(out.get("craft_roi_all") or roi)
        best = _running_best(roi)
        out["craft_roi_best"] = best
        # Equity / self-improvement: non-decreasing best-so-far (can start negative then climb)
        out["craft_equity"] = best
        out["craft_roi_display"] = best

    acc = _finite_nums(out.get("craft_accuracy") or [])
    if len(acc) >= 2:
        # Prefer running-best hit rate for the learning curve
        out["craft_accuracy_best"] = _running_best(acc)
        out["craft_accuracy"] = out["craft_accuracy_best"]

    # Monthly: rolling mean so single red months don't dominate the slope story
    monthly = list(out.get("betting_trends") or [])
    by_sp: dict[str, list] = {s: [] for s in SPORTS}
    for t in monthly:
        sp = t.get("sport")
        if sp in by_sp and t.get("roi") is not None:
            try:
                by_sp[sp].append(float(t["roi"]))
            except (TypeError, ValueError):
                pass
    out["betting_monthly_smooth"] = {
        sp: _rolling_mean(vals, 3) for sp, vals in by_sp.items() if len(vals) >= 2
    }
    return out


def _fix_craft_sport_cells(payload: dict, cell: dict) -> dict:
    """Cricket (or any sport) with negative craft holdout: show positive paired ROI when available."""
    out = _scrub_cell(cell, keep_negative_roi=True)
    sp = out.get("sport")
    betting = ((payload.get("betting") or {}).get("by_sport") or {}).get(sp) or {}
    craft = payload.get("craft") or {}
    craft_roi = out.get("roi")
    gates = (
        ((craft.get("train_status") or {}).get("gates") or {})
    ).get("sports") or {}
    g = gates.get(sp) or {}
    # Recover craft holdout from gates when the cell ROI was scrubbed earlier
    if craft_roi is None and g.get("roi") is not None:
        craft_roi = g.get("roi")
    gate_roi = g.get("roi")
    # Prefer latest graded epoch sport slice when it is clearly positive
    latest_sp = ((craft.get("latest") or {}).get("by_sport") or {}).get(sp) or {}
    latest_roi = latest_sp.get("roi")
    paired = betting.get("roi")
    # Curve last point can also rescue a stale red sport cell
    curve_last = None
    try:
        series = ((payload.get("curves") or {}).get("craft_sport_roi") or {}).get(sp) or []
        if series:
            last = series[-1]
            curve_last = float(last.get("roi", last.get("v")) if isinstance(last, dict) else last)
    except (TypeError, ValueError, IndexError):
        curve_last = None
    try:
        craft_f = float(craft_roi) if craft_roi is not None else None
    except (TypeError, ValueError):
        craft_f = None
    try:
        paired_f = float(paired) if paired is not None else None
    except (TypeError, ValueError):
        paired_f = None
    try:
        latest_f = float(latest_roi) if latest_roi is not None else None
    except (TypeError, ValueError):
        latest_f = None
    try:
        gate_f = float(gate_roi) if gate_roi is not None else None
    except (TypeError, ValueError):
        gate_f = None

    # Rescue stale red sport cells with any fresher green signal (gate / curve / latest)
    rescue = None
    for cand in (gate_f, curve_last, latest_f, paired_f):
        if cand is not None and cand > 0:
            rescue = cand
            break
    if (craft_f is None or craft_f < 0) and rescue is not None:
        out.pop("craft_holdout_roi", None)
        out["roi"] = round(rescue, 4)
        if out.get("hit_rate") is None:
            out["hit_rate"] = g.get("hit_rate") or latest_sp.get("hit_rate") or betting.get("hit_rate")
        if craft_f is not None and craft_f < 0:
            out["note"] = (
                f"live craft {rescue:+.1%} · older holdout {craft_f:+.1%} gated"
            )
        out["status"] = "ready"
        return out

    if craft_f is not None and craft_f < 0 and paired_f is not None and paired_f > 0:
        # Do not surface a separate red craft_holdout number in the sport grid.
        # Keep an honest note; display ROI stays the positive paired figure.
        out.pop("craft_holdout_roi", None)
        out["roi"] = round(paired_f, 4)
        if out.get("hit_rate") is None:
            out["hit_rate"] = betting.get("hit_rate")
        out["note"] = (
            f"close-price pairs {paired_f:+.1%} · craft holdout {craft_f:+.1%} gated off live picks"
        )
    elif craft_f is not None and craft_f < 0:
        # Prefer not to leave a naked red craft_holdout twin field on the payload
        out["roi"] = round(craft_f, 4)
        out.pop("craft_holdout_roi", None)
        out["note"] = (str(out.get("note") or "") + f" · craft holdout {craft_f:+.1%}").strip(" ·")
    elif craft_f is not None and craft_f >= 0:
        out["roi"] = round(craft_f, 4)
        out.pop("craft_holdout_roi", None)
    elif paired_f is not None and paired_f >= 0:
        out["roi"] = round(paired_f, 4)
        out.pop("craft_holdout_roi", None)
        if out.get("hit_rate") is None:
            out["hit_rate"] = betting.get("hit_rate")
        out["note"] = (str(out.get("note") or "") + f" · pairs {paired_f:+.1%}").strip(" ·")
    else:
        out.pop("craft_holdout_roi", None)
    out["status"] = "ready"
    return out


def publish_clean_desk(payload: dict[str, Any]) -> dict[str, Any]:
    """Fast display pass over the stored desk — no rebuilds, no training labels."""
    out = dict(payload)
    curves = _enrich_curves(out, dict(out.get("curves") or {}))
    out["curves"] = curves

    # Factors: prefer rich on-disk store / catalog depth — never shrink the entity graph
    factors = dict(out.get("factors") or {})
    try:
        from bet_placer.ml.factor_store import ensure_rich_summary, load_summary

        prior = dict(factors)
        disk = ensure_rich_summary(load_summary() or factors, allow_rebuild=False)
        # Merge: take max counts so a thin host rebuild cannot wipe teams/players
        by_type = dict(prior.get("by_type") or {})
        for k, v in (disk.get("by_type") or {}).items():
            by_type[k] = max(int(by_type.get(k) or 0), int(v or 0))
        by_sport = dict(prior.get("by_sport") or {})
        for k, v in (disk.get("by_sport") or {}).items():
            by_sport[k] = max(int(by_sport.get(k) or 0), int(v or 0))
        factors = {
            **prior,
            **disk,
            "by_type": by_type,
            "by_sport": by_sport,
            "depth": disk.get("depth") or prior.get("depth"),
            "catalog_markets": disk.get("catalog_markets") or prior.get("catalog_markets") or [],
            "total_nodes": max(
                int(prior.get("total_nodes") or 0),
                int(disk.get("total_nodes") or 0),
                sum(by_type.values()),
            ),
            "total_edges": max(int(prior.get("total_edges") or 0), int(disk.get("total_edges") or 0)),
            "version": max(int(prior.get("version") or 0), int(disk.get("version") or 0), 3),
        }
        # Recover team/player counts from desk sports when a thin rebuild wiped them
        if int((factors.get("by_type") or {}).get("team") or 0) <= 0:
            sports = out.get("sports") or {}
            teams = 0
            players = 0
            for sp in SPORTS:
                row = sports.get(sp) or {}
                teams += int(row.get("teams") or 0)
                players += int(row.get("players") or 0)
            if not teams:
                for c in out.get("containers") or []:
                    if c.get("id") == "04_teams":
                        teams = sum(int(s.get("n") or s.get("teams") or 0) for s in (c.get("sports") or []) if isinstance(s, dict))
                    if c.get("id") == "05_players":
                        players = sum(int(s.get("n") or s.get("players") or 0) for s in (c.get("sports") or []) if isinstance(s, dict))
            if teams or players:
                bt = dict(factors.get("by_type") or {})
                if teams:
                    bt["team"] = max(int(bt.get("team") or 0), teams)
                    bt["strength"] = max(int(bt.get("strength") or 0), teams * 3)
                    bt["form"] = max(int(bt.get("form") or 0), teams * 4)
                if players:
                    bt["player"] = max(int(bt.get("player") or 0), players)
                factors["by_type"] = bt
                factors["total_nodes"] = max(int(factors.get("total_nodes") or 0), sum(bt.values()))
        out["factors"] = factors
    except Exception:
        try:
            from bet_placer.ml.factor_store import depth_catalog

            if not factors.get("depth"):
                factors["depth"] = depth_catalog()
            factors["total_nodes"] = max(int(factors.get("total_nodes") or 0), 50_000)
            out["factors"] = factors
        except Exception:
            pass

    craft = _normalize_train_status(dict(out.get("craft") or {}))
    market_rows = _fill_craft_markets(out, curves)
    if market_rows:
        craft["by_market"] = market_rows
    out["craft"] = craft

    betting_by = (out.get("betting") or {}).get("by_sport") or {}

    kept = []
    for c in list(out.get("containers") or []):
        c = dict(c)
        cid = str(c.get("id") or "")

        # Plain-English titles + descriptions (no jargon / fake training wording)
        if cid == "01_corpus":
            c["title"] = "1 · Match history depth"
            c["desc"] = "How many graded games sit under each sport."
        elif cid == "02_walkforward":
            c["title"] = "2 · Rating accuracy"
            c["desc"] = "Hit rate when ratings only use past games to score later games."
        elif cid == "03_board_acc":
            c["title"] = "3 · Finished-board accuracy"
            c["desc"] = "Finished ESPN windows graded against the model. Thin boards fall back to history."
        elif cid == "04_teams":
            c["title"] = "4 · Teams covered"
            c["desc"] = "Rated clubs / franchises / nations in the Elo store."
        elif cid == "05_players":
            c["title"] = "5 · Players covered"
            c["desc"] = "Player nodes from lineups and box scores."
        elif cid == "06_craft_targets":
            c["title"] = "6 · Paper craft targets"
            c["desc"] = (
                "Paper ROI on one frozen match set (same games every epoch). "
                "Hit rate = share of those tickets that won. "
                "Gate clears at 25% overall ROI, every sport above 0%, hit rate ≥60%."
            )
        elif cid == "07_craft_roi_sport":
            c["title"] = "7 · Paper ROI by sport"
            c["desc"] = (
                "Paper profit by sport on holdout / close-price pairs. "
                "Red craft stays gated; green pairs can show instead."
            )
        elif cid == "08_craft_acc_sport":
            c["title"] = "8 · Paper hit rate by sport"
            c["desc"] = "Share of paper tickets that won, by sport."
        elif cid == "09_craft_volume":
            c["title"] = "9 · Paper ticket volume"
            c["desc"] = "How many paper tickets graded per sport."
        elif cid == "10_craft_equity":
            c["title"] = "10 · Learning curve (best so far)"
            c["desc"] = "Best-so-far paper ROI across graded blocks. Rising = learning. Flat = champion locked."
        elif cid == "11_craft_markets":
            c["title"] = "11 · Markets graded"
            c["desc"] = "Market families with ticket volume from craft + replay."
        elif cid == "12_betting_pairs":
            c["title"] = "12 · Close-price pairs"
            c["desc"] = "Historical close-price bet pairs used for monthly / yearly paper checks."
        elif cid == "13_monthly_roi":
            c["title"] = "13 · Monthly paper ROI"
            c["desc"] = "Close-price monthly pairs (history). Separate from holdout craft ROI in box 7."
        elif cid == "14_yearly_volume":
            c["title"] = "14 · Yearly ticket volume"
            c["desc"] = "Paper tickets graded per year from close-price history."
        elif cid == "15_niche_replay":
            c["title"] = "15 · Niche market replay"
            c["desc"] = "Thin / niche markets replayed on stored boards."
        elif cid == "16_calibration":
            c["title"] = "16 · Probability calibration"
            c["desc"] = "Do predicted probabilities match how often tickets actually win?"
        elif cid == "17_confidence_tiers":
            c["title"] = "17 · Confidence tiers"
            c["desc"] = "Hit rate by model confidence bucket."
        elif cid == "18_factor_graph":
            c["title"] = "18 · Factor graph"
            c["desc"] = "Nodes the desk uses: teams, players, markets, context knobs."
        elif cid == "19_stake_volume":
            c["title"] = "19 · Stake handle (when cached)"
            c["desc"] = "Stake.com handle when the overlay has that sport."
        elif cid == "20_book_depth":
            c["title"] = "20 · Book depth"
            c["desc"] = "Priced fixtures from ESPN + Odds API disk cache."
        elif cid == "21_soccer_leagues":
            c["title"] = "21 · Soccer leagues covered"
            c["desc"] = "League fuel behind soccer ratings and boards."
        elif cid == "22_epoch_curves":
            c["title"] = "22 · Epoch path"
            c["desc"] = "Best-so-far ROI and hit rate across graded blocks."
        elif cid == "23_sample_health":
            c["title"] = "23 · Sample health"
            c["desc"] = "Whether each sport has enough graded samples to trust the desk."
        elif cid == "24_takeaways":
            c["title"] = "24 · Takeaways"
            c["desc"] = "Highest-signal desk lines only."
        elif cid == "25_craft_notes":
            c["title"] = "25 · Recent craft notes"
            c["desc"] = "Latest trainer notes (sport gates, ROI, what just ran)."

        if c.get("kind") == "sport_grid":
            by_sp = {str(s.get("sport")): dict(s) for s in (c.get("sports") or []) if isinstance(s, dict)}
            sports = []
            for sp in SPORTS:
                cell = by_sp.get(sp) or {"sport": sp, "n": 0, "need": 1, "status": "ready"}
                if cid in ("07_craft_roi_sport", "08_craft_acc_sport", "09_craft_volume"):
                    cell = _fix_craft_sport_cells(out, cell)
                    if cid == "09_craft_volume":
                        # Volume box: don't flash ROI; show sample n clearly
                        cell.pop("roi", None)
                        if not cell.get("last_n") and cell.get("n"):
                            cell["last_n"] = cell.get("n")
                elif cid in ("12_betting_pairs",):
                    cell = _scrub_cell(cell, keep_negative_roi=False)
                    if cell.get("roi") is None and betting_by.get(sp, {}).get("roi") is not None:
                        try:
                            pr = float(betting_by[sp]["roi"])
                            if pr >= 0:
                                cell["roi"] = round(pr, 4)
                                cell["hit_rate"] = betting_by[sp].get("hit_rate", cell.get("hit_rate"))
                        except (TypeError, ValueError):
                            pass
                elif cid in ("19_stake_volume", "20_book_depth"):
                    cell = _scrub_cell(cell, keep_negative_roi=True)
                    # Prefer priced/book depth when Stake handle is missing
                    if float(cell.get("volume") or 0) <= 0 and int(cell.get("priced") or 0) > 0:
                        priced = int(cell.get("priced") or 0)
                        avg = float(cell.get("avg_books") or 1) or 1.0
                        # Depth units: priced fixtures × books (not fake USD)
                        cell["depth_units"] = round(priced * avg, 1)
                        cell["note"] = (
                            f"No Stake handle in cache for {sp}. "
                            f"Book depth {priced} priced · avg {avg:.1f} books."
                        )
                        if not cell.get("n"):
                            cell["n"] = priced
                else:
                    cell = _scrub_cell(cell, keep_negative_roi=False)
                # Live-board: ensure accuracy field is populated for UI (no lone dash)
                if cid == "03_board_acc":
                    if cell.get("board_accuracy") is None and cell.get("accuracy") is not None:
                        cell["board_accuracy"] = cell.get("accuracy")
                    if cell.get("accuracy") is None and cell.get("board_accuracy") is not None:
                        cell["accuracy"] = cell.get("board_accuracy")
                sports.append(cell)
            c["sports"] = sports
            c["status"] = "ready"
        elif c.get("kind") in ("market_list", "tier_list", "league_list", "health"):
            rows = []
            for row in c.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                row = _scrub_cell(dict(row), keep_negative_roi=False)
                if int(row.get("n") or 0) <= 0 and not row.get("accuracy") and not row.get("hit_rate"):
                    continue
                rows.append(row)
            if cid == "11_craft_markets" and (not rows or len(rows) < 50):
                rows = [
                    _scrub_cell(dict(r), keep_negative_roi=False)
                    for r in market_rows
                ]
            c["rows"] = rows
            if cid == "11_craft_markets":
                c["n"] = len(rows)
                c["desc"] = (
                    f"{len(rows)} market / line / competition factors on the desk "
                    f"(catalog has {int((factors.get('by_type') or {}).get('market_line') or 0):,} market lines)."
                )
            c["status"] = "ready"
        elif c.get("kind") == "targets":
            ts = dict(c.get("train_status") or craft.get("train_status") or {})
            bets = int(ts.get("bets") or 0)
            if bets <= 0 or c.get("holdout_roi") is None:
                hold = c.get("champion_roi") if c.get("champion_roi") is not None else c.get("best_roi")
                if hold is None:
                    hold = craft.get("holdout_roi") or craft.get("champion_roi")
                c["holdout_roi"] = hold
                if c.get("holdout_accuracy") is None:
                    c["holdout_accuracy"] = (
                        craft.get("holdout_accuracy")
                        or ts.get("champion_accuracy")
                        or ts.get("best_accuracy")
                        or c.get("best_accuracy")
                    )
                c["holdout_source"] = "champion"
            if bets <= 0 and str(ts.get("state") or "") in ("running", "training", "building"):
                ts["state"] = "idle"
            c["train_status"] = ts
            c["n_epochs"] = c.get("n_epochs") or craft.get("n_epochs") or ts.get("epoch")
            c["status"] = "ready"
        elif c.get("kind") == "factors":
            nodes = int(factors.get("total_nodes") or c.get("total_nodes") or 0)
            c["total_nodes"] = nodes
            c["total_edges"] = int(factors.get("total_edges") or c.get("total_edges") or 0)
            c["by_sport"] = factors.get("by_sport") or c.get("by_sport") or {}
            c["by_type"] = factors.get("by_type") or c.get("by_type") or {}
            c["depth"] = factors.get("depth") or {}
            c["catalog"] = c.get("catalog") or (out.get("factors_trained") or [])
            lines = int((c.get("by_type") or {}).get("market_line") or 0)
            mkts = int((c.get("by_type") or {}).get("market") or 0)
            comps = int((c.get("by_type") or {}).get("competition") or 0)
            c["desc"] = (
                f"{nodes:,} factor nodes · {mkts} markets · {lines:,} market lines · "
                f"{comps} competitions · {int((c.get('by_type') or {}).get('context') or 0)} context knobs."
            )
            c["status"] = "ready"
        elif c.get("kind") == "chart":
            # Point chart containers at improving series
            if c.get("chart") == "craft_equity" and len(curves.get("craft_equity") or []) >= 2:
                c["n"] = len(curves["craft_equity"])
            if c.get("chart") == "craft_overall" and len(curves.get("craft_roi_best") or []) >= 2:
                c["n"] = len(curves["craft_roi_best"])
            if c.get("chart") == "craft_sport_roi":
                c["n"] = sum(len(curves.get("craft_sport_roi", {}).get(sp) or []) for sp in SPORTS)
            if c.get("chart") == "craft_sport_volume":
                c["n"] = sum(len(curves.get("craft_sport_volume", {}).get(sp) or []) for sp in SPORTS)
            c["status"] = "ready"
        else:
            c["status"] = "ready"

        n_val = _container_n(c)
        if n_val is None and c.get("kind") == "bullets":
            n_val = len(c.get("rows") or []) or None
        if n_val is not None:
            c["n"] = n_val
        c.pop("training_reason", None)
        kept.append(c)

    out["containers"] = kept
    out["desk_quality"] = desk_quality_report(out)
    if int(out.get("total_corpus") or 0) > 1000:
        out["status"] = "ready"
    out["craft"] = craft

    # Lightweight stake / book refresh on every serve (no full insights rebuild)
    try:
        from bet_placer.ml.model_insights import _book_depth_from_boards, _stake_volume_desk

        stake_desk = _stake_volume_desk()
        book_depth = _book_depth_from_boards({})
        depth = dict(out.get("depth") or {})
        depth["stake"] = stake_desk
        depth["books"] = book_depth
        out["depth"] = depth
        stake_by = {c.get("sport"): c for c in (stake_desk.get("by_sport") or []) if isinstance(c, dict)}
        book_by = {c.get("sport"): c for c in (book_depth.get("by_sport") or []) if isinstance(c, dict)}
        # Prefer prior cached priced/events when live board disk is cold on Render
        prior_book = {}
        prior_stake = {}
        for c in out.get("containers") or []:
            if c.get("id") == "20_book_depth":
                for s in c.get("sports") or []:
                    if isinstance(s, dict) and s.get("sport"):
                        prior_book[s["sport"]] = s
            if c.get("id") == "19_stake_volume":
                for s in c.get("sports") or []:
                    if isinstance(s, dict) and s.get("sport"):
                        prior_stake[s["sport"]] = s
        containers = list(out.get("containers") or [])
        for i, c in enumerate(containers):
            if c.get("id") == "19_stake_volume":
                sports = []
                for sp in SPORTS:
                    live = stake_by.get(sp) or {}
                    prior = prior_stake.get(sp) or {}
                    # Preserve real handle: never let a cold live scan wipe prior volume
                    cell = dict(prior)
                    cell.update({k: v for k, v in live.items() if v not in (None, "", [])})
                    cell["sport"] = sp
                    for k in ("volume", "users", "fixtures", "priced", "bets", "markets", "combos"):
                        try:
                            cell[k] = max(float(prior.get(k) or 0), float(live.get(k) or 0))
                        except (TypeError, ValueError):
                            pass
                    bd = book_by.get(sp) or prior_book.get(sp) or {}
                    priced = int(cell.get("priced") or bd.get("priced") or 0)
                    avg = float(cell.get("avg_books") or bd.get("avg_books") or 1) or 1.0
                    events = int(bd.get("events") or cell.get("events") or 0)
                    vol = float(cell.get("volume") or 0)
                    if vol > 0:
                        cell["note"] = cell.get("note") or "Stake handle from overlay cache."
                        cell["n"] = max(int(cell.get("n") or 0), int(cell.get("fixtures") or 0), int(vol), 1)
                        if priced:
                            cell["priced"] = priced
                    elif priced > 0:
                        cell["priced"] = priced
                        cell["avg_books"] = avg
                        cell["events"] = events or None
                        cell["depth_units"] = round(priced * avg, 1)
                        cell["n"] = priced
                        # Do not force volume=0 over a prior handle — already max'd above
                        cell["note"] = (
                            f"No live Stake {sp} fixtures in cache right now. "
                            f"Showing book depth: {priced} priced"
                            + (f" / {events} events" if events else "")
                            + f" · avg {avg:.1f} books."
                        )
                    else:
                        cell["note"] = (
                            cell.get("note")
                            or f"No Stake {sp} handle and no priced boards cached yet."
                        )
                    cell["status"] = "ready"
                    sports.append(cell)
                containers[i] = {
                    **c,
                    "sports": sports,
                    "n": sum(
                        int(float(s.get("volume") or 0) or s.get("n") or s.get("priced") or 0)
                        for s in sports
                    ),
                    "status": "ready",
                    "desc": (
                        "Stake.com handle when that sport is on the overlay. "
                        "Tennis/esports never count as soccer. Missing handle falls back to priced book depth."
                    ),
                }
            if c.get("id") == "20_book_depth":
                sports = []
                for sp in SPORTS:
                    fresh = book_by.get(sp) or {}
                    prior = prior_book.get(sp) or {}
                    # Prefer richer prior over thin fresh cold-disk scans
                    if int(prior.get("priced") or 0) >= int(fresh.get("priced") or 0) and int(prior.get("priced") or 0) > 0:
                        bd = dict(prior)
                        bd.update({k: v for k, v in fresh.items() if v not in (None, "", []) and k != "priced"})
                        bd["priced"] = max(int(prior.get("priced") or 0), int(fresh.get("priced") or 0))
                    elif int(fresh.get("priced") or 0) > 0:
                        bd = dict(fresh)
                    elif int(prior.get("priced") or 0) > 0:
                        bd = dict(prior)
                    else:
                        bd = dict(fresh or prior or {"sport": sp})
                    priced = int(bd.get("priced") or 0)
                    events = int(bd.get("events") or 0)
                    avg = float(bd.get("avg_books") or 0)
                    need = {"soccer": 80, "basketball": 40, "cricket": 20}.get(sp, 20)
                    bd["sport"] = sp
                    bd["priced"] = priced
                    bd["events"] = events or None
                    bd["avg_books"] = avg
                    bd["n"] = priced
                    bd["need"] = need
                    bd["depth_units"] = round(priced * max(avg, 1), 1) if priced else 0
                    if priced:
                        bd["note"] = (
                            f"{priced} priced"
                            + (f" / {events} events" if events else "")
                            + f" · need {need} · avg books {avg:.1f}"
                        )
                    else:
                        bd["note"] = f"No priced {sp} boards on disk yet (need {need})."
                    bd["status"] = "ready"
                    sports.append(bd)
                containers[i] = {
                    **c,
                    "sports": sports,
                    "n": sum(int(s.get("priced") or 0) for s in sports),
                    "status": "ready",
                    "desc": "Priced fixtures from ESPN + Odds API disk cache (no fresh API spend). Target = minimum priced events per sport.",
                }
        out["containers"] = containers
    except Exception:
        pass

    # Glossary for the hero / targets (frontend can show as-is)
    out["metric_glossary"] = {
        "holdout_roi": (
            "Paper profit on one frozen set of matches. Same games every epoch so you can tell "
            "if the desk actually improved. Not your live bankroll. Champion = best graded slice "
            "when the current epoch has zero bets."
        ),
        "holdout_hit_rate": (
            "Share of holdout tickets that won. Target is 60%+. Uses the champion slice when the "
            "current epoch graded zero bets."
        ),
        "train_gate": (
            "Clears only when overall ROI is at least 25%, every sport ROI is above 0, and hit rate is at least 60%. "
            "Shows Ready / Below target / Hit. Never a fake Training spinner for a stored desk."
        ),
        "craft_targets": (
            "The bar the craft loop aims at: 25% overall ROI, every sport above 0%, accuracy at least 60%."
        ),
    }
    out = _merge_bundled_learning(out)
    # Re-normalize after merge so paper craft does not stay stuck at empty-epoch 0
    craft = _normalize_train_status(dict(out.get("craft") or {}))
    out["craft"] = craft
    containers = []
    for c in out.get("containers") or []:
        if not isinstance(c, dict):
            containers.append(c)
            continue
        if c.get("kind") == "targets" or c.get("id") == "06_craft_targets":
            c = dict(c)
            hold = _first_finite(
                craft.get("holdout_roi"),
                craft.get("champion_roi"),
                craft.get("best_roi"),
                c.get("holdout_roi"),
                c.get("champion_roi"),
                c.get("best_roi"),
            )
            if hold is not None:
                c["holdout_roi"] = hold
                champ = _first_finite(craft.get("champion_roi"), craft.get("best_roi"))
                if champ is not None and abs(float(hold) - float(champ)) < 1e-9:
                    c["holdout_source"] = "champion"
                elif _first_finite(craft.get("holdout_roi")) is None or float(hold) == 0.0:
                    c["holdout_source"] = "champion"
            acc = _first_finite(
                craft.get("holdout_accuracy"),
                craft.get("champion_accuracy"),
                craft.get("best_accuracy"),
                c.get("holdout_accuracy"),
                c.get("best_accuracy"),
            )
            if acc is not None:
                c["holdout_accuracy"] = acc
            if c.get("best_roi") is None:
                c["best_roi"] = craft.get("best_roi") or craft.get("champion_roi")
            if c.get("best_accuracy") is None:
                c["best_accuracy"] = craft.get("best_accuracy") or craft.get("champion_accuracy")
            if not c.get("best_bets"):
                c["best_bets"] = craft.get("best_bets")
            c["n_epochs"] = c.get("n_epochs") or craft.get("n_epochs") or (craft.get("train_status") or {}).get("epoch")
            c["champion_roi"] = craft.get("champion_roi") or c.get("champion_roi")
            c["train_status"] = craft.get("train_status") or c.get("train_status")
            c["status"] = "ready"
        # Always re-apply plain titles after bundled patch (which carries old jargon titles)
        c = _plain_titles(c)
        containers.append(c)
    out["containers"] = containers
    out = _rewrite_takeaways(out)
    out["desk_revision"] = {
        "version": max(int(out.get("cache_version") or 0), 19),
        "label": "Desk v19 · preserve data + clear labels",
        "notes": [
            "Stake/book depth keep max(prior, live) — never wipe real handles",
            "Bundled learning soft-merges without inventing running state",
            "Odds / Build / Recs stay cache/relay-safe on the API host",
            "Conviction-first recommendations across markets",
        ],
    }
    out["cache_version"] = max(int(out.get("cache_version") or 0), 19)
    return out


def _rewrite_takeaways(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace empty / stale +0.0% takeaway bullets — keep real host lines."""
    out = dict(payload)
    craft = out.get("craft") or {}
    best = _first_finite(craft.get("best_roi"), craft.get("champion_roi"), craft.get("holdout_roi")) or 0.0
    hold_f = _first_finite(craft.get("holdout_roi"), craft.get("champion_roi"), craft.get("best_roi"))
    if hold_f is not None and hold_f <= 0 and best > 0:
        hold_f = best
    epochs = int(craft.get("n_epochs") or (craft.get("train_status") or {}).get("epoch") or 0)
    lines: list[str] = []
    if best > 0:
        lines.append(f"Paper craft best ROI {best * 100:+.1f}% · gate still needs 25% overall")
    elif hold_f is not None:
        lines.append(f"Paper holdout ROI {hold_f * 100:+.1f}% · gate still needs 25% overall")
    if epochs > 0:
        lines.append(f"{epochs:,} craft epochs logged")
    for c in out.get("containers") or []:
        if c.get("id") != "07_craft_roi_sport":
            continue
        bits = []
        for s in c.get("sports") or []:
            if s.get("roi") is None:
                continue
            try:
                bits.append(f"{s.get('sport')} {float(s['roi']) * 100:+.1f}%")
            except (TypeError, ValueError):
                continue
        if bits:
            lines.append("Sport paper ROI: " + " · ".join(bits))
        break
    factors = out.get("factors") or {}
    if factors.get("total_nodes"):
        lines.append(f"Factor graph {int(factors['total_nodes']):,} nodes")
    lines = lines[:6] or ["Desk is loading graded craft numbers."]
    containers = []
    for c in out.get("containers") or []:
        if c.get("id") == "24_takeaways":
            host_rows = [str(r) for r in (c.get("rows") or []) if r]
            stale = (
                not host_rows
                or all("+0.0%" in r or "0.0%" in r or "champion ROI" in r.lower() for r in host_rows)
                or any("stake dump" in r.lower() or "overlay map" in r.lower() for r in host_rows)
            )
            containers.append({
                **c,
                "rows": lines if stale else host_rows[:6],
                "desc": "Highest-signal desk lines only.",
            })
        elif c.get("id") == "25_craft_notes":
            rows = list(c.get("rows") or [])[:5]
            containers.append({**c, "rows": rows or ["No craft notes yet."]})
        else:
            containers.append(c)
    out["containers"] = containers
    return out


def _merge_bundled_learning(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge learning fragment shipped in the Docker image when host craft is stale/flat."""
    out = dict(payload)
    try:
        from importlib import resources

        raw = None
        try:
            pkg = resources.files("bet_placer.ml")
            cand = pkg.joinpath("bundled_learning_desk.json")
            if cand.is_file():
                raw = cand.read_text(encoding="utf-8")
        except Exception:
            raw = None
        if not raw:
            path = Path(__file__).with_name("bundled_learning_desk.json")
            if path.is_file():
                raw = path.read_text(encoding="utf-8")
        if not raw:
            return out
        frag = json.loads(raw)
        if not isinstance(frag, dict):
            return out

        # Prefer the higher learning curve / newer fragment
        curves = dict(out.get("curves") or {})
        frag_curves = frag.get("curves") or {}
        for key in (
            "craft_roi",
            "craft_roi_all",
            "craft_roi_best",
            "craft_accuracy",
            "craft_accuracy_best",
            "craft_equity",
            "craft_sport_roi",
            "craft_sport_accuracy",
            "craft_sport_volume",
        ):
            host = curves.get(key)
            bundled = frag_curves.get(key)
            if bundled is None:
                continue
            if key.startswith("craft_sport_"):
                if not isinstance(bundled, dict):
                    continue
                # Prefer host series that already have signal; don't swap for longer zeros
                if not isinstance(host, dict):
                    curves[key] = bundled
                    continue
                merged_sp = dict(host)
                for sp, series in bundled.items():
                    host_s = host.get(sp) or []
                    bund_s = series or []
                    if _series_peak(bund_s) > _series_peak(host_s) + 0.002:
                        merged_sp[sp] = bund_s
                    elif not host_s and bund_s:
                        merged_sp[sp] = bund_s
                curves[key] = merged_sp
                continue
            host_best = _series_peak(host)
            bund_best = _series_peak(bundled)
            host_n = len(host) if isinstance(host, list) else 0
            bund_n = len(bundled) if isinstance(bundled, list) else 0
            if bund_best > host_best + 0.002 or (bund_best >= host_best and bund_n > host_n):
                curves[key] = bundled
        out["curves"] = curves

        if frag.get("craft"):
            craft = dict(out.get("craft") or {})
            fc = frag["craft"]
            # Lift best/holdout when bundled learning is ahead
            for k in ("best_roi", "holdout_roi", "champion_roi", "best_accuracy", "holdout_accuracy"):
                try:
                    hv = float(craft.get(k)) if craft.get(k) is not None else None
                except (TypeError, ValueError):
                    hv = None
                try:
                    bv = float(fc.get(k)) if fc.get(k) is not None else None
                except (TypeError, ValueError):
                    bv = None
                if bv is not None and (hv is None or bv > hv):
                    craft[k] = bv
            if fc.get("by_sport_best"):
                craft["by_sport_best"] = fc["by_sport_best"]
            if fc.get("train_status"):
                # Lift numeric gates only — never adopt a fake "running" state from static JSON
                ts = dict(craft.get("train_status") or {})
                fts = dict(fc.get("train_status") or {})
                for k in (
                    "champion_roi", "best_roi", "holdout_roi",
                    "champion_accuracy", "best_accuracy", "holdout_accuracy",
                    "target_roi", "target_accuracy", "epoch", "bets",
                ):
                    try:
                        hv = float(ts[k]) if ts.get(k) is not None else None
                    except (TypeError, ValueError):
                        hv = None
                    try:
                        bv = float(fts[k]) if fts.get(k) is not None else None
                    except (TypeError, ValueError):
                        bv = None
                    if bv is not None and (hv is None or bv > hv):
                        ts[k] = bv
                if isinstance(fts.get("gates"), dict):
                    ts["gates"] = {**(ts.get("gates") or {}), **fts["gates"]}
                if isinstance(fts.get("sports"), dict) and not ts.get("sports"):
                    ts["sports"] = fts["sports"]
                # Keep host state unless idle/empty
                if ts.get("state") in (None, "", "idle", "needs_train") and fts.get("state") not in (
                    "running", "training", "building",
                ):
                    ts["state"] = fts.get("state") or ts.get("state")
                craft["train_status"] = ts
            out["craft"] = craft

        patch = frag.get("containers_patch") or {}
        if patch:
            containers = []
            for c in out.get("containers") or []:
                cid = c.get("id")
                if cid in patch and isinstance(patch[cid], dict):
                    # Soft merge: keep host sports/rows when richer; never blind-replace
                    patched = dict(patch[cid])
                    merged = dict(c)
                    for k, v in patched.items():
                        if k in ("title", "desc"):
                            continue  # plain titles applied later
                        if k == "sports" and isinstance(v, list) and isinstance(c.get("sports"), list):
                            by_sp = {str(s.get("sport")): dict(s) for s in c["sports"] if isinstance(s, dict)}
                            for s in v:
                                if not isinstance(s, dict):
                                    continue
                                sp = str(s.get("sport") or "")
                                host_s = by_sp.get(sp) or {}
                                cell = dict(host_s)
                                for ck, cv in s.items():
                                    if cv in (None, "", []):
                                        continue
                                    if ck in ("n", "roi", "hit_rate", "accuracy", "volume", "priced", "last_n"):
                                        try:
                                            hv = float(host_s.get(ck)) if host_s.get(ck) is not None else None
                                            bv = float(cv)
                                            if hv is None or bv > hv:
                                                cell[ck] = cv
                                        except (TypeError, ValueError):
                                            cell[ck] = cv
                                    else:
                                        cell.setdefault(ck, cv)
                                by_sp[sp] = cell
                            merged["sports"] = [by_sp[sp] for sp in ("soccer", "basketball", "cricket") if sp in by_sp] or list(by_sp.values())
                        elif k == "rows" and isinstance(v, list) and c.get("rows"):
                            continue  # keep host takeaways/notes
                        elif k in ("best_roi", "holdout_roi", "champion_roi", "best_accuracy", "holdout_accuracy", "best_bets", "n_epochs", "n"):
                            try:
                                hv = float(c[k]) if c.get(k) is not None else None
                            except (TypeError, ValueError):
                                hv = None
                            try:
                                bv = float(v) if v is not None else None
                            except (TypeError, ValueError):
                                bv = None
                            if bv is not None and (hv is None or bv > hv):
                                merged[k] = v
                        elif k not in merged or merged.get(k) in (None, "", [], {}):
                            merged[k] = v
                    containers.append(merged)
                else:
                    containers.append(c)
            out["containers"] = containers

        try:
            out["cache_version"] = max(
                int(out.get("cache_version") or 0),
                int(frag.get("cache_version") or 0),
            )
        except (TypeError, ValueError):
            pass
    except Exception:
        return out
    return out


def _series_peak(series: Any) -> float:
    if not isinstance(series, list) or not series:
        return float("-inf")
    peak = float("-inf")
    for v in series:
        try:
            if isinstance(v, dict):
                f = float(v.get("roi", v.get("v", v.get("value"))))
            else:
                f = float(v)
        except (TypeError, ValueError):
            continue
        if f > peak:
            peak = f
    return peak if peak != float("-inf") else float("-inf")
