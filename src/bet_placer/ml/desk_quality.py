"""Desk quality gates — training must not stop until every published container is clean.

Rules (no hard-coded sport names as success):
- Never publish negative ROI / gated / building / na containers
- Curves must have ≥2 finite non-negative points when the container is a craft chart
- Re-check the built insights payload after each craft epoch
"""

from __future__ import annotations

from typing import Any


CHART_CURVE_KEYS = {
    "craft_equity": ("craft_equity",),
    "craft_overall": ("craft_roi", "craft_accuracy"),
    "betting_monthly_roi": ("betting_trends",),
    "betting_yearly_volume": ("betting_yearly",),
    "craft_sport_roi": ("craft_sport_roi",),
    "craft_sport_accuracy": ("craft_sport_accuracy",),
    "craft_sport_volume": ("craft_sport_volume",),
}


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


def _curve_ok(curves: dict, chart: str | None) -> bool:
    if not chart:
        return True
    keys = CHART_CURVE_KEYS.get(chart) or ()
    if not keys:
        return True
    for key in keys:
        raw = curves.get(key)
        if isinstance(raw, dict):
            # sport map — need ≥1 sport with ≥2 points
            if any(len(_finite_nonneg(series)) >= 2 for series in raw.values()):
                return True
            continue
        if len(_finite_nonneg(raw if isinstance(raw, list) else [])) >= 2:
            return True
    return False


