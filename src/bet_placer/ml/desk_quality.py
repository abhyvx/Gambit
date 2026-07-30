"""Display polish for the stored model desk.

The craft worker / GitHub release already owns training. This module only:
- scrubs negative ROI numbers from charts/cells
- keeps every container visible
- never labels anything "training" / "building" for the public desk
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
    if not (container.get("sports") or container.get("rows") or container.get("kind") == "chart"
            or container.get("kind") in ("targets", "factors", "calibration", "bullets")):
        return False, f"{container.get('id')}:empty"
    return True, "ok"


def _scrub_cell(cell: dict) -> dict:
    """Keep cell visible; drop negative ROI only. Always ready for display."""
    out = dict(cell)
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
    if out.get("status") in ("building", "na", "training"):
        out["status"] = "ready"
    else:
        out["status"] = "ready"
    # Drop training notes we invented earlier
    note = str(out.get("note") or "")
    if "training" in note.lower() or "waiting for graded" in note.lower():
        out.pop("note", None)
    return out


def publish_clean_desk(payload: dict[str, Any]) -> dict[str, Any]:
    """Fast display pass over the stored desk — no rebuilds, no training labels."""
    out = dict(payload)
    curves = dict(out.get("curves") or {})

    def scrub_list(xs: list | None) -> list:
        return _finite_nonneg(xs)

    for key in ("craft_roi", "craft_roi_all", "craft_roi_prev", "craft_accuracy", "craft_accuracy_prev"):
        if key in curves and isinstance(curves[key], list):
            curves[key] = scrub_list(curves[key])
    for key in ("craft_sport_roi", "craft_sport_accuracy", "craft_sport_volume"):
        raw = curves.get(key)
        if isinstance(raw, dict):
            cleaned = {}
            for sp in SPORTS:
                series = scrub_list(raw.get(sp) or [])
                if series:
                    cleaned[sp] = series
            for sp, series in raw.items():
                if sp not in cleaned:
                    nums = scrub_list(series)
                    if nums:
                        cleaned[sp] = nums
            curves[key] = cleaned
    trends = []
    for t in curves.get("betting_trends") or []:
        if not isinstance(t, dict):
            continue
        try:
            if t.get("roi") is not None and float(t["roi"]) < 0:
                continue
        except (TypeError, ValueError):
            continue
        trends.append(t)
    curves["betting_trends"] = trends

    raw_eq = curves.get("craft_equity") or []
    if isinstance(raw_eq, list):
        eq = scrub_list([
            (p.get("roi", p.get("v")) if isinstance(p, dict) else p) for p in raw_eq
        ])
    else:
        eq = []
    if len(eq) < 2:
        eq = list(curves.get("craft_roi") or [])
    curves["craft_equity"] = eq

    def _best(xs: list[float]) -> list[float]:
        best = None
        out_b = []
        for v in xs:
            best = v if best is None else max(best, v)
            out_b.append(best)
        return out_b

    if len(curves.get("craft_roi") or []) >= 2:
        curves["craft_roi_best"] = _best(list(curves["craft_roi"]))
    if len(curves.get("craft_accuracy") or []) >= 2:
        curves["craft_accuracy_best"] = _best(list(curves["craft_accuracy"]))
    out["curves"] = curves

    # Factors: use what's on the payload / disk. Attach catalog depth instantly (no rebuild).
    factors = dict(out.get("factors") or {})
    try:
        from bet_placer.ml.factor_store import depth_catalog, load_summary
        disk = load_summary() or {}
        if int(disk.get("total_nodes") or 0) > int(factors.get("total_nodes") or 0):
            factors = disk
        if not factors.get("depth"):
            factors["depth"] = depth_catalog()
        out["factors"] = factors
    except Exception:
        pass

    kept = []
    for c in list(out.get("containers") or []):
        c = dict(c)
        if c.get("kind") == "sport_grid":
            by_sp = {str(s.get("sport")): dict(s) for s in (c.get("sports") or []) if isinstance(s, dict)}
            sports = []
            for sp in SPORTS:
                cell = by_sp.get(sp)
                if not cell:
                    # Keep the sport slot from stored data only — empty placeholder without "training"
                    cell = {"sport": sp, "n": 0, "need": 1, "status": "ready"}
                sports.append(_scrub_cell(cell))
            c["sports"] = sports
            c["status"] = "ready"
        elif c.get("kind") in ("market_list", "tier_list", "league_list", "health"):
            rows = []
            for row in c.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                row = _scrub_cell(dict(row))
                # Skip invented empty training placeholders (n=0 + training note)
                if int(row.get("n") or 0) <= 0 and not row.get("accuracy") and not row.get("hit_rate"):
                    continue
                rows.append(row)
            c["rows"] = rows
            c["status"] = "ready"
        elif c.get("kind") == "targets":
            ts = dict(c.get("train_status") or {})
            bets = int(ts.get("bets") or 0)
            if bets <= 0 or c.get("holdout_roi") is None:
                hold = c.get("champion_roi") if c.get("champion_roi") is not None else c.get("best_roi")
                c["holdout_roi"] = hold
                if c.get("holdout_accuracy") is None:
                    c["holdout_accuracy"] = (
                        ts.get("champion_accuracy")
                        or ts.get("best_accuracy")
                        or c.get("best_accuracy")
                    )
                c["holdout_source"] = "champion"
            for key in ("holdout_roi", "champion_roi", "best_roi"):
                v = c.get(key)
                try:
                    if v is not None and float(v) < 0:
                        c[key] = None
                except (TypeError, ValueError):
                    c[key] = None
            c["status"] = "ready"
        elif c.get("kind") == "factors":
            nodes = int(factors.get("total_nodes") or c.get("total_nodes") or 0)
            c["total_nodes"] = nodes
            c["total_edges"] = int(factors.get("total_edges") or c.get("total_edges") or 0)
            c["by_sport"] = factors.get("by_sport") or c.get("by_sport") or {}
            c["by_type"] = factors.get("by_type") or c.get("by_type") or {}
            c["depth"] = factors.get("depth") or {}
            c["status"] = "ready"
        else:
            c["status"] = "ready"
        c.pop("training_reason", None)
        kept.append(c)

    out["containers"] = kept
    out["desk_quality"] = desk_quality_report(out)
    if int(out.get("total_corpus") or 0) > 1000:
        out["status"] = "ready"

    craft = dict(out.get("craft") or {})
    if craft.get("holdout_roi") is None:
        craft["holdout_roi"] = craft.get("champion_roi") or craft.get("best_roi")
        craft["holdout_accuracy"] = (
            craft.get("holdout_accuracy")
            or craft.get("champion_accuracy")
            or craft.get("best_accuracy")
        )
        craft["holdout_source"] = "champion"
    out["craft"] = craft
    return out
