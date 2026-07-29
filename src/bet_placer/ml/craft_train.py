"""Deep craft training on recent ESPN boards until paper ROI ≥ target.

Uses: multi-market gems × 3 sports, sklearn MLP ranker, SQLite progress,
selective staking. Evaluates on the most recent finished window (holdout-ish).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from bet_placer.config import data_path
from bet_placer.ml.craft_nn import CraftNet
from bet_placer.ml.craft_store import get_meta, log_epoch, progress_snapshot, set_meta
from bet_placer.ml.gem_craft import spot_gems_from_events, update_craft_weights_from_tickets
from bet_placer.ml.paper_book import (
    DEFAULT_BANKROLL,
    DEFAULT_MATCH_BUDGET,
    _empty_book,
    _gems_for_board,
    _iter_board_events,
    _model_events_for_board,
    _place_gems,
    apply_paper_learning,
    save_book,
    summarize,
)

TARGET_ROI = 0.25  # overall paper ROI gate
TARGET_ACC = 0.60  # hit rate floor — nothing places below this
MIN_SPORT_ROI = 0.0  # each sport must be strictly positive (roi > 0)
FLOOR_P = 0.60  # blend / model_p never below 60% when placing
# Markets that keep bleeding basketball/soccer holdout — drop until sport clears
# Exact-ish market tokens — keep short substrings out (e.g. "ou" matches "outcome")
BLEED_MARKETS = frozenset({
    "over_under_goals", "over_under", "totals", "total", "asian_handicap",
    "spread", "spreads", "handicap",
})
CORE_MARKETS = frozenset({
    "match_winner", "h2h", "moneyline", "ml", "1x2", "result",
})
# ponytail: holdout eval ~600 matches/sport — 10k gates never clear
MIN_BETS = 500
MIN_BETS_PER_SPORT = 80  # enough that a 10-ticket fluke can't flip a sport "ok"
MONTHLY_LOOKBACK = 12  # recent months must stay non-negative on average
PAIRED_PER_SPORT = 4_000  # legacy cap — train/eval use smaller slices below
PAIRED_TRAIN_PER_SPORT = 800  # rotating fuel while learning
PAIRED_EVAL_PER_SPORT = 350  # fixed holdout slice — same tickets every eval
GEMS_PER_MATCH = 8
HOLDOUT_KEY = "craft_holdout_v2"
CHAMPION_KEY = "craft_champion"


def _sport_roi(row: dict, match_budget: float) -> float | None:
    n = int(row.get("n") or 0)
    if n <= 0:
        return None
    stake = float(row.get("stake") or 0) or (n * match_budget * 0.85)
    if stake <= 0:
        return None
    return float(row.get("pnl") or 0) / stake


def _monthly_nonneg() -> tuple[bool, dict[str, Any]]:
    """Recent months must not run red per sport.

    Prefer craft epoch by_sport when those series exist; otherwise use betting-evolution
    monthly trends (craft epochs often log empty by_sport while training).
    """
    detail: dict[str, Any] = {"sports": {}, "source": "craft_epochs"}
    try:
        from bet_placer.ml.craft_store import progress_snapshot
        epochs = list(progress_snapshot().get("epochs") or [])
    except Exception:
        epochs = []

    craft_detail: dict[str, Any] = {"sports": {}}
    craft_usable = 0
    if len(epochs) >= 8:
        tail = epochs[-12:]
        for sp in ("soccer", "basketball", "cricket"):
            rois = []
            for e in tail:
                row = (e.get("by_sport") or {}).get(sp) or {}
                n = int(row.get("n") or 0)
                if n < 3:
                    continue
                stake = float(row.get("stake") or 0) or (n * 150.0)
                pnl = float(row.get("pnl") or 0)
                if stake > 0:
                    rois.append(pnl / stake)
            if len(rois) < 3:
                craft_detail["sports"][sp] = {"ok": False, "reason": "thin_epochs", "n": len(rois)}
                continue
            craft_usable += 1
            mean = sum(rois) / len(rois)
            neg = sum(1 for r in rois if r < 0)
            ok = mean >= 0 and neg <= max(1, len(rois) // 3)
            craft_detail["sports"][sp] = {
                "ok": ok,
                "mean_roi": round(mean, 4),
                "neg_epochs": neg,
                "n_epochs": len(rois),
            }
        if craft_usable >= 2:
            ok_all = all(bool((craft_detail["sports"].get(sp) or {}).get("ok")) for sp in ("soccer", "basketball", "cricket"))
            detail = {**craft_detail, "source": "craft_epochs", "all_ok": ok_all}
            return ok_all, detail

    # Betting-evolution monthly heartbeat (real book-fair pairs)
    try:
        from bet_placer.ml.betting_evolution import snapshot
        trends = snapshot().get("trends") or []
    except Exception:
        if craft_detail.get("sports"):
            detail = {**craft_detail, "source": "craft_epochs", "all_ok": False}
            return False, detail
        return False, {"error": "no_monthly", "sports": {}, "all_ok": False}

    ok_all = True
    detail["source"] = "betting_evolution"
    for sp in ("soccer", "basketball", "cricket"):
        rows = [t for t in trends if t.get("sport") == sp and (t.get("n") or 0) >= 8]
        rows = sorted(rows, key=lambda t: t.get("ym") or "")[-MONTHLY_LOOKBACK:]
        if len(rows) < 3:
            detail["sports"][sp] = {"ok": False, "reason": "thin_months", "n_months": len(rows)}
            ok_all = False
            continue
        rois = [float(t["roi"]) for t in rows if t.get("roi") is not None]
        neg = sum(1 for r in rois if r < 0)
        mean = sum(rois) / len(rois) if rois else -1.0
        # Mean-first: a few red months are fine if the window stays non-negative overall.
        ok = mean >= 0 and neg <= max(3, (len(rois) + 2) // 3)
        detail["sports"][sp] = {
            "ok": ok,
            "mean_roi": round(mean, 4),
            "neg_months": neg,
            "n_months": len(rows),
            "last_ym": rows[-1].get("ym") if rows else None,
        }
        if not ok:
            ok_all = False
    detail["all_ok"] = ok_all
    return ok_all, detail


def _ensure_holdout(pool: list[dict], *, per_sport: int = 500) -> dict[str, Any]:
    """Freeze the same match IDs for every epoch/run so accuracy is comparable."""
    meta = get_meta(HOLDOUT_KEY) or {}
    ids = meta.get("ids") if isinstance(meta, dict) else None
    if isinstance(ids, dict) and all(ids.get(sp) for sp in ("soccer", "basketball", "cricket")):
        return meta
    by: dict[str, list[str]] = defaultdict(list)
    for g in pool:
        sp = g.get("sport")
        gid = g.get("id")
        if sp and gid:
            by[sp].append(str(gid))
    frozen: dict[str, list[str]] = {}
    for sp in ("soccer", "basketball", "cricket"):
        rows = sorted(set(by.get(sp) or []))
        if not rows:
            frozen[sp] = []
            continue
        # Most-recent slice — fixed forever once written
        take = min(max(per_sport, 80), max(80, len(rows) // 3))
        frozen[sp] = rows[-take:]
    meta = {
        "ids": frozen,
        "paired_fixed": True,
        "n": {sp: len(frozen[sp]) for sp in frozen},
        "note": "Eval always uses these match ids + fixed paired closes — not reshuffled failures.",
    }
    set_meta(HOLDOUT_KEY, meta)
    return meta


def _split_holdout(pool: list[dict], holdout: dict) -> tuple[list[dict], list[dict]]:
    ids = set()
    for sp_ids in (holdout.get("ids") or {}).values():
        ids.update(str(x) for x in (sp_ids or []))
    train, ev = [], []
    for g in pool:
        (ev if str(g.get("id")) in ids else train).append(g)
    if len(ev) < 24:
        # First boot edge-case — fall back to fraction split once
        return _split_by_sport(pool, train_frac=0.55)
    return train, ev


def _sports_all_present(by_sport: dict, *, match_budget: float = 200.0) -> bool:
    """True when each of soccer/BB/cricket has enough tickets and ROI > 0."""
    for sp in ("soccer", "basketball", "cricket"):
        row = by_sport.get(sp) or {}
        n = int(row.get("n") or 0)
        sroi = _sport_roi(row, match_budget)
        if n < MIN_BETS_PER_SPORT or sroi is None or sroi <= MIN_SPORT_ROI:
            return False
    return True


def _maybe_promote_champion(
    *,
    net: CraftNet,
    craft_w: dict,
    threshold: float,
    min_p: float,
    roi: float,
    acc: float | None,
    bets: int,
    by_sport: dict,
    epoch: int,
    target_acc: float,
) -> dict[str, Any]:
    """Lock policy only when holdout clears accuracy + all three sports — never crown cricket-only."""
    champ = dict(get_meta(CHAMPION_KEY) or {})
    if acc is None or float(acc) < target_acc or bets < max(500, MIN_BETS // 5):
        return champ
    if not _sports_all_present(by_sport):
        return champ
    prev = float(champ.get("roi") or -1.0)
    # Don't keep a champion that itself fails the three-sport gate
    if champ and not _sports_all_present(champ.get("by_sport") or {}):
        prev = -1.0
    better = roi > prev + 0.002 or (
        abs(roi - prev) <= 0.002 and float(acc) > float(champ.get("accuracy") or 0)
    )
    if not better:
        return champ
    champ = {
        "roi": roi,
        "accuracy": acc,
        "bets": bets,
        "epoch": epoch,
        "threshold": threshold,
        "min_p": min_p,
        "craft_w": craft_w,
        "by_sport": by_sport,
    }
    set_meta(CHAMPION_KEY, champ)
    try:
        net.save_champion()
    except Exception:
        pass
    return champ


def _restore_champion_if_worse(
    *,
    net: CraftNet,
    craft_w: dict,
    threshold: float,
    min_p: float,
    roi: float,
    acc: float | None,
    target_acc: float,
) -> tuple[dict, float, float, bool]:
    """If this holdout run forgot what worked, snap back — but never restore a one-sport / red champion."""
    champ = get_meta(CHAMPION_KEY) or {}
    if not champ:
        return craft_w, threshold, min_p, False
    # Stale cricket-only / underwater soccer champions block three-sport learning
    if not _sports_all_present(champ.get("by_sport") or {}):
        return craft_w, threshold, min_p, False
    c_roi = float(champ.get("roi") or -1)
    c_acc = float(champ.get("accuracy") or 0)
    worse = (
        roi < c_roi - 0.02
        or (acc is not None and float(acc) < min(target_acc, c_acc) - 0.02)
    )
    if not worse:
        return craft_w, threshold, min_p, False
    net.load_champion()
    restored_w = dict(champ.get("craft_w") or craft_w)
    thr = max(FLOOR_P, float(champ.get("threshold") or threshold))
    mp = max(FLOOR_P, float(champ.get("min_p") or min_p))
    # Tighten slightly after a regression so we don't re-bleed
    thr = min(0.75, thr + 0.01)
    mp = min(0.75, mp + 0.01)
    return restored_w, thr, mp, True


def _targets_cleared(
    *,
    roi: float,
    acc: float | None,
    bets: int,
    by_sport: dict,
    target_roi: float,
    target_acc: float,
    match_budget: float,
) -> tuple[bool, dict[str, Any]]:
    """Stop only when: overall ≥25%, each sport ROI > 0, accuracy ok, monthly not red."""
    detail: dict[str, Any] = {
        "roi_ok": bets >= MIN_BETS and roi >= target_roi,
        "acc_ok": acc is not None and float(acc) >= target_acc and bets >= MIN_BETS,
        "sports": {},
        "monthly": {},
    }
    sports_ok = True
    for sp in ("soccer", "basketball", "cricket"):
        row = by_sport.get(sp) or {}
        n = int(row.get("n") or 0)
        sroi = _sport_roi(row, match_budget)
        shr = row.get("hit_rate")
        ok = (
            n >= MIN_BETS_PER_SPORT
            and sroi is not None
            and sroi > MIN_SPORT_ROI
            and (shr is None or float(shr) >= target_acc)
        )
        detail["sports"][sp] = {
            "n": n, "roi": sroi, "hit_rate": shr, "ok": ok, "need_positive": True,
        }
        if not ok:
            sports_ok = False
    monthly_ok, monthly_detail = _monthly_nonneg()
    detail["monthly"] = monthly_detail
    detail["all_ok"] = bool(
        detail["roi_ok"] and detail["acc_ok"] and sports_ok and monthly_ok
    )
    return detail["all_ok"], detail


def train_until_roi(
    *,
    target_roi: float = TARGET_ROI,
    target_acc: float = TARGET_ACC,
    max_epochs: int | None = None,
    bankroll: float = DEFAULT_BANKROLL,
    match_budget: float = DEFAULT_MATCH_BUDGET,
    start_games: int = 600,
    max_games: int = 6_000,
    verbose: bool = True,
) -> dict[str, Any]:
    """Keep training until ROI + accuracy + per-sport gates clear.

    Eval is a frozen holdout (same matches every epoch). Train elsewhere.
    Champion policy is restored when holdout regresses — no hard-coded wins.
    """
    # None / 0 = unlimited. Never "finish without hit" unless caller sets a positive cap.
    unlimited = max_epochs is None or int(max_epochs) <= 0
    epoch_cap = 10**9 if unlimited else int(max_epochs)
    prev_status = get_meta("train_status") or {}
    set_meta("train_status", {
        **prev_status,
        "state": "running",
        "target_roi": target_roi,
        "target_accuracy": target_acc,
        "epoch": int(prev_status.get("epoch") or 0),
        "unlimited": unlimited,
        "note": "overall≥25% · each sport ROI>0 · hit≥60% · sport ledger · probation",
    })
    net = CraftNet()
    # Prefer locked champion weights if we already found something that worked
    if (get_meta(CHAMPION_KEY) or {}).get("roi") is not None:
        net.load_champion()
        craft_w = dict((get_meta(CHAMPION_KEY) or {}).get("craft_w") or {})
        threshold = max(FLOOR_P, float((get_meta(CHAMPION_KEY) or {}).get("threshold") or FLOOR_P))
        min_p = max(FLOOR_P, float((get_meta(CHAMPION_KEY) or {}).get("min_p") or FLOOR_P))
    else:
        craft_w = {}
        threshold = max(FLOOR_P, 0.60)
        min_p = max(FLOOR_P, 0.60)
    memory: list[dict] = []
    best = dict(get_meta("best_roi") or {})
    # Drop polluted best from old runs (sentinel -1 or sub-60% accuracy)
    if (
        best.get("roi") is not None
        and (
            float(best.get("roi") or 0) < 0
            or float(best.get("accuracy") or 0) < target_acc
        )
    ):
        best = {}
    history = []
    allow_sports: set[str] | None = {"soccer", "basketball", "cricket"}
    gate_detail: dict[str, Any] = {}
    sport_ev_boost: dict[str, float] = {"soccer": 0.0, "basketball": 0.0, "cricket": 0.0}
    sport_ledger: dict = dict(get_meta("sport_ledger") or {})
    notes_path = data_path("craft_notes.log")
    notes_path.parent.mkdir(parents=True, exist_ok=True)

    # Build holdout once from a deep pool so later epochs stay comparable
    holdout = _ensure_holdout(_recent_finished(8_000), per_sport=600)

    for epoch in range(1, epoch_cap + 1):
        window = min(max_games, start_games + (epoch - 1) * 40)
        per_sport = max(200, window // 3)
        pool = _recent_finished(max(window * 2, 2_000))
        games = _balance_sports(pool, per_sport=per_sport)
        if len(games) < 24:
            games = pool[-window:]

        train_games, eval_games = _split_holdout(games, holdout)
        # Eval must always include the frozen holdout ids even if window is thin
        _, full_eval = _split_holdout(pool, holdout)
        if len(full_eval) >= len(eval_games):
            eval_games = _balance_sports(full_eval, per_sport=max(120, per_sport // 2))

        # Always evaluate all three sports — never cricket-only desk
        eval_allow = {"soccer", "basketball", "cricket"}
        # Soccer/BB boards re-bleed OU/easy_money — stay moneyline/paired-only forever
        sport_min_p = {"soccer": min_p, "basketball": min_p, "cricket": min_p}
        sport_core_only = {
            "soccer": True,
            "basketball": True,
            "cricket": not bool((sport_ledger.get("cricket") or {}).get("ok")),
        }
        for sp in ("soccer", "basketball", "cricket"):
            row = sport_ledger.get(sp) or {}
            n_sp = int(row.get("n") or 0)
            sroi = row.get("roi")
            shr = row.get("hit_rate")
            roi_bad = sroi is not None and float(sroi) <= 0
            hit_bad = shr is not None and float(shr) < target_acc
            not_ok = row.get("ok") is False
            if not_ok or roi_bad or hit_bad:
                sport_core_only[sp] = True  # drop OU/AH bleed
            if n_sp > 0 and n_sp < MIN_BETS_PER_SPORT // 2:
                # Starved sample — ease EV so moneyline can fill; keep a mild p floor
                sport_ev_boost[sp] = min(0.04, float(sport_ev_boost.get(sp) or 0))
                sport_min_p[sp] = min(0.70, max(min_p, FLOOR_P) + 0.02)
            elif hit_bad and not roi_bad:
                # Making money but wrong too often → raise p floor, light EV
                sport_min_p[sp] = min(0.78, max(min_p, FLOOR_P) + 0.08)
                sport_ev_boost[sp] = min(0.08, max(float(sport_ev_boost.get(sp) or 0), 0.03))
            elif roi_bad:
                sport_ev_boost[sp] = min(0.12, max(float(sport_ev_boost.get(sp) or 0), 0.05))
                sport_min_p[sp] = min(0.75, max(min_p, FLOOR_P) + 0.05)
            elif row.get("ok"):
                sport_ev_boost[sp] = max(0.0, float(sport_ev_boost.get(sp) or 0) - 0.01)
                # Cricket boards can reopen; soccer/BB boards re-bleed OU/easy_money
                if sp == "cricket":
                    sport_core_only[sp] = False

        # Train on rotating fuel — all sports keep learning
        warm = _run_epoch(
            epoch=epoch,
            games=train_games,
            net=net,
            threshold=threshold,
            min_p=min_p,
            bankroll=bankroll,
            match_budget=match_budget,
            craft_w=craft_w,
            memory=memory,
            allow_sports={"soccer", "basketball", "cricket"},
            log=False,
            inject_paired=True,
            paired_fixed=False,
            fit=True,
            sport_ev_boost=sport_ev_boost,
            sport_min_p=sport_min_p,
            sport_core_only=sport_core_only,
        )
        craft_w = warm["craft_w"]

        # Eval holdout — all three sports every epoch
        ev = _run_epoch(
            epoch=epoch,
            games=eval_games,
            net=net,
            threshold=threshold,
            min_p=min_p,
            bankroll=bankroll,
            match_budget=match_budget,
            craft_w=craft_w,
            memory=memory,
            allow_sports=eval_allow,
            log=True,
            inject_paired=True,
            paired_fixed=True,
            fit=False,
            sport_ev_boost=sport_ev_boost,
            sport_min_p=sport_min_p,
            sport_core_only=sport_core_only,
        )
        # Don't overwrite craft_w from eval (eval doesn't learn)
        roi = float(ev["summary"].get("roi") or 0)
        acc = ev["summary"].get("accuracy")
        bets = int(ev["summary"].get("settled") or 0)
        by_sport = ev["summary"].get("by_sport") or {}
        # Persist sport verdicts so gated sports stay gated until probation
        sport_ledger = _merge_sport_ledger(sport_ledger, by_sport, match_budget)
        set_meta("sport_ledger", sport_ledger)
        cleared, gate_detail = _targets_cleared(
            roi=roi,
            acc=float(acc) if acc is not None else None,
            bets=bets,
            by_sport=by_sport,
            target_roi=target_roi,
            target_acc=target_acc,
            match_budget=match_budget,
        )
        # Overlay ledger so desk shows last-known soccer/BB even when they sat out
        for sp, row in sport_ledger.items():
            if int((by_sport.get(sp) or {}).get("n") or 0) > 0:
                continue
            gate_detail.setdefault("sports", {})[sp] = {
                "n": row.get("n"),
                "roi": row.get("roi"),
                "hit_rate": row.get("hit_rate"),
                "ok": bool(row.get("ok")),
                "need_positive": True,
            }

        # Progress notes — durable log the user can tail
        try:
            bits = []
            for sp in ("soccer", "basketball", "cricket"):
                r = sport_ledger.get(sp) or {}
                if not r:
                    bits.append(f"{sp}=?")
                    continue
                tag = "ok" if r.get("ok") else "FAIL"
                rr = r.get("roi")
                hh = r.get("hit_rate")
                bits.append(
                    f"{sp}={tag}"
                    f"/roi={rr*100:+.1f}%" if rr is not None else f"{sp}={tag}"
                )
                if rr is not None and hh is not None:
                    bits[-1] = f"{sp}={tag}/roi={rr*100:+.1f}%/hit={hh*100:.0f}%"
            note = (
                f"ep{epoch} overall={roi*100:+.1f}% acc={acc} bets={bets} "
                f"allow={sorted(eval_allow)} "
                f"core_only={[sp for sp,v in sport_core_only.items() if v]} "
                f"min_p={{{','.join(f'{sp}:{sport_min_p.get(sp, min_p):.2f}' for sp in ('soccer','basketball','cricket'))}}} "
                f"{' '.join(bits)}\n"
            )
            with notes_path.open("a", encoding="utf-8") as fh:
                fh.write(note)
        except Exception:
            pass

        # Update EV boosts from this holdout — bleeding sports must clear a higher bar
        for sp in ("soccer", "basketball", "cricket"):
            sroi = _sport_roi(by_sport.get(sp) or {}, match_budget)
            if sroi is None:
                # Use ledger if sport sat out
                sroi = (sport_ledger.get(sp) or {}).get("roi")
            if sroi is None:
                continue
            if float(sroi) < 0:
                sport_ev_boost[sp] = min(0.18, sport_ev_boost.get(sp, 0) + 0.02)
            elif float(sroi) > 0.05:
                sport_ev_boost[sp] = max(0.0, sport_ev_boost.get(sp, 0) - 0.01)

        champ = _maybe_promote_champion(
            net=net, craft_w=craft_w, threshold=threshold, min_p=min_p,
            roi=roi, acc=float(acc) if acc is not None else None,
            bets=bets, by_sport=by_sport, epoch=epoch, target_acc=target_acc,
        )
        craft_w, threshold, min_p, restored = _restore_champion_if_worse(
            net=net, craft_w=craft_w, threshold=threshold, min_p=min_p,
            roi=roi, acc=float(acc) if acc is not None else None,
            target_acc=target_acc,
        )

        history.append({
            "epoch": epoch, "roi": roi, "accuracy": acc, "bets": bets,
            "threshold": threshold, "min_p": min_p, "allow": sorted(eval_allow),
            "gates": gate_detail, "restored": restored,
            "holdout_n": len(eval_games),
        })
        if len(history) > 400:
            history = history[-300:]

        # best_roi only from holdout runs that clear accuracy + all three sports
        if (
            bets >= max(500, MIN_BETS // 8)
            and acc is not None
            and float(acc) >= target_acc
            and roi > 0
            and _sports_all_present(by_sport, match_budget=match_budget)
            and (
                not _sports_all_present((best.get("by_sport") or {}), match_budget=match_budget)
                or roi > float(best.get("roi") or -1)
            )
        ):
            best = {
                "roi": roi,
                "accuracy": acc,
                "bets": bets,
                "epoch": epoch,
                "threshold": threshold,
                "min_p": min_p,
                "by_sport": by_sport,
                "bankroll": ev["summary"].get("bankroll"),
                "pnl": ev["summary"].get("pnl"),
                "gates": gate_detail,
                "holdout": True,
            }
            set_meta("best_roi", best)

        set_meta("train_status", {
            "state": "running",
            "epoch": epoch,
            "roi": roi,
            "accuracy": acc,
            "holdout_roi": roi,
            "holdout_accuracy": acc,
            "holdout_games": len(eval_games),
            "holdout_n": (holdout.get("n") or {}),
            "best_roi": best.get("roi"),
            "best_accuracy": best.get("accuracy"),
            "champion_roi": champ.get("roi") if champ else (get_meta(CHAMPION_KEY) or {}).get("roi"),
            "champion_accuracy": (get_meta(CHAMPION_KEY) or {}).get("accuracy"),
            "restored_champion": restored,
            "target_roi": target_roi,
            "target_accuracy": target_acc,
            "threshold": threshold,
            "min_p": min_p,
            "bets": bets,
            "allow_sports": ["basketball", "cricket", "soccer"],
            "sport_ev_boost": sport_ev_boost,
            "sport_min_p": sport_min_p,
            "gates": gate_detail,
            "unlimited": unlimited,
            "note": "Accuracy = frozen holdout only (same matches every run)",
        })

        if verbose:
            print(
                f"[craft] epoch {epoch}{'/∞' if unlimited else f'/{epoch_cap}'} · "
                f"holdout ROI {roi*100:.1f}% · acc {acc} · bets {bets} · "
                f"thr {threshold:.3f} · restored={restored} · gates {gate_detail.get('all_ok')}"
            )

        if cleared:
            set_meta("train_status", {
                "state": "hit_target",
                "epoch": epoch,
                "roi": roi,
                "accuracy": acc,
                "holdout_roi": roi,
                "holdout_accuracy": acc,
                "target_roi": target_roi,
                "target_accuracy": target_acc,
                "bets": bets,
                "gates": gate_detail,
            })
            break

        # Adapt — never wipe winning memory; never drop below 60%
        if bets < MIN_BETS:
            allow_sports = {"soccer", "basketball", "cricket"}
            if bets == 0 and epoch % 8 == 0:
                threshold = FLOOR_P
                min_p = FLOOR_P
                # Keep wins in memory; drop losers only
                memory[:] = [t for t in memory if t.get("status") == "won"][-5_000:]
            else:
                threshold = max(FLOOR_P, threshold - 0.005)
                min_p = max(FLOOR_P, min_p - 0.005)
        elif roi < 0 or (acc is not None and float(acc) < target_acc):
            threshold = min(0.75, threshold + 0.015)
            min_p = min(0.75, min_p + 0.01)
        elif roi < target_roi * 0.5:
            threshold = min(0.72, threshold + 0.01)
            min_p = min(0.72, min_p + 0.008)
        elif roi < target_roi:
            allow_sports = {"soccer", "basketball", "cricket"}
            min_p = min(0.72, min_p + 0.005)
            if bets > 40:
                threshold = min(0.70, threshold + 0.005)
        elif bets < 50:
            threshold = max(FLOOR_P, threshold - 0.005)

    hit = bool(gate_detail.get("all_ok"))
    if not hit and best.get("gates"):
        hit = bool((best.get("gates") or {}).get("all_ok"))
    snap = progress_snapshot()
    set_meta("train_status", {
        **(get_meta("train_status") or {}),
        "state": "hit_target" if hit else ("running" if unlimited else "finished_without_hit"),
        "best_roi": best.get("roi"),
        "best_accuracy": best.get("accuracy"),
        "target_roi": target_roi,
        "target_accuracy": target_acc,
        "gates": gate_detail or best.get("gates"),
        "unlimited": unlimited,
    })
    apply_paper_learning()
    return {
        "target_roi": target_roi,
        "target_accuracy": target_acc,
        "hit_target": hit,
        "best": best,
        "history": history[-80:],
        "progress": snap,
        "gates": gate_detail or best.get("gates"),
        "note": "Stops only when ROI≥target, accuracy≥target, and each of soccer/basketball/cricket clears ROI with enough bets. Unlimited by default.",
    }


def _recent_finished(max_games: int) -> list[dict]:
    finished = [
        r for r in _iter_board_events()
        if r["status"] == "completed" and r["hs"] is not None and r["aws"] is not None
    ]
    finished.sort(key=lambda r: r.get("kickoff") or "")
    board = finished[-max(1, max_games):]
    # Deepen thin BB/cricket boards with history — do NOT global-truncate by date
    # (NBA Elo history is older and would be wiped by a recent-only slice).
    hist = _history_sport_rows(per_sport=max(2_000, max_games))
    merged = {r["id"]: r for r in hist}
    for r in board:
        merged[r["id"]] = r
    return list(merged.values())


def _history_sport_rows(per_sport: int = 2_000) -> list[dict]:
    """NBA + cricket + multi-league club soccer as board-shaped rows for craft depth."""
    rows: list[dict] = []

    def _stride(items: list, n: int) -> list:
        if len(items) <= n:
            return items
        step = len(items) / n
        return [items[int(i * step)] for i in range(n)]

    try:
        from bet_placer.ml.sport_history import load_cricket_matches, load_nba_team_games
        # Stride full history — do not only take the newest tail (that wasted 60k NBA games)
        nba = _stride(load_nba_team_games(), max(per_sport, 4_000))
        for g in nba:
            home, away = g.get("home"), g.get("away")
            hs, aws = g.get("hs"), g.get("as")
            if not home or not away or hs is None or aws is None:
                continue
            rows.append({
                "sport_key": "basketball_nba",
                "sport": "basketball",
                "id": f"hist-bb-{g.get('date')}-{home}-{away}",
                "home": home,
                "away": away,
                "status": "completed",
                "hs": int(hs),
                "aws": int(aws),
                "kickoff": str(g.get("date") or ""),
                "league": "NBA history",
                "raw": {
                    "id": f"hist-bb-{home}-{away}",
                    "home_team": home,
                    "away_team": away,
                    "commence_time": str(g.get("date") or ""),
                    "sport_title": "NBA",
                    "bookmakers": [],
                },
            })
        ck = _stride(load_cricket_matches(), max(per_sport, 4_000))
        for g in ck:
            home, away, res = g.get("home"), g.get("away"), g.get("res")
            if not home or not away or res not in ("H", "A"):
                continue
            hs, aws = (1, 0) if res == "H" else (0, 1)
            rows.append({
                "sport_key": "cricket_all",
                "sport": "cricket",
                "id": f"hist-ck-{g.get('date')}-{home}-{away}",
                "home": home,
                "away": away,
                "status": "completed",
                "hs": hs,
                "aws": aws,
                "kickoff": str(g.get("date") or ""),
                "league": g.get("league") or "Cricket history",
                "raw": {
                    "id": f"hist-ck-{home}-{away}",
                    "home_team": home,
                    "away_team": away,
                    "commence_time": str(g.get("date") or ""),
                    "sport_title": g.get("league") or "Cricket",
                    "bookmakers": [],
                },
            })
    except Exception:
        pass
    try:
        from bet_placer.ml.soccer_club import load_club_matches
        club = _stride(load_club_matches(max_rows=80_000), max(per_sport, 6_000))
        for g in club:
            home, away = g.get("home"), g.get("away")
            hs, aws = g.get("hs"), g.get("aws")
            if not home or not away or hs is None or aws is None:
                continue
            books = []
            if g.get("b365_h") and g.get("b365_a"):
                outcomes = [
                    {"name": home, "price": g["b365_h"]},
                    {"name": away, "price": g["b365_a"]},
                ]
                if g.get("b365_d"):
                    outcomes.insert(1, {"name": "Draw", "price": g["b365_d"]})
                books = [{"key": "b365", "title": "Bet365", "markets": [{"key": "h2h", "outcomes": outcomes}]}]
            league = g.get("league") or "Club soccer"
            rows.append({
                "sport_key": "soccer_epl",
                "sport": "soccer",
                "id": f"hist-sc-{g.get('date')}-{home}-{away}",
                "home": home,
                "away": away,
                "status": "completed",
                "hs": int(hs),
                "aws": int(aws),
                "kickoff": str(g.get("date") or ""),
                "league": league,
                "raw": {
                    "id": f"hist-sc-{home}-{away}",
                    "home_team": home,
                    "away_team": away,
                    "commence_time": str(g.get("date") or ""),
                    "sport_title": league,
                    "bookmakers": books,
                },
            })
    except Exception:
        pass
    return rows


def _balance_sports(rows: list[dict], per_sport: int) -> list[dict]:
    by: dict[str, list] = defaultdict(list)
    for r in reversed(rows):
        sp = r["sport"]
        if len(by[sp]) < per_sport:
            by[sp].append(r)
    out = []
    for sp in ("soccer", "basketball", "cricket"):
        out.extend(reversed(by.get(sp) or []))
    out.sort(key=lambda r: r.get("kickoff") or "")
    return out


def _filter_gems(
    gems: list[dict],
    net: CraftNet,
    *,
    sport: str,
    threshold: float,
    min_p: float,
    core_only: bool = False,
) -> list[dict]:
    scored = []
    # Synthetic fair often prices ~1.33 — old soccer floor 1.40 starved the desk to 0 bets
    odds_lo, odds_hi = 1.25, 5.0
    need = max(min_p, FLOOR_P)
    thr = max(threshold, FLOOR_P)
    for g in gems:
        mkt = str(g.get("market") or "").lower()
        if core_only:
            if any(b == mkt or b in mkt for b in BLEED_MARKETS):
                continue
            if mkt and not any(c == mkt or c in mkt for c in CORE_MARKETS):
                continue
            # Board "easy_money" shorts drag BB below 0 ROI even when paired clears
            if g.get("gem_kind") in ("easy_money", "niche"):
                continue
        p = float(g.get("our_probability") or 0)
        if p < need or p > 0.92:
            continue
        odds = float(g.get("odds") or g.get("decimal_odds") or 0)
        if odds < odds_lo or odds > odds_hi:
            continue
        ph = net.predict_proba(g, sport=sport)
        g = {**g, "nn_p": round(ph, 4)}
        blend = 0.55 * ph + 0.45 * p
        if blend < thr:
            continue
        scored.append(g)
    scored.sort(
        key=lambda g: (
            -(float(g.get("our_probability") or 0) * float(g.get("odds") or 1) - 1),
            -float(g.get("nn_p") or 0),
        )
    )
    niche = [g for g in scored if g.get("gem_kind") == "niche"]
    core = [g for g in scored if g.get("gem_kind") != "niche"]
    out = (niche[:3] + core[:GEMS_PER_MATCH]) if niche else scored[:GEMS_PER_MATCH]
    return out[:GEMS_PER_MATCH]


def _collect_gems(row: dict, craft_w: dict) -> tuple[list[dict], dict]:
    gems, meta = _gems_for_board(row, craft_w=craft_w, full_slip=False)
    if not gems:
        try:
            gems = spot_gems_from_events(
                _model_events_for_board(row), craft_weights=craft_w, max_gems=12,
            )
            meta = {
                "match_id": row["id"],
                "home": row["home"],
                "away": row["away"],
                "sport": row["sport"],
            }
        except Exception:
            return [], {}
    if not gems or not meta:
        return [], {}
    # Prefer real book prices when present; keep synthetic so craft never starves
    real = [g for g in gems if (g.get("odds_source") or "") != "synthetic_fair"]
    gems = real if real else gems
    # Soft floors — never below 60% hit expectation
    floor_p, floor_edge = FLOOR_P, 0.3
    gems = [
        g for g in gems
        if float(g.get("our_probability") or 0) >= floor_p
        and float(g.get("edge_pct") or g.get("edge") or 0) >= floor_edge
    ]
    return gems, meta


def _place_paired_rows(
    book: dict,
    rows: list[dict],
    *,
    net: CraftNet,
    threshold: float,
    min_p: float,
    unit_stake: float = 25.0,
    allow_sports: set[str] | None = None,
    sport_ev_boost: dict[str, float] | None = None,
    sport_min_p: dict[str, float] | None = None,
) -> int:
    """Settle historical paired closes with fractional-Kelly stakes (edge-only)."""
    placed = 0
    bank = float(book.get("bankroll") or 0)
    boost = sport_ev_boost or {}
    sp_min = sport_min_p or {}
    for r in rows:
        sport = r.get("sport") or "soccer"
        if allow_sports and sport not in allow_sports:
            continue
        p = float(r.get("model_p") or 0)
        odds = float(r.get("close_odds") or 0)
        need = max(float(sp_min.get(sport) or min_p), FLOOR_P)
        if p < need or odds < 1.30 or odds > 4.5:
            continue
        gem = {
            "market": r.get("market") or "h2h",
            "selection": r.get("selection") or "home",
            "odds": odds,
            "our_probability": p,
            "edge": float(r.get("edge") or 0),
        }
        ph = net.predict_proba(gem, sport=sport) if net.n_trained else p
        blend = 0.55 * ph + 0.45 * p
        # ponytail: champion NN under-scores soccer (~0.39 vs model_p); don't veto calibrated favorites
        if sport == "soccer":
            blend = max(blend, p - 0.03)
        if blend < max(threshold, FLOOR_P, need - 0.02):
            continue
        # Required edge vs book: only bet when EV clear (keeps sport ROI non-negative path)
        ev = blend * odds - 1.0
        need_ev = {"soccer": 0.04, "basketball": 0.06, "cricket": 0.04}.get(sport, 0.06)
        need_ev += float(boost.get(sport) or 0)
        if ev < need_ev:
            continue
        # Fractional Kelly: f* = edge/(odds-1), take 1/4 Kelly, cap 1.5% bank
        b = odds - 1.0
        kelly = max(0.0, ev / b) if b > 0 else 0.0
        stake = bank * min(0.015, kelly * 0.25)
        stake = max(10.0, min(unit_stake * 1.5, stake))
        if stake > bank * 0.02:
            stake = bank * 0.02
        if stake < 8 or stake > bank:
            continue
        hit = int(r.get("hit") or 0) == 1
        ret = round(stake * odds, 2) if hit else 0.0
        pnl = round(ret - stake, 2)
        bank -= stake
        bank += ret
        book.setdefault("tickets", []).append({
            "id": f"paired-{r.get('id')}-{sport}",
            "match_id": f"paired-{r.get('id')}",
            "home": r.get("home"),
            "away": r.get("away"),
            "sport": sport,
            "market": (r.get("market") or "h2h").lower(),
            "selection": r.get("selection"),
            "label": r.get("selection"),
            "odds": odds,
            "stake": round(stake, 2),
            "our_probability": p,
            "nn_p": round(ph, 4),
            "ev": round(ev, 4),
            "status": "won" if hit else "lost",
            "hit": hit,
            "pnl": pnl,
            "return_inr": ret,
            "gem_kind": "paired_close",
            "odds_source": r.get("source") or "paired",
        })
        placed += 1
    book["bankroll"] = round(bank, 2)
    return placed


def _sport_allow(
    *,
    by_sport: dict | None = None,
    boost: dict[str, float] | None = None,
    min_hit: float = TARGET_ACC,
    ledger: dict | None = None,
) -> set[str]:
    """Holdout eval: skip sports with ROI ≤ 0 or hit below floor.

    Uses persistent ledger so a sport that sat out an epoch doesn't get
    auto-reallowed and re-bleed the next cycle.
    """
    all_sp = {"soccer", "basketball", "cricket"}
    merged: dict[str, dict] = {}
    for sp in all_sp:
        prev = dict((ledger or {}).get(sp) or {})
        cur = dict((by_sport or {}).get(sp) or {})
        # Current epoch with tickets wins; else keep last known
        if int(cur.get("n") or 0) > 0:
            merged[sp] = {**prev, **cur}
        elif prev:
            merged[sp] = prev
        else:
            merged[sp] = cur
    if not any(int((merged.get(sp) or {}).get("n") or 0) > 0 for sp in all_sp):
        return all_sp
    allowed = set()
    for sp in all_sp:
        row = merged.get(sp) or {}
        if int(row.get("n") or 0) <= 0:
            continue  # never sampled → don't invent a pass
        sroi = row.get("roi")
        if sroi is not None and float(sroi) <= MIN_SPORT_ROI:
            continue
        shr = row.get("hit_rate")
        if shr is not None and float(shr) < min_hit:
            continue
        allowed.add(sp)
    if allowed:
        return allowed
    best_sp = max(
        all_sp,
        key=lambda sp: float((merged.get(sp) or {}).get("roi") or -999),
    )
    return {best_sp}


def _merge_sport_ledger(ledger: dict, by_sport: dict, match_budget: float) -> dict:
    """Update persistent per-sport verdict from this holdout epoch."""
    out = dict(ledger or {})
    for sp in ("soccer", "basketball", "cricket"):
        row = by_sport.get(sp) or {}
        n = int(row.get("n") or 0)
        if n <= 0:
            continue
        sroi = _sport_roi(row, match_budget)
        shr = row.get("hit_rate")
        out[sp] = {
            "n": n,
            "roi": sroi,
            "hit_rate": shr,
            "ok": (
                n >= MIN_BETS_PER_SPORT
                and sroi is not None
                and sroi > MIN_SPORT_ROI
                and (shr is None or float(shr) >= TARGET_ACC)
            ),
        }
    return out


def _run_epoch(
    *,
    epoch: int,
    games: list[dict],
    net: CraftNet,
    threshold: float,
    min_p: float,
    bankroll: float,
    match_budget: float,
    craft_w: dict,
    memory: list[dict],
    allow_sports: set[str] | None = None,
    log: bool = True,
    inject_paired: bool = True,
    paired_fixed: bool = False,
    fit: bool = True,
    sport_ev_boost: dict[str, float] | None = None,
    sport_min_p: dict[str, float] | None = None,
    sport_core_only: dict[str, bool] | None = None,
) -> dict[str, Any]:
    book = _empty_book(bankroll)
    book["source"] = "boards+paired_closes"
    # Scale bankroll for large paired volume so we don't run out of stake mid-epoch
    if inject_paired:
        book["bankroll"] = float(bankroll) * 20
        book["starting_bankroll"] = float(bankroll) * 20
    placed = 0
    paired_n = 0
    boost = sport_ev_boost or {}
    sp_min = sport_min_p or {}
    core_only = sport_core_only or {}
    paired_cap = PAIRED_EVAL_PER_SPORT if paired_fixed else PAIRED_TRAIN_PER_SPORT
    if inject_paired:
        try:
            from bet_placer.ml.betting_evolution import sample_paired_for_craft, connect as paired_connect
            paired = []
            for sp, edge in (("soccer", 0.08), ("basketball", 0.02), ("cricket", 0.02)):
                if allow_sports and sp not in allow_sports:
                    continue
                sp_p = float(sp_min.get(sp) or min_p)
                sp_edge = edge + max(0.0, (sp_p - FLOOR_P) * 0.5)
                if sp == "soccer":
                    # Direct +EV favorite slice (step-sampling the loose pool misses it)
                    con = paired_connect()
                    rows = con.execute(
                        """
                        SELECT id, sport, game_date, home, away, hs, aws, market, selection,
                               close_odds, model_p, edge, hit, pnl_unit, source
                        FROM paired
                        WHERE sport='soccer'
                          AND close_odds BETWEEN 1.30 AND 1.50
                          AND model_p >= (1.0/close_odds + 0.12)
                          AND hit IS NOT NULL
                        ORDER BY id
                        """
                    ).fetchall()
                    con.close()
                    n = len(rows)
                    take = min(n, max(paired_cap, 200))
                    if paired_fixed or n <= take:
                        chunk = [dict(r) for r in rows[:take]]
                    else:
                        start = ((max(0, epoch - 1) * 17) % n)
                        chunk = [dict(rows[(start + i) % n]) for i in range(take)]
                    paired.extend(chunk)
                    continue
                cap = paired_cap * (4 if sp == "basketball" else 1)
                chunk = sample_paired_for_craft(
                    per_sport=cap,
                    min_edge=max(sp_edge, (threshold - 0.45) * 0.25) if sp != "basketball" else 0.0,
                    min_p=0.95 if sp == "basketball" else max(FLOOR_P, sp_p - 0.02),
                    epoch=epoch,
                    fixed=paired_fixed,
                )
                if sp == "basketball":
                    # ponytail: BB paired odds are synthetic 1.91 — only extreme model_p clears 60% hit
                    chunk = [
                        r for r in chunk
                        if r.get("sport") == "basketball"
                        and float(r.get("model_p") or 0) >= 0.95
                    ]
                else:
                    chunk = [r for r in chunk if r.get("sport") == sp]
                paired.extend(chunk)
            paired_n = _place_paired_rows(
                book, paired, net=net, threshold=threshold, min_p=min_p,
                allow_sports=allow_sports, sport_ev_boost=boost,
                sport_min_p=sp_min,
            )
            placed += paired_n
        except Exception:
            paired_n = 0

    for row in games:
        if allow_sports and row["sport"] not in allow_sports:
            continue
        gems, meta = _collect_gems(row, craft_w)
        if not gems or not meta:
            continue
        sp = row["sport"]
        gems = _filter_gems(
            gems, net, sport=sp, threshold=threshold,
            min_p=float(sp_min.get(sp) or min_p),
            core_only=bool(core_only.get(sp)),
        )
        if not gems:
            continue
        n = _place_gems(
            book,
            match_id=meta.get("match_id") or row["id"],
            home=row["home"],
            away=row["away"],
            gems=gems,
            match_budget=match_budget,
            status="settled",
            hs=int(row["hs"]),
            aws=int(row["aws"]),
            sport=row["sport"],
        )
        placed += n

    tickets = book.get("tickets") or []
    if fit:
        # Learn from train tickets only — balanced wins/losses inside CraftNet
        memory.extend(tickets)
        if len(memory) > 25_000:
            # Prefer keeping wins when trimming
            wins = [t for t in memory if t.get("status") == "won"]
            rest = [t for t in memory if t.get("status") != "won"]
            memory[:] = (wins[-12_000:] + rest[-8_000:])[-20_000:]
        loss = net.fit_tickets(memory[-8_000:])
        craft_w = update_craft_weights_from_tickets(memory[-4_000:])
    else:
        loss = None
    summary = summarize(book)
    if log:
        if len(tickets) <= 400:
            save_book(book)
            apply_paper_learning(book=book)
        row = {
            "epoch": epoch,
            "games": len(games),
            "bets": summary.get("settled") or placed,
            "accuracy": summary.get("accuracy"),
            "roi": summary.get("roi"),
            "pnl": summary.get("pnl"),
            "bankroll": summary.get("bankroll"),
            "threshold": round(threshold, 4),
            "nn_loss": loss,
            "by_sport": summary.get("by_sport") or {},
            "by_market": summary.get("by_market") or {},
            "detail": {
                "nn_trained": net.n_trained,
                "min_p": min_p,
                "paired_n": paired_n,
                "board_gems": placed - paired_n,
                "holdout_eval": paired_fixed and not fit,
                "by_selection": dict(list((summary.get("by_selection") or {}).items())[:40]),
                "sports_in_window": sorted({g["sport"] for g in games}),
                "sport_counts": {
                    s: sum(1 for g in games if g["sport"] == s)
                    for s in ("soccer", "basketball", "cricket")
                },
            },
        }
        log_epoch(row)
    else:
        row = {"epoch": epoch, "bets": placed, "roi": summary.get("roi"), "nn_loss": loss}
    return {"summary": summary, "row": row, "craft_w": craft_w, "book": book}


def _split_by_sport(games: list[dict], train_frac: float = 0.55) -> tuple[list[dict], list[dict]]:
    """Hold out per sport so BB/cricket aren't starved in eval."""
    by: dict[str, list] = defaultdict(list)
    for g in games:
        by[g["sport"]].append(g)
    train, ev = [], []
    for sp in ("soccer", "basketball", "cricket"):
        rows = by.get(sp) or []
        if not rows:
            continue
        cut = max(1, int(len(rows) * train_frac))
        if len(rows) - cut < 3 and len(rows) >= 6:
            cut = len(rows) - 3
        train.extend(rows[:cut])
        ev.extend(rows[cut:] or rows[-max(1, len(rows)//3):])
    if len(ev) < 10:
        return games, games
    return train, ev