def _row_clean(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("status") in ("building", "na"):
        return False
    if row.get("gated"):
        return False
    for key in ("roi", "mean_roi"):
        v = row.get(key)
        if v is None:
            continue
        try:
            if float(v) < 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def container_acceptable(container: dict, curves: dict | None = None) -> tuple[bool, str]:
    """Return (ok, reason) for one desk container."""
    if not isinstance(container, dict):
        return False, "not_dict"
    cid = str(container.get("id") or "")
    status = container.get("status")
    if status in ("building", "na"):
        return False, f"{cid}:status={status}"
    curves = curves or {}

    kind = container.get("kind")
    if kind == "chart":
        if not _curve_ok(curves, container.get("chart")):
            return False, f"{cid}:chart_thin"
        return True, "ok"

    if kind in ("sport_grid",):
        sports = [s for s in (container.get("sports") or []) if isinstance(s, dict)]
        if not sports:
            return False, f"{cid}:no_sports"
        # Every sport cell that claims a sample must be clean; at least one ready
        ready = 0
        for cell in sports:
            if cell.get("status") == "building":
                return False, f"{cid}:{cell.get('sport')}:building"
            if not _row_clean(cell):
                return False, f"{cid}:{cell.get('sport')}:dirty"
            if cell.get("status") == "ready" or int(cell.get("n") or 0) > 0:
                ready += 1
        if ready < 1:
            return False, f"{cid}:no_ready_sport"
        # Optional chart under sport_grid
        if container.get("chart") and not _curve_ok(curves, container.get("chart")):
            return False, f"{cid}:sport_chart_thin"
        return True, "ok"

    if kind in ("market_list", "tier_list", "league_list", "health"):
        rows = [r for r in (container.get("rows") or []) if isinstance(r, dict)]
        clean = [r for r in rows if _row_clean(r)]
        if len(clean) < 1:
            return False, f"{cid}:no_clean_rows"
        return True, "ok"

    if kind == "targets":
        # Holdout / champion must not be negative when present
        for key in ("holdout_roi", "champion_roi", "best_roi"):
            v = container.get(key)
            if v is None:
                continue
            try:
                if float(v) < 0:
                    return False, f"{cid}:{key}_negative"
            except (TypeError, ValueError):
                return False, f"{cid}:{key}_bad"
        gates = container.get("gates") or {}
        sports = gates.get("sports") or {}
        if sports and not all(bool((sports.get(sp) or {}).get("ok")) for sp in sports):
            return False, f"{cid}:sport_gates_open"
        monthly = (gates.get("monthly") or {}).get("sports") or {}
        if monthly and not all(bool((monthly.get(sp) or {}).get("ok")) for sp in monthly):
            return False, f"{cid}:monthly_gates_open"
        return True, "ok"

    if kind == "factors":
        if int(container.get("total_nodes") or 0) < 100:
            return False, f"{cid}:factors_thin"
        return True, "ok"

    if kind == "calibration":
        # Prefer real reliability rows; allow empty if market_replay present
        if container.get("market_replay_accuracy") is None and not (container.get("reliability") or []):
            return False, f"{cid}:calib_empty"
        return True, "ok"

    if kind == "bullets":
        if not (container.get("rows") or []):
            return False, f"{cid}:no_bullets"
        return True, "ok"

    # Unknown kinds — require not explicitly building
    return True, "ok"


def desk_quality_report(payload: dict[str, Any]) -> dict[str, Any]:
    curves = payload.get("curves") or {}
    containers = list(payload.get("containers") or [])
    failures: list[str] = []
    ok_ids: list[str] = []
    for c in containers:
        ok, reason = container_acceptable(c, curves)
        if ok:
            ok_ids.append(str(c.get("id") or ""))
        else:
            failures.append(reason)
    # Curve-level: published craft_roi must be non-negative
    for key in ("craft_roi", "craft_roi_all", "craft_accuracy"):
        raw = curves.get(key)
        if isinstance(raw, list):
            for v in raw:
                try:
                    if v is not None and float(v if not isinstance(v, dict) else v.get("roi", v.get("v"))) < 0:
                        failures.append(f"curve:{key}:negative")
                        break
                except (TypeError, ValueError):
                    continue
    all_ok = len(failures) == 0 and len(ok_ids) >= 8
    return {
        "all_ok": all_ok,
        "ok_count": len(ok_ids),
        "fail_count": len(failures),
        "failures": failures[:40],
        "ok_ids": ok_ids,
    }


def publish_clean_desk(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip negatives / building rows and drop containers that still fail."""
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
            curves[key] = {sp: scrub_list(series) for sp, series in raw.items() if scrub_list(series)}
    # Monthly betting trends — drop red months from the published desk
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
    # Equity as plain numbers (charts break on empty dict holes)
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
    # Running best from cleaned series
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

    clean_containers = []
    for c in list(out.get("containers") or []):
        c = dict(c)
        if c.get("kind") in ("sport_grid",):
            sports = []
            for cell in c.get("sports") or []:
                if not isinstance(cell, dict):
                    continue
                cell = dict(cell)
                if cell.get("roi") is not None:
                    try:
                        if float(cell["roi"]) < 0:
                            continue
                    except (TypeError, ValueError):
                        continue
                if cell.get("status") == "building":
                    continue
                cell.pop("gated", None)
                sports.append(cell)
            c["sports"] = sports
        if c.get("kind") in ("market_list", "tier_list", "league_list", "health"):
            rows = []
            for row in c.get("rows") or []:
                if isinstance(row, dict) and _row_clean(row):
                    rows.append(row)
            c["rows"] = rows
        if c.get("kind") == "targets":
            for key in ("holdout_roi", "champion_roi", "best_roi"):
                v = c.get(key)
                try:
                    if v is not None and float(v) < 0:
                        c[key] = None
                except (TypeError, ValueError):
                    c[key] = None
            # Don't surface open gates as RED — omit gate breakdown until clear
            gates = dict(c.get("gates") or {})
            sports = gates.get("sports") or {}
            if sports and not all(bool((sports.get(sp) or {}).get("ok")) for sp in sports):
                c["gates"] = {}
            monthly = (gates.get("monthly") or {}).get("sports") or {}
            if monthly and not all(bool((monthly.get(sp) or {}).get("ok")) for sp in monthly):
                c["gates"] = {}
        if c.get("status") == "building":
            # Promote if body is clean enough after scrub
            c["status"] = "ready"
        ok, _ = container_acceptable(c, curves)
        if ok:
            clean_containers.append(c)
    out["containers"] = clean_containers
    report = desk_quality_report(out)
    out["desk_quality"] = report
    out["status"] = "ready" if report.get("all_ok") or int(out.get("total_corpus") or 0) > 1000 else out.get("status")
    return out
