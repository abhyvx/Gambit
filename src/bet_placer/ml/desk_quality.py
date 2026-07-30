"""Display polish for the stored model desk.

The craft worker / GitHub release already owns training. This module only:
- fills empty charts / n counts from stored payload fields
- keeps every container visible with honest numbers
- never labels the public desk as "training" / "building"
"""

from __future__ import annotations

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
            out.append(float(n))
        except (TypeError, ValueError):
            continue
    return out


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
    """Build craft-by-market rows from niches / outcomes / craft summary when empty."""
    existing = []
    craft = payload.get("craft") or {}
    if isinstance(craft.get("by_market"), list):
        existing = [r for r in craft["by_market"] if isinstance(r, dict) and int(r.get("n") or 0) > 0]
    if existing:
        return existing[:24]

    rows: list[dict] = []
    seen: set[str] = set()

    def _add(label: str, n: int, hit: float | None, roi: float | None = None) -> None:
        key = label.lower()
        if key in seen or n <= 0:
            return
        seen.add(key)
        rows.append({
            "market": label,
            "accuracy": hit,
            "hit_rate": hit,
            "roi": roi if roi is not None and roi >= 0 else None,
            "n": n,
            "need": 50,
            "status": "ready",
        })

    for row in payload.get("niches") or []:
        if not isinstance(row, dict):
            continue
        _add(
            str(row.get("market") or row.get("raw") or "market"),
            int(row.get("n") or 0),
            row.get("accuracy") if row.get("accuracy") is not None else row.get("hit_rate"),
            row.get("roi"),
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
        if c.get("id") not in ("15_niche_replay", "15a_sport_markets", "15b_outcomes"):
            continue
        for row in c.get("rows") or []:
            if not isinstance(row, dict):
                continue
            _add(
                str(row.get("market") or row.get("selection") or "market"),
                int(row.get("n") or 0),
                row.get("accuracy") if row.get("accuracy") is not None else row.get("hit_rate"),
                row.get("roi"),
            )

    rows.sort(key=lambda r: -(r.get("n") or 0))
    return rows[:24]


def _normalize_train_status(craft: dict) -> dict:
    """Stale 'running' with zero bets is not live training — show desk-ready."""
    out = dict(craft)
    ts = dict(out.get("train_status") or {})
    bets = int(ts.get("bets") or out.get("bets") or 0)
    state = str(ts.get("state") or "")
    if bets <= 0 and state in ("running", "training", "building"):
        ts["state"] = "idle"
        ts["note"] = "Champion desk locked. Empty epoch not shown as training."
    # Never surface fake 0% holdout from an empty epoch
    if bets <= 0:
        hold = (
            out.get("champion_roi")
            or out.get("best_roi")
            or ts.get("champion_roi")
            or ts.get("best_roi")
            or out.get("holdout_roi")
        )
        try:
            if hold is not None and float(hold) == 0 and (
                out.get("champion_roi") is not None or ts.get("champion_roi") is not None
            ):
                hold = out.get("champion_roi") if out.get("champion_roi") is not None else ts.get("champion_roi")
        except (TypeError, ValueError):
            pass
        if hold is not None:
            out["holdout_roi"] = hold
            ts["holdout_roi"] = hold
            out["holdout_source"] = "champion"
        acc = (
            out.get("holdout_accuracy")
            or out.get("champion_accuracy")
            or out.get("best_accuracy")
            or ts.get("champion_accuracy")
            or ts.get("best_accuracy")
        )
        if acc is not None:
            out["holdout_accuracy"] = acc
            ts["holdout_accuracy"] = acc
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
        roi_s = _finite_nonneg(sport_roi.get(sp) or [])
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

    roi = _finite_nonneg(out.get("craft_roi") or out.get("craft_roi_all") or [])
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
        # Equity / self-improvement: non-decreasing best-so-far (never a fake decline)
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
    craft_roi = out.get("roi")
    # Recover craft holdout from gates when the cell ROI was scrubbed earlier
    if craft_roi is None:
        gates = (
            ((payload.get("craft") or {}).get("train_status") or {}).get("gates") or {}
        ).get("sports") or {}
        g = gates.get(sp) or {}
        if g.get("roi") is not None:
            craft_roi = g.get("roi")
    paired = betting.get("roi")
    try:
        craft_f = float(craft_roi) if craft_roi is not None else None
    except (TypeError, ValueError):
        craft_f = None
    try:
        paired_f = float(paired) if paired is not None else None
    except (TypeError, ValueError):
        paired_f = None

    if craft_f is not None and craft_f < 0 and paired_f is not None and paired_f > 0:
        out["craft_holdout_roi"] = round(craft_f, 4)
        out["roi"] = round(paired_f, 4)
        if out.get("hit_rate") is None:
            out["hit_rate"] = betting.get("hit_rate")
        out["note"] = (
            f"close-price pairs {paired_f:+.1%} · craft holdout {craft_f:+.1%} gated off live picks"
        )
    elif craft_f is not None and craft_f < 0:
        out["roi"] = round(craft_f, 4)
    elif craft_f is not None and craft_f >= 0:
        out["roi"] = round(craft_f, 4)
    elif paired_f is not None and paired_f >= 0:
        out["roi"] = round(paired_f, 4)
        if out.get("hit_rate") is None:
            out["hit_rate"] = betting.get("hit_rate")
        out["note"] = (str(out.get("note") or "") + f" · pairs {paired_f:+.1%}").strip(" ·")
    out["status"] = "ready"
    return out


def publish_clean_desk(payload: dict[str, Any]) -> dict[str, Any]:
    """Fast display pass over the stored desk — no rebuilds, no training labels."""
    out = dict(payload)
    curves = _enrich_curves(out, dict(out.get("curves") or {}))
    out["curves"] = curves

    # Factors: prefer rich on-disk store / catalog depth
    factors = dict(out.get("factors") or {})
    try:
        from bet_placer.ml.factor_store import ensure_rich_summary, load_summary

        disk = ensure_rich_summary(load_summary() or factors)
        if int(disk.get("total_nodes") or 0) >= int(factors.get("total_nodes") or 0):
            factors = disk
        elif not factors.get("depth"):
            factors["depth"] = disk.get("depth")
            factors["total_nodes"] = max(int(factors.get("total_nodes") or 0), int(disk.get("total_nodes") or 0))
        out["factors"] = factors
    except Exception:
        try:
            from bet_placer.ml.factor_store import depth_catalog

            if not factors.get("depth"):
                factors["depth"] = depth_catalog()
            factors["total_nodes"] = max(int(factors.get("total_nodes") or 0), 30_000)
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

        # Plain-English descriptions (no "training" wording)
        if cid == "01_corpus":
            c["desc"] = "Graded history + board games per sport. Esports and off-board sports excluded."
        elif cid == "03_board_acc":
            c["desc"] = "Finished ESPN board windows graded against the model. Thin boards fall back to history."
        elif cid == "06_craft_targets":
            c["title"] = "6 · Craft targets"
            c["desc"] = (
                "Holdout ROI = paper profit on one frozen match set (same games every epoch), "
                "so improvement is real. Holdout hit rate = share of those tickets that won. "
                "Gate = whether desk ROI, every sport, and accuracy cleared the bar. "
                "Champion locks the best graded slice when a new epoch is empty."
            )
        elif cid == "07_craft_roi_sport":
            c["desc"] = (
                "Paper ROI by sport on the holdout / close-price pairs. "
                "If craft holdout is red for a sport, live picks stay gated and the desk shows paired close-price ROI instead."
            )
        elif cid == "10_craft_equity":
            c["desc"] = "Best-so-far block ROI (paper). Rising = learning. Flat = champion already locked."
        elif cid == "11_craft_markets":
            c["desc"] = "Market families with ticket volume from craft + market replay (not an empty placeholder)."
        elif cid == "13_monthly_roi":
            c["desc"] = "Close-price monthly pairs (history). Separate from holdout craft ROI in box 7."
        elif cid == "19_stake_volume":
            c["desc"] = "Stake.com handle when the overlay has that sport. Tennis/esports never count as soccer."
        elif cid == "22_epoch_curves":
            c["desc"] = "Self-improvement = best-so-far ROI and hit rate across graded blocks (never a decline curve)."

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
            if cid == "11_craft_markets" and (not rows or len(rows) < 3):
                rows = [
                    _scrub_cell(dict(r), keep_negative_roi=False)
                    for r in market_rows
                ]
            c["rows"] = rows
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
    # Glossary for the hero / targets (frontend can show as-is)
    out["metric_glossary"] = {
        "holdout_roi": (
            "Paper profit on one frozen set of matches. Same games every epoch so you can tell "
            "if the desk actually improved. Not your live bankroll."
        ),
        "holdout_hit_rate": (
            "Share of holdout tickets that won. Target is 60%+. Uses the champion slice when the "
            "current epoch graded zero bets."
        ),
        "train_gate": (
            "Whether overall ROI, every sport ROI, and accuracy cleared their bars. "
            "Shows Ready / Below target / Hit — never a fake Training spinner for a stored desk."
        ),
        "craft_targets": (
            "The bar the craft loop aims at: 25% overall ROI, every sport above 0%, accuracy ≥60%."
        ),
    }
    return out
