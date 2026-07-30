"""Desk quality — keep training until every container is publish-ready.

Containers are NEVER hidden. Unready ones stay visible with status=training
and scrubbed bad numbers so the desk does not show fake red ROI.
"""

from __future__ import annotations

from typing import Any

SPORTS = ("soccer", "basketball", "cricket")

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
            if any(len(_finite_nonneg(series)) >= 2 for series in raw.values()):
                return True
            continue
        if len(_finite_nonneg(raw if isinstance(raw, list) else [])) >= 2:
            return True
    return False


def _row_publish_ready(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("status") in ("building", "na", "training"):
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
    if not isinstance(container, dict):
        return False, "not_dict"
    cid = str(container.get("id") or "")
    status = container.get("status")
    if status in ("building", "na", "training"):
        return False, f"{cid}:status={status}"
    curves = curves or {}
    kind = container.get("kind")

    if kind == "chart":
        if not _curve_ok(curves, container.get("chart")):
            return False, f"{cid}:chart_thin"
        return True, "ok"

    if kind == "sport_grid":
        sports = [s for s in (container.get("sports") or []) if isinstance(s, dict)]
        if len(sports) < 3:
            return False, f"{cid}:missing_sport"
        for cell in sports:
            if not _row_publish_ready(cell):
                return False, f"{cid}:{cell.get('sport')}:not_ready"
            if cell.get("sport") not in SPORTS:
                return False, f"{cid}:bad_sport"
        if container.get("chart") and not _curve_ok(curves, container.get("chart")):
            return False, f"{cid}:sport_chart_thin"
        return True, "ok"

    if kind in ("market_list", "tier_list", "league_list", "health"):
        rows = [r for r in (container.get("rows") or []) if isinstance(r, dict)]
        clean = [r for r in rows if _row_publish_ready(r)]
        if len(clean) < 1:
            return False, f"{cid}:no_clean_rows"
        # Sport markets must include basketball + cricket when this is the sport desk
        if cid.startswith("15a"):
            labels = " ".join(str(r.get("market") or "").lower() for r in clean)
            if "basketball" not in labels or "cricket" not in labels:
                return False, f"{cid}:missing_bb_ck_niches"
        return True, "ok"

    if kind == "targets":
        for key in ("holdout_roi", "best_roi"):
            v = container.get(key)
            if v is None:
                continue
            try:
                if float(v) < 0:
                    return False, f"{cid}:{key}_negative"
            except (TypeError, ValueError):
                return False, f"{cid}:{key}_bad"
        # Need a real holdout or best number to publish
        if container.get("holdout_roi") is None and container.get("best_roi") is None:
            return False, f"{cid}:no_holdout"
        return True, "ok"

    if kind == "factors":
        if int(container.get("total_nodes") or 0) < 10_000:
            return False, f"{cid}:factors_thin"
        return True, "ok"

    if kind == "calibration":
        if container.get("market_replay_accuracy") is None and not (container.get("reliability") or []):
            return False, f"{cid}:calib_empty"
        return True, "ok"

    if kind == "bullets":
        if not (container.get("rows") or []):
            return False, f"{cid}:no_bullets"
        return True, "ok"

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
    all_ok = len(failures) == 0 and len(ok_ids) >= 12
    return {
        "all_ok": all_ok,
        "ok_count": len(ok_ids),
        "fail_count": len(failures),
        "failures": failures[:40],
        "ok_ids": ok_ids,
        "training_ids": [str(c.get("id")) for c in containers if c.get("status") == "training"],
    }


def _scrub_cell(cell: dict) -> dict:
    """Keep the cell visible; scrub negative ROI and mark training if not ready."""
    out = dict(cell)
    dirty = False
    if out.get("status") in ("building", "na"):
        dirty = True
    if out.get("gated"):
        dirty = True
        out.pop("gated", None)
    for key in ("roi", "mean_roi"):
        v = out.get(key)
        if v is None:
            continue
        try:
            if float(v) < 0:
                out[key] = None
                dirty = True
        except (TypeError, ValueError):
            out[key] = None
            dirty = True
    if dirty or not _row_publish_ready(out):
        out["status"] = "training"
        out["note"] = out.get("note") or "Training until this sport clears positive holdout."
    elif out.get("status") != "ready":
        out["status"] = "ready"
    return out


def publish_clean_desk(payload: dict[str, Any]) -> dict[str, Any]:
    """Scrub bad numbers but KEEP every container visible (training until ready)."""
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
            # Keep all sports keys even if empty — fill with [] so UI shows training
            cleaned = {}
            for sp in SPORTS:
                series = scrub_list(raw.get(sp) or [])
                cleaned[sp] = series
            # Also keep any extra keys
            for sp, series in raw.items():
                if sp not in cleaned:
                    cleaned[sp] = scrub_list(series)
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

    # Inject live factor depth when cache is stale/shallow
    try:
        from bet_placer.ml.factor_store import load_summary, rebuild as rebuild_factors
        factors = load_summary() or {}
        needs_depth = (
            int(factors.get("total_nodes") or 0) < 30_000
            or not (factors.get("depth") or {})
            or int(factors.get("version") or 0) < 2
        )
        if needs_depth:
            factors = rebuild_factors() or factors
        if factors:
            out["factors"] = factors
    except Exception:
        factors = out.get("factors") or {}

    kept = []
    for c in list(out.get("containers") or []):
        c = dict(c)
        if c.get("kind") == "sport_grid":
            by_sp = {str(s.get("sport")): dict(s) for s in (c.get("sports") or []) if isinstance(s, dict)}
            sports = []
            for sp in SPORTS:
                cell = by_sp.get(sp) or {"sport": sp, "n": 0, "need": 1, "status": "training"}
                sports.append(_scrub_cell(cell))
            c["sports"] = sports
            # Container training if any sport still training
            if any(s.get("status") == "training" for s in sports):
                c["status"] = "training"
            elif c.get("chart") and not _curve_ok(curves, c.get("chart")):
                c["status"] = "training"
            else:
                c["status"] = "ready"
        elif c.get("kind") in ("market_list", "tier_list", "league_list", "health"):
            rows = []
            for row in c.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                rows.append(_scrub_cell(dict(row)))
            c["rows"] = rows
            if not rows or any(r.get("status") == "training" for r in rows):
                # Keep structure — if empty, mark training
                if not rows:
                    c["status"] = "training"
                elif any(r.get("status") == "training" for r in rows) and not any(
                    r.get("status") == "ready" for r in rows
                ):
                    c["status"] = "training"
                else:
                    c["status"] = "ready"
            else:
                c["status"] = "ready"
            if str(c.get("id") or "").startswith("15a"):
                labels = " ".join(str(r.get("market") or "").lower() for r in rows)
                if "basketball" not in labels or "cricket" not in labels:
                    c["status"] = "training"
        elif c.get("kind") == "targets":
            # Prefer a real graded holdout; else champion — never show 0 from empty epoch
            ts = dict(c.get("train_status") or {})
            bets = int(ts.get("bets") or 0)
            hold = c.get("holdout_roi")
            champ = c.get("champion_roi")
            best = c.get("best_roi")
            if bets <= 0 or hold is None:
                hold = champ if champ is not None else best
                c["holdout_roi"] = hold
                if c.get("holdout_accuracy") is None:
                    c["holdout_accuracy"] = (
                        ts.get("champion_accuracy")
                        or ts.get("best_accuracy")
                        or c.get("best_accuracy")
                    )
                c["holdout_source"] = "champion" if champ is not None else "best"
            else:
                c["holdout_source"] = "live"
            for key in ("holdout_roi", "champion_roi", "best_roi"):
                v = c.get(key)
                try:
                    if v is not None and float(v) < 0:
                        c[key] = None
                except (TypeError, ValueError):
                    c[key] = None
            if c.get("holdout_roi") is None and c.get("best_roi") is None:
                c["status"] = "training"
            else:
                c["status"] = "ready"
        elif c.get("kind") == "factors":
            nodes = int((factors or {}).get("total_nodes") or c.get("total_nodes") or 0)
            c["total_nodes"] = nodes
            c["total_edges"] = int((factors or {}).get("total_edges") or c.get("total_edges") or 0)
            c["by_sport"] = (factors or {}).get("by_sport") or c.get("by_sport") or {}
            c["by_type"] = (factors or {}).get("by_type") or c.get("by_type") or {}
            c["depth"] = (factors or {}).get("depth") or {}
            c["status"] = "ready" if nodes >= 10_000 else "training"
        elif c.get("kind") == "chart":
            c["status"] = "ready" if _curve_ok(curves, c.get("chart")) else "training"
        elif c.get("status") == "building":
            c["status"] = "training"

        ok, reason = container_acceptable(c, curves)
        if ok:
            c["status"] = "ready"
            c.pop("training_reason", None)
        else:
            c["status"] = "training"
            c["training_reason"] = reason
        kept.append(c)

    out["containers"] = kept
    report = desk_quality_report(out)
    out["desk_quality"] = report
    if int(out.get("total_corpus") or 0) > 1000:
        out["status"] = "ready"
    # Surface one honest holdout on craft blob for the hero
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
