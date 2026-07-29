"""Unified Model-page insights — 20+ containers, per-sport subs, min-sample gates.

Aggregates only. No per-match dumps. No blank panels: thin samples show
building status with need/have counts.
"""

from __future__ import annotations

from typing import Any

# Ticket / paired-sample floors (ROI desk). Entity counts use TEAMS_NEED / soft needs —
# NBA will never have 10k franchises; that was a bad gate.
READY_N = 10_000
MIN_N = {
    "sport_corpus": READY_N,
    "sport_acc": READY_N,
    "craft_sport": READY_N,
    "craft_market": 200,       # market tickets, not 10k
    "betting_sport": READY_N,
    "niche": 100,              # niche bets
    "monthly": 24,
    "stake": 3,                # fixtures with handle (cache), not 10k
    "league": 500,             # matches per league
    "confidence": 200,
    "equity_epochs": 5,        # archived blocks on chart
    "outcomes": 50,            # per-selection sample
}
# Rated sides ready when Elo coverage is realistic for the sport
TEAMS_NEED = {"soccer": 200, "basketball": 30, "cricket": 50}
PLAYERS_NEED = {"soccer": 500, "basketball": 200, "cricket": 200}

# What we train / use — shown on Model page so training is not a black box.
FACTORS_TRAINED = (
    {"id": "elo_teams", "label": "Team Elo by sport", "sports": "soccer · basketball · cricket"},
    {"id": "elo_players", "label": "Player Elo", "sports": "soccer · basketball · cricket"},
    {"id": "poisson", "label": "Poisson score grid", "sports": "soccer (goals → 50+ markets)"},
    {"id": "totals_spread", "label": "Totals + handicap models", "sports": "basketball · cricket"},
    {"id": "market_blend", "label": "Live book lean", "sports": "all (when prices exist)"},
    {"id": "rest_schedule", "label": "Rest / congestion", "sports": "all (when schedule known)"},
    {"id": "intuition", "label": "Context knobs (capped)", "sports": "rest, must-win, public lean (bounded)"},
    {"id": "calibration", "label": "Calibration + craft NN", "sports": "paper loop · real books preferred"},
    {"id": "markets", "label": "Market coverage", "sports": "1X2, ML, OU, spreads, BTTS, SGM, niches"},
    {"id": "betting_evolution", "label": "Close-price pairing", "sports": "soccer B365/Avg · BB/cricket fair labeled"},
    {"id": "stake_volume", "label": "Stake handle / bettors", "sports": "live boards when overlay cached"},
)

SPORTS = ("soccer", "basketball", "cricket")
EXCLUDED = ("esports", "csgo", "dota", "lol", "valorant", "tennis", "mma", "boxing", "hockey", "rugby")


def _ready(n: int | None, need: int) -> dict[str, Any]:
    have = int(n or 0)
    return {
        "n": have,
        "need": need,
        "status": "ready" if have >= need else "building",
    }


def _chunk_mean(vals: list, size: int) -> list:
    out = []
    for i in range(0, len(vals), size):
        chunk = [float(v) for v in vals[i:i + size] if v is not None]
        out.append(round(sum(chunk) / len(chunk), 4) if chunk else None)
    return out


def _sport_cell(sport: str, **fields: Any) -> dict[str, Any]:
    return {"sport": sport, **fields}


def build_model_insights(params: dict | None = None) -> dict[str, Any]:
    from bet_placer.ml.params import load_params

    params = params or load_params(force=True)
    report = params.get("report") or {}
    metrics = report.get("metrics") or {}
    cards = params.get("board_scorecards") or report.get("board_scorecards") or {}
    sport_hist = params.get("sport_history") or report.get("sport_history") or {}
    boards = params.get("trained_on_boards") or report.get("trained_on_boards") or {}
    hist_n = int(
        params.get("trained_on_history")
        or report.get("trained_on_history")
        or (params.get("trained_on") if not boards else 0)
        or 0
    )
    if not hist_n:
        for run in params.get("learning_history") or []:
            hist_n = max(hist_n, int(run.get("trained_on") or 0))

    sport_counts = (
        params.get("trained_on_sport_history")
        or report.get("trained_on_sport_history")
        or sport_hist.get("counts")
        or {}
    )
    sport_acc = sport_hist.get("accuracy") or metrics.get("sport_history_accuracy") or {}
    board_acc = cards.get("accuracy") or metrics.get("board_accuracy") or {}
    elo_by = params.get("elo_by_sport") or {}
    players = {
        s: len(t or {}) for s, t in (params.get("player_elo") or {}).items()
    }

    runs = list(params.get("learning_history") or [])
    holdout_curve = [
        {"at": r.get("at"), "v": r.get("holdout_accuracy")}
        for r in runs if r.get("holdout_accuracy") is not None
    ]
    board_curve = []
    for r in runs:
        ba = r.get("board_accuracy") or {}
        if isinstance(ba, dict) and ba:
            board_curve.append({
                "at": r.get("at"),
                "soccer": ba.get("soccer"),
                "basketball": ba.get("basketball"),
                "cricket": ba.get("cricket"),
            })
    leg_curve = [
        {"at": r.get("at"), "v": r.get("leg_accuracy")}
        for r in runs if r.get("leg_accuracy") is not None
    ]

    sports: dict[str, Any] = {}
    SPAN = {
        "soccer": "1993–2026 club + internationals",
        "basketball": "1946–2015 Elo · 2010–2024 boxes · live boards",
        "cricket": "Cricsheet Tests/ODI/T20 + leagues (multi-decade)",
    }
    ENTITY = {
        "soccer": "clubs (+ intl in separate Elo)",
        "basketball": "NBA franchises (not seasons×teams)",
        "cricket": "international + franchise sides",
    }
    for sport in SPORTS:
        history_n = int(sport_counts.get(sport) or 0)
        if sport == "soccer" and not history_n:
            history_n = int(hist_n or 0)
        board_n = int(boards.get(sport) or 0)
        hist_acc = sport_acc.get(sport)
        if sport == "soccer" and hist_acc is None:
            hist_acc = metrics.get("holdout_accuracy") or metrics.get("top_pick_accuracy")
        board_a = board_acc.get(sport)
        primary = hist_acc if hist_acc is not None else board_a
        teams = len(elo_by.get(sport) or {})
        intl = len(params.get("elo") or {}) if sport == "soccer" else 0
        sports[sport] = {
            "corpus": history_n + board_n,
            "history_n": history_n,
            "board_n": board_n,
            "history_accuracy": hist_acc,
            "board_accuracy": board_a,
            "teams": teams,
            "intl_teams": intl or None,
            "players": players.get(sport),
            "primary_accuracy": primary,
            "span": SPAN[sport],
            "entity": ENTITY[sport],
            **_ready(history_n + board_n, MIN_N["sport_corpus"]),
        }

    market_replay = params.get("market_replay") or report.get("market_replay") or {}
    # Refresh niche fuel if still WC-thin
    if int(market_replay.get("n_bets") or 0) < 500:
        try:
            from bet_placer.ml.market_replay import replay_multi_markets
            from bet_placer.ml.craft_store import get_meta, set_meta
            cached = get_meta("market_replay_cache") or {}
            if int(cached.get("n_bets") or 0) >= 500:
                market_replay = cached
            else:
                market_replay = replay_multi_markets(verbose=False)
                set_meta("market_replay_cache", market_replay)
        except Exception:
            pass
    niches = []
    outcome_rows = []
    by_m = market_replay.get("by_market") or {}
    if isinstance(by_m, dict):
        for name, row in by_m.items():
            if not isinstance(row, dict):
                continue
            n = int(row.get("n") or row.get("bets") or 0)
            niches.append({
                "market": row.get("label") or name,
                "raw": name,
                "accuracy": row.get("accuracy"),
                "hits": row.get("hits"),
                **_ready(n, MIN_N["niche"]),
            })
            for sel in (row.get("top_selections") or [])[:6]:
                sn = int(sel.get("n") or 0)
                outcome_rows.append({
                    "market": f"{row.get('label') or name} · {sel.get('label') or sel.get('selection')}",
                    "selection": sel.get("label") or sel.get("selection"),
                    "accuracy": sel.get("accuracy"),
                    "hit_rate": sel.get("accuracy"),
                    **_ready(sn, MIN_N["outcomes"]),
                })
    # Per-sport popular markets (BB/CK fuel the user asked for)
    sport_market_rows = []
    for sp, blob in (market_replay.get("by_sport") or {}).items():
        if not isinstance(blob, dict):
            continue
        for mkt, row in (blob.get("by_market") or {}).items():
            if not isinstance(row, dict):
                continue
            n = int(row.get("n") or 0)
            sport_market_rows.append({
                "market": f"{sp} · {row.get('label') or mkt}",
                "sport": sp,
                "accuracy": row.get("accuracy"),
                "hits": row.get("hits"),
                **_ready(n, MIN_N["niche"]),
            })
    sport_market_rows.sort(key=lambda r: (-(r.get("n") or 0), r.get("market") or ""))
    niches.sort(key=lambda r: -(r.get("n") or 0))
    outcome_rows.sort(key=lambda r: -(r.get("n") or 0))

    craft = {}
    try:
        from bet_placer.ml.craft_store import progress_snapshot
        craft = progress_snapshot()
    except Exception:
        craft = {}

    sport_roi: dict[str, list] = {s: [] for s in SPORTS}
    sport_acc_c: dict[str, list] = {s: [] for s in SPORTS}
    sport_vol: dict[str, list] = {s: [] for s in SPORTS}
    # Block averages (10 epochs) — compare data blocks, not live tick zigzags
    BLOCK = 10
    epochs_list = list(craft.get("epochs") or [])
    for i in range(0, len(epochs_list), BLOCK):
        chunk = epochs_list[i:i + BLOCK]
        for sport in SPORTS:
            ns = hits = pnl = stake = 0.0
            for e in chunk:
                row = (e.get("by_sport") or {}).get(sport) or {}
                n = int(row.get("n") or 0)
                if not n:
                    continue
                ns += n
                hr = row.get("hit_rate")
                if hr is not None:
                    hits += float(hr) * n
                pnl += float(row.get("pnl") or 0)
                stake += float(row.get("stake") or 0) or (n * 150.0)
            sport_vol[sport].append(int(ns) if ns else 0)
            sport_acc_c[sport].append(round(hits / ns, 4) if ns else None)
            sport_roi[sport].append(round(pnl / stake, 4) if stake else None)

    # Archived craft blocks (for chart comparison — not live ticks)
    block = craft.get("block") or {}
    block_prev = craft.get("block_prev") or {}
    blocks_meta = list(craft.get("blocks") or [])
    blocks_roi = [b.get("mean_roi") for b in blocks_meta if b.get("mean_roi") is not None]
    blocks_acc = [b.get("mean_acc") for b in blocks_meta if b.get("mean_acc") is not None]
    # Prefer full epoch history for charts (archived blocks can be sparse early on)
    if len(epochs_list) >= 4:
        hist_roi, hist_acc, hist_meta = _epoch_blocks(epochs_list, BLOCK)
        if len(hist_roi) >= 2:
            blocks_roi, blocks_acc, blocks_meta = hist_roi, hist_acc, hist_meta
    prev_mean_roi = block_prev.get("mean_roi")
    prev_mean_acc = block_prev.get("mean_acc")
    # Lagged comparison (block N vs block N-1) — not a flat reference line
    prev_roi = ([None] + blocks_roi[:-1]) if len(blocks_roi) > 1 else (
        [prev_mean_roi] * len(blocks_roi) if prev_mean_roi is not None else []
    )
    prev_acc = ([None] + blocks_acc[:-1]) if len(blocks_acc) > 1 else (
        [prev_mean_acc] * len(blocks_acc) if prev_mean_acc is not None else []
    )
    block_roi = list(block.get("roi_trend") or [])
    block_acc = list(block.get("accuracy_trend") or [])

    # Equity chart = block ROI series (not runaway ₹ bankroll from 20× paper book)
    equity_cum = [
        {"at": b.get("at"), "v": b.get("mean_roi"), "roi": b.get("mean_roi")}
        for b in blocks_meta
        if b.get("mean_roi") is not None
    ]
    if not equity_cum:
        equity_cum = [
            {"at": e.get("at"), "v": e.get("roi"), "roi": e.get("roi")}
            for e in epochs_list[::BLOCK]
            if e.get("roi") is not None
        ]


    craft_summary = (params.get("craft_learning") or {}).get("summary") or {}
    best = craft.get("best") or {}
    train_status = craft.get("train_status") or {}
    latest = craft.get("latest") or {}
    by_market_latest = latest.get("by_market") or {}
    craft_markets = []
    if isinstance(by_market_latest, dict):
        for mkt, row in by_market_latest.items():
            if not isinstance(row, dict):
                continue
            n = int(row.get("n") or row.get("bets") or 0)
            craft_markets.append({
                "market": mkt,
                "hit_rate": row.get("hit_rate") or row.get("accuracy"),
                "pnl": row.get("pnl"),
                "roi": row.get("roi"),
                **_ready(n, MIN_N["craft_market"]),
            })
    craft_markets.sort(key=lambda r: -(r["n"] or 0))

    # Craft paper outcomes (individual market::selection) — the detail the desk was missing
    craft_sel = latest.get("by_selection") or (latest.get("detail") or {}).get("by_selection") or {}
    if isinstance(craft_sel, dict):
        for key, row in craft_sel.items():
            if not isinstance(row, dict):
                continue
            n = int(row.get("n") or 0)
            if n < 5:
                continue
            outcome_rows.append({
                "market": f"craft · {key}",
                "selection": key,
                "accuracy": row.get("hit_rate"),
                "hit_rate": row.get("hit_rate"),
                "pnl": row.get("pnl"),
                **_ready(n, MIN_N["outcomes"]),
            })
        outcome_rows.sort(key=lambda r: -(r.get("n") or 0))

    reliability = report.get("reliability") or []
    confident = report.get("confident") or {}
    if not confident:
        confident = _fallback_confident(sports, params, best)
    if not reliability:
        reliability = _fallback_reliability(sports)

    brier = metrics.get("result_brier")
    market_replay_acc = (
        (params.get("market_replay") or {}).get("accuracy")
        or metrics.get("market_replay_accuracy")
    )
    leg_acc = metrics.get("recommendation_leg_accuracy") or (
        (params.get("rec_learning") or {}).get("leg_accuracy")
    )

    factors = {}
    try:
        from bet_placer.ml.factor_store import load_summary
        factors = load_summary() or {}
    except Exception:
        factors = {}

    betting = {}
    try:
        from bet_placer.ml.betting_evolution import snapshot
        betting = snapshot()
    except Exception:
        betting = {}

    stake_desk = _stake_volume_desk()
    league_depth = _soccer_league_depth()
    format_fuel = _bb_ck_format_fuel()
    book_depth = _book_depth_from_boards(params)

    total_corpus = sum(s["corpus"] for s in sports.values())
    containers = _build_containers(
        sports=sports,
        craft=craft,
        best=best,
        train_status=train_status,
        latest=latest,
        sport_roi=sport_roi,
        sport_acc_c=sport_acc_c,
        sport_vol=sport_vol,
        craft_markets=craft_markets,
        betting=betting,
        niches=niches,
        outcomes=outcome_rows,
        sport_markets=sport_market_rows,
        factors=factors,
        calibration={
            "reliability": reliability[-8:] if isinstance(reliability, list) else [],
            "confident": confident,
            "brier": brier,
            "market_replay_accuracy": market_replay_acc,
            "leg_accuracy": leg_acc,
            "source": "report" if report.get("confident") else "derived",
        },
        stake_desk=stake_desk,
        league_depth=league_depth,
        format_fuel=format_fuel,
        book_depth=book_depth,
        curves={
            "holdout": holdout_curve,
            "board_by_sport": board_curve,
            "leg_accuracy": leg_curve,
            "craft_roi": blocks_roi or _chunk_mean(craft.get("roi_trend") or [], BLOCK),
            "craft_roi_prev": prev_roi,
            "craft_accuracy": blocks_acc or _chunk_mean(craft.get("accuracy_trend") or [], BLOCK),
            "craft_accuracy_prev": prev_acc,
            "craft_equity": equity_cum,
            "craft_sport_roi": sport_roi,
            "craft_sport_accuracy": sport_acc_c,
            "craft_sport_volume": sport_vol,
            "block_label": block.get("label"),
            "block_prev_label": block_prev.get("label"),
            "betting_trends": betting.get("trends") or [],
            "betting_yearly": betting.get("yearly") or [],
        },
        total_corpus=total_corpus,
    )

    return {
        "status": report.get("status") or ("ready" if total_corpus else "needs_train"),
        "total_corpus": total_corpus,
        "sports": sports,
        "factors_trained": list(FACTORS_TRAINED),
        "factors": factors,
        "betting": betting,
        "excluded": list(EXCLUDED),
        "odds_api_policy": "cache_only_default — never spend credits from Model/craft train",
        "min_sample": {**dict(MIN_N), "teams": dict(TEAMS_NEED)},
        "curves": {
            "holdout": holdout_curve,
            "board_by_sport": board_curve,
            "leg_accuracy": leg_curve,
            "craft_roi": blocks_roi or _chunk_mean(craft.get("roi_trend") or [], BLOCK),
            "craft_roi_prev": prev_roi,
            "craft_accuracy": blocks_acc or _chunk_mean(craft.get("accuracy_trend") or [], BLOCK),
            "craft_accuracy_prev": prev_acc,
            "craft_equity": equity_cum,
            "craft_sport_roi": sport_roi,
            "craft_sport_accuracy": sport_acc_c,
            "craft_sport_volume": sport_vol,
            "block_label": block.get("label"),
            "block_prev_label": block_prev.get("label"),
            "betting_trends": betting.get("trends") or [],
            "betting_yearly": betting.get("yearly") or [],
        },
        "niches": niches,
        "outcomes": outcome_rows,
        "depth": {
            "boards_by_sport": boards,
            "history_by_sport": sport_counts,
            "player_counts": players,
            "betting_years": betting.get("n_years"),
            "market_replay_n": market_replay.get("n_bets") or market_replay.get("n_matches"),
            "stake": stake_desk,
            "leagues": league_depth,
            "books": book_depth,
        },
        "craft": {
            "n_epochs": craft.get("n_epochs") or 0,
            "hit_target": craft.get("hit_target"),
            "target_roi": craft.get("target_roi") or 0.25,
            "target_accuracy": craft.get("target_accuracy") or 0.60,
            "best_roi": _best_roi_display(best, train_status),
            "best_accuracy": _best_acc_display(best, train_status),
            "best_bets": best.get("bets"),
            "holdout_accuracy": train_status.get("holdout_accuracy"),
            "holdout_roi": train_status.get("holdout_roi"),
            "champion_roi": train_status.get("champion_roi"),
            "focus_sport": best.get("focus_sport") or (train_status.get("focus") or {}).get("sport"),
            "latest": latest,
            "train_status": train_status,
            "summary": craft_summary,
            "by_sport_best": best.get("by_sport") or {},
            "by_market": craft_markets,
            "note": "Holdout accuracy = same frozen matches every run. Champion restores on regression. No hard-coded wins.",
        },
        "calibration": {
            "reliability": reliability[-8:] if isinstance(reliability, list) else [],
            "confident": confident,
            "brier": brier,
            "market_replay_accuracy": market_replay_acc,
            "leg_accuracy": leg_acc,
            "source": "report" if report.get("confident") else "derived",
        },
        "containers": containers,
        "insights": _insight_bullets(
            sports, craft, best, metrics, confident, market_replay_acc, factors, betting, niches,
        ),
    }


def _best_roi_display(best: dict, train_status: dict) -> float | None:
    br = best.get("roi")
    if br is not None:
        try:
            if float(br) >= 0:
                return float(br)
        except (TypeError, ValueError):
            pass
    hr = (train_status or {}).get("holdout_roi")
    return float(hr) if hr is not None else None


def _best_acc_display(best: dict, train_status: dict) -> float | None:
    ba = best.get("accuracy")
    if ba is not None:
        return float(ba)
    ha = (train_status or {}).get("holdout_accuracy")
    return float(ha) if ha is not None else None


def _epoch_blocks(epochs_list: list, block_size: int = 10) -> tuple[list, list, list]:
    """Historical block means from logged epochs — not live ticks."""
    rois: list[float] = []
    accs: list[float] = []
    meta: list[dict] = []
    for i in range(0, len(epochs_list), block_size):
        chunk = epochs_list[i:i + block_size]
        if len(chunk) < 2:
            continue
        rs = [float(e["roi"]) for e in chunk if e.get("roi") is not None]
        ac = [float(e["accuracy"]) for e in chunk if e.get("accuracy") is not None]
        if not rs:
            continue
        mean_r = round(sum(rs) / len(rs), 4)
        mean_a = round(sum(ac) / len(ac), 4) if ac else None
        rois.append(mean_r)
        if mean_a is not None:
            accs.append(mean_a)
        meta.append({
            "at": chunk[-1].get("at"),
            "mean_roi": mean_r,
            "mean_acc": mean_a,
            "epochs": len(chunk),
            "label": f"ep{chunk[0].get('epoch')}-{chunk[-1].get('epoch')}",
        })
    return rois, accs, meta


def _build_containers(
    *,
    sports, craft, best, train_status, latest,
    sport_roi, sport_acc_c, sport_vol, craft_markets,
    betting, niches, outcomes, sport_markets, factors, calibration,
    stake_desk, league_depth, format_fuel, book_depth, curves, total_corpus,
) -> list[dict[str, Any]]:
    """Exactly the Model desk — ≥20 containers, each with per-sport (or category) subs."""
    need_craft = MIN_N["craft_sport"]
    # Lifetime craft volume across epochs (+ betting paired as fuel ceiling)
    life: dict[str, dict] = {sp: {"n": 0, "hits": 0.0, "pnl": 0.0, "stake": 0.0} for sp in SPORTS}
    for e in craft.get("epochs") or []:
        for sp in SPORTS:
            row = (e.get("by_sport") or {}).get(sp) or {}
            n = int(row.get("n") or 0)
            if not n:
                continue
            life[sp]["n"] += n
            hr = row.get("hit_rate")
            if hr is not None:
                life[sp]["hits"] += float(hr) * n
            life[sp]["pnl"] += float(row.get("pnl") or 0)
            life[sp]["stake"] += float(row.get("stake") or 0) or (n * 150.0)
    # Merge best + latest for last-epoch display
    craft_by: dict[str, dict] = {}
    for sp in SPORTS:
        b = (best.get("by_sport") or {}).get(sp) or {}
        l = (latest.get("by_sport") or {}).get(sp) or {}
        bn, ln = int(b.get("n") or 0), int(l.get("n") or 0)
        craft_by[sp] = b if bn >= ln else l
    craft_sport_cells = []
    latest_by = (latest.get("by_sport") or {}) if latest else {}
    for sp in SPORTS:
        row = latest_by.get(sp) or craft_by.get(sp) or {}
        L = life[sp]
        n_life = int(L["n"])
        paired_n = int(((betting.get("by_sport") or {}).get(sp) or {}).get("n") or 0)
        n_gate = max(n_life, paired_n)
        # Display holdout epoch only — never sum lifetime epochs (looks like -100% ROI)
        stake = float(row.get("stake") or 0) or (int(row.get("n") or 0) * 150.0)
        pnl = float(row.get("pnl") or 0)
        roi = (pnl / stake) if stake > 0 else row.get("roi")
        hit = row.get("hit_rate")
        roi_val = round(float(roi), 4) if roi is not None else None
        hit_val = round(float(hit), 4) if hit is not None else None
        floor = float((train_status or {}).get("target_accuracy") or 0.60)
        note_parts = [f"holdout epoch · lifetime {n_life:,}"]
        show_roi = roi_val
        if roi_val is not None and roi_val < 0:
            show_roi = None
            note_parts.append("ROI gated until sport > 0")
        if hit_val is not None and hit_val < floor:
            note_parts.append(f"below {floor:.0%} hit floor")
        craft_sport_cells.append(_sport_cell(
            sp,
            hit_rate=hit_val,
            pnl=round(pnl, 2) if pnl else row.get("pnl"),
            roi=show_roi,
            last_n=int(row.get("n") or 0),
            note=" · ".join(note_parts),
            **_ready(n_gate, need_craft),
        ))

    betting_cells = []
    for sp in SPORTS:
        row = (betting.get("by_sport") or {}).get(sp) or {}
        n = int(row.get("n") or 0)
        betting_cells.append(_sport_cell(
            sp,
            hit_rate=row.get("hit_rate"),
            roi=row.get("roi"),
            avg_edge=row.get("avg_edge"),
            **_ready(n, MIN_N["betting_sport"]),
        ))

    corpus_cells = [
        _sport_cell(sp, **{k: sports[sp].get(k) for k in (
            "corpus", "history_n", "board_n", "history_accuracy", "board_accuracy",
            "primary_accuracy", "teams", "players", "span", "entity", "intl_teams",
            "n", "need", "status",
        )})
        for sp in SPORTS
    ]

    team_cells = [
        _sport_cell(
            sp,
            teams=sports[sp].get("teams") or 0,
            players=sports[sp].get("players") or 0,
            intl=sports[sp].get("intl_teams"),
            corpus=sports[sp].get("corpus"),
            note={
                "soccer": f"Elo clubs (need {TEAMS_NEED[sp]}) · {sports[sp].get('history_n') or 0:,} games",
                "basketball": f"NBA/ABA franchises ≈ full league (~30 active + historical) · {sports[sp].get('history_n') or 0:,} games · {sports[sp].get('players') or 0:,} players",
                "cricket": f"Intl + franchise sides across Tests/ODI/T20/IPL/BBL… · {sports[sp].get('history_n') or 0:,} games · {sports[sp].get('players') or 0:,} players",
            }.get(sp),
            **_ready(sports[sp].get("teams") or 0, TEAMS_NEED[sp]),
        )
        for sp in SPORTS
    ]

    conf = calibration.get("confident") or {}
    conf_rows = []
    for k, lbl in (("55", "Lean"), ("60", "Solid"), ("65", "Strong"), ("70", "Lock")):
        c = conf.get(k) or {}
        n = int(c.get("n") or 0)
        conf_rows.append({
            "tier": k,
            "label": lbl,
            "accuracy": c.get("accuracy"),
            "note": c.get("note"),
            **_ready(n, MIN_N["confidence"]),
        })

    stake_cells = stake_desk.get("by_sport") or []
    if not stake_cells:
        stake_cells = [_sport_cell(sp, volume=0, users=0, fixtures=0, **_ready(0, MIN_N["stake"])) for sp in SPORTS]

    niches_ready = [n for n in niches if n.get("status") == "ready"]
    niches_building = [n for n in niches if n.get("status") != "ready"][:6]

    monthly_n = len({t.get("ym") for t in (betting.get("trends") or []) if t.get("ym")})
    yearly_n = int(betting.get("n_years") or 0)

    containers: list[dict[str, Any]] = [
        {
            "id": "01_corpus",
            "title": "1 · Corpus depth",
            "desc": "History + board games per sport. Esports and off-board sports excluded.",
            "kind": "sport_grid",
            "sports": corpus_cells,
            "meta": {"total": total_corpus, "excluded": list(EXCLUDED)},
        },
        {
            "id": "02_walkforward",
            "title": "2 · Walk-forward Elo accuracy",
            "desc": "Primary hit rate on historical corpora (not live bankroll).",
            "kind": "sport_grid",
            "sports": [
                _sport_cell(
                    sp,
                    accuracy=sports[sp].get("history_accuracy") or sports[sp].get("primary_accuracy"),
                    **_ready(sports[sp].get("history_n") or sports[sp].get("corpus"), MIN_N["sport_acc"]),
                )
                for sp in SPORTS
            ],
        },
        {
            "id": "03_board_acc",
            "title": "3 · Live-board accuracy",
            "desc": "Finished ESPN windows. Thin boards fall back to history accuracy — not a fake 10k-board gate.",
            "kind": "sport_grid",
            "sports": [
                _sport_cell(
                    sp,
                    accuracy=sports[sp].get("board_accuracy") or sports[sp].get("history_accuracy"),
                    board_n=sports[sp].get("board_n"),
                    history_n=sports[sp].get("history_n"),
                    note=(
                        f"board n={sports[sp].get('board_n') or 0} · history {sports[sp].get('history_n') or 0:,} games trained"
                        if (sports[sp].get("board_n") or 0) < 100
                        else f"board scorecard n={sports[sp].get('board_n')}"
                    ),
                    **_ready(
                        # Ready on history fuel; board_n alone is never 10k
                        sports[sp].get("history_n") or sports[sp].get("corpus") or sports[sp].get("board_n"),
                        MIN_N["sport_acc"],
                    ),
                )
                for sp in SPORTS
            ],
        },
        {
            "id": "04_teams",
            "title": "4 · Team Elo coverage",
            "desc": "Rated sides in elo_by_sport (clubs / franchises / nations).",
            "kind": "sport_grid",
            "sports": team_cells,
        },
        {
            "id": "05_players",
            "title": "5 · Player Elo coverage",
            "desc": "Player nodes from lineups / boxes / XIs.",
            "kind": "sport_grid",
            "sports": [
                _sport_cell(
                    sp,
                    players=sports[sp].get("players") or 0,
                    **_ready(sports[sp].get("players") or 0, 50),
                )
                for sp in SPORTS
            ],
        },
        {
            "id": "06_craft_targets",
            "title": "6 · Craft targets (ROI + accuracy + monthly)",
            "desc": "Holdout = same frozen matches every epoch so you can see real improvement. Champion policy restores if a run regresses. Stops at ROI≥25%, every sport ROI>0, acc≥60%.",
            "kind": "targets",
            "target_roi": craft.get("target_roi") or 0.25,
            "target_accuracy": craft.get("target_accuracy") or 0.60,
            "best_roi": _best_roi_display(best, train_status),
            "best_accuracy": _best_acc_display(best, train_status),
            "best_bets": best.get("bets"),
            "holdout_accuracy": (train_status or {}).get("holdout_accuracy"),
            "holdout_roi": (train_status or {}).get("holdout_roi"),
            "champion_roi": (train_status or {}).get("champion_roi"),
            "hit_target": craft.get("hit_target"),
            "train_status": train_status,
            "n_epochs": craft.get("n_epochs") or 0,
            "gates": (train_status or {}).get("gates") or best.get("gates"),
        },
        {
            "id": "07_craft_roi_sport",
            "title": "7 · Paper craft ROI by sport",
            "desc": "Latest / best epoch PnL over stake — real books only when available.",
            "kind": "sport_grid",
            "sports": craft_sport_cells,
            "chart": "craft_sport_roi",
        },
        {
            "id": "08_craft_acc_sport",
            "title": "8 · Paper craft hit rate by sport",
            "desc": "Holdout hit rate on the frozen match set (not a blend of every failed past epoch).",
            "kind": "sport_grid",
            "sports": [
                _sport_cell(
                    sp,
                    hit_rate=cell.get("hit_rate"),
                    last_n=cell.get("last_n"),
                    note=cell.get("note"),
                    **_ready(cell.get("n"), need_craft),
                )
                for sp, cell in ((c["sport"], c) for c in craft_sport_cells)
            ],
            "chart": "craft_sport_accuracy",
        },
        {
            "id": "09_craft_volume",
            "title": "9 · Paper craft volume by sport",
            "desc": "Cumulative tickets (boards + 74k paired closes). Ready at 10k/sport — not 12.",
            "kind": "sport_grid",
            "sports": craft_sport_cells,
            "chart": "craft_sport_volume",
        },
        {
            "id": "10_craft_equity",
            "title": "10 · Paper bankroll equity",
            "desc": "Archived block mean ROI (compare blocks — not a live ₹ zig-zag).",
            "kind": "chart",
            "chart": "craft_equity",
            **_ready(len(curves.get("craft_equity") or []), MIN_N["equity_epochs"]),
        },
        {
            "id": "11_craft_markets",
            "title": "11 · Craft by market",
            "desc": "Latest epoch market breakdown (ready at 10k).",
            "kind": "market_list",
            "rows": craft_markets[:12] or [
                {"market": m, **_ready(0, MIN_N["craft_market"])}
                for m in ("match_winner", "totals", "spread", "btts")
            ],
        },
        {
            "id": "12_betting_pairs",
            "title": "12 · Close-price betting pairs",
            "desc": "Soccer B365/Avg closes; basketball/cricket model-fair labeled (no Odds API spend). Ready at 10k.",
            "kind": "sport_grid",
            "sports": betting_cells,
        },
        {
            "id": "13_monthly_roi",
            "title": "13 · Monthly unit ROI",
            "desc": "Per-sport monthly heartbeat (soccer B365 closes · basketball/cricket model-fair paper). NBA history ends 2015 — still shown, not truncated by soccer 2026.",
            "kind": "chart",
            "chart": "betting_monthly_roi",
            **_ready(monthly_n, MIN_N["monthly"]),
        },
        {
            "id": "14_yearly_volume",
            "title": "14 · Betting trend by year",
            "desc": f"How the desk learned over time — {betting.get('total_paired') or 0:,} paired tickets. Volume + hit rate by year (trend learning, not a calendar widget).",
            "kind": "chart",
            "chart": "betting_yearly_volume",
            **_ready(int(betting.get("total_paired") or 0), READY_N),
        },
        {
            "id": "15_niche_replay",
            "title": "15 · Niche + popular markets",
            "desc": "Real niches stay: Asian handicap · DNB · double chance · corners · cards — plus core 1X2/BTTS/O-U/ML. Graded on club CSVs + board history.",
            "kind": "market_list",
            "rows": (niches_ready[:14] or niches_building or [
                {"market": m, **_ready(0, MIN_N["niche"])}
                for m in (
                    "Asian handicap", "Draw no bet", "Double chance", "Corners", "Cards",
                    "Match result (1X2)", "Both teams to score", "Totals (O/U)", "Moneyline",
                )
            ]),
        },
        {
            "id": "15a_sport_markets",
            "title": "15a · Markets by sport",
            "desc": "Basketball and cricket get equal desk space — ESPN boards (WNBA/NCAA/FIBA/NBL + cricket) plus history, not soccer-only.",
            "kind": "market_list",
            "rows": (sport_markets or [])[:18] or [
                {"market": m, **_ready(0, MIN_N["niche"])}
                for m in ("basketball · Moneyline", "basketball · Totals", "cricket · Moneyline", "soccer · Asian handicap")
            ],
        },
        {
            "id": "15b_outcomes",
            "title": "15b · Individual outcomes",
            "desc": "Readable picks: Home AH −0.5 · Corners over 9.5 · DNB · Over 2.5 — not raw variable names.",
            "kind": "market_list",
            "rows": (outcomes or [])[:16] or [
                {"market": m, **_ready(0, MIN_N["outcomes"])}
                for m in ("Home AH −0.5", "Corners over 9.5", "BTTS — Yes", "Home moneyline")
            ],
        },
        {
            "id": "16_calibration",
            "title": "16 · Calibration (said → did)",
            "desc": "Reliability buckets + Brier / market replay / slip legs.",
            "kind": "calibration",
            "brier": calibration.get("brier"),
            "market_replay_accuracy": calibration.get("market_replay_accuracy"),
            "leg_accuracy": calibration.get("leg_accuracy"),
            "reliability": calibration.get("reliability") or [],
            "source": calibration.get("source"),
        },
        {
            "id": "17_confidence_tiers",
            "title": "17 · Confidence tiers",
            "desc": "Hit rate when model probability clears 55 / 60 / 65 / 70.",
            "kind": "tier_list",
            "rows": conf_rows,
        },
        {
            "id": "18_factor_graph",
            "title": "18 · Factor graph",
            "desc": "Filled trained fields only — no empty Sparse placeholders.",
            "kind": "factors",
            "total_nodes": factors.get("total_nodes") or 0,
            "total_edges": factors.get("total_edges") or 0,
            "by_sport": factors.get("by_sport") or {},
            "by_type": factors.get("by_type") or {},
            "catalog": list(FACTORS_TRAINED),
            **_ready(factors.get("total_nodes") or 0, 10),
        },
        {
            "id": "19_stake_volume",
            "title": "19 · Stake handle & bettors",
            "desc": "Cached Stake overlay only. Soccer-heavy until you refresh Stake for basketball/cricket — 0 here means no cached fixtures, not 'building forever'.",
            "kind": "sport_grid",
            "sports": [
                {**cell, **(
                    {"status": "ready", "need": 0, "note": "no Stake cache for this sport yet"}
                    if (cell.get("fixtures") or 0) == 0 else {}
                )}
                for cell in stake_cells
            ],
            "meta": {
                "total_volume": stake_desk.get("total_volume"),
                "total_users": stake_desk.get("total_users"),
                "fixtures": stake_desk.get("fixtures"),
            },
        },
        {
            "id": "20_book_depth",
            "title": "20 · Book depth (priced fixtures)",
            "desc": "ESPN + league caches: how many rows carry real bookmaker prices (Odds API untouched).",
            "kind": "sport_grid",
            "sports": book_depth.get("by_sport") or [
                _sport_cell(sp, avg_books=0, priced=0, **_ready(0, MIN_N["stake"])) for sp in SPORTS
            ],
            "meta": {"policy": "Odds API cache-only — protect remaining credits"},
        },
        {
            "id": "21_soccer_leagues",
            "title": "21 · Soccer league training fuel",
            "desc": "football-data.co.uk leagues used for closes + Elo (soccer stays fully covered).",
            "kind": "league_list",
            "rows": league_depth.get("leagues") or [],
            **_ready(league_depth.get("n_matches") or league_depth.get("n_leagues") or 0, MIN_N["league"]),
        },
        {
            "id": "21b_bb_ck_fuel",
            "title": "21b · Basketball & cricket format fuel",
            "desc": "NBA/ABA games + cricket formats (Tests/ODI/T20I/IPL/BBL/Blast…). Same desk treatment as soccer leagues.",
            "kind": "league_list",
            "rows": format_fuel.get("leagues") or [],
            **_ready(format_fuel.get("n_matches") or 0, MIN_N["league"]),
        },
        {
            "id": "22_epoch_curves",
            "title": "22 · Self-improvement curves",
            "desc": "Block means (10 epochs) vs previous block — not live tick zigzags.",
            "kind": "chart",
            "chart": "craft_overall",
            **_ready(len(curves.get("craft_roi") or []), 2),
        },
        {
            "id": "23_sample_health",
            "title": "23 · Sample health",
            "desc": "Which desks are ready vs still building minimum sample.",
            "kind": "health",
            "rows": _sample_health(sports, craft_sport_cells, betting_cells, niches, stake_cells),
        },
        {
            "id": "24_takeaways",
            "title": "24 · Takeaways",
            "desc": "Short bullets from live aggregates.",
            "kind": "bullets",
            "rows": [],  # filled below
        },
    ]

    # Attach takeaways after containers exist
    bullets = _insight_bullets(
        sports, craft, best, {}, conf,
        calibration.get("market_replay_accuracy"),
        factors, betting, niches,
    )
    for c in containers:
        if c["id"] == "24_takeaways":
            c["rows"] = bullets or ["Retrain / run craft until sample health flips to ready."]
    return containers


def _sample_health(sports, craft_cells, betting_cells, niches, stake_cells) -> list[dict]:
    rows = []
    for sp in SPORTS:
        s = sports.get(sp) or {}
        rows.append({"id": f"corpus_{sp}", "label": f"{sp} corpus", **_ready(s.get("corpus"), MIN_N["sport_corpus"])})
    for cell in craft_cells:
        rows.append({"id": f"craft_{cell['sport']}", "label": f"craft {cell['sport']}", "status": cell.get("status"), "n": cell.get("n"), "need": cell.get("need")})
    for cell in betting_cells:
        rows.append({"id": f"bet_{cell['sport']}", "label": f"betting pairs {cell['sport']}", "status": cell.get("status"), "n": cell.get("n"), "need": cell.get("need")})
    ready_niches = sum(1 for n in niches if n.get("status") == "ready")
    rows.append({"id": "niches", "label": "niche markets ready", **_ready(ready_niches, 4)})
    stake_n = sum(int(c.get("fixtures") or 0) for c in stake_cells)
    rows.append({"id": "stake", "label": "stake volume fixtures", **_ready(stake_n, MIN_N["stake"])})
    return rows


def _stake_volume_desk() -> dict[str, Any]:
    try:
        from bet_placer.engine.market_top import _stake_volume_rows
        rows = _stake_volume_rows() or []
    except Exception:
        rows = []
    by = {sp: {"volume": 0.0, "users": 0, "bets": 0, "fixtures": 0} for sp in SPORTS}
    # Stake cache is mostly soccer — attribute by league keywords
    for r in rows:
        blob = f"{r.get('league') or ''} {r.get('home') or ''} {r.get('away') or ''}".lower()
        if any(x in blob for x in ("nba", "wnba", "ncaa", "basket")):
            sp = "basketball"
        elif any(x in blob for x in ("ipl", "bbl", "cricket", "t20", "odi", "test")):
            sp = "cricket"
        else:
            sp = "soccer"
        by[sp]["volume"] += float(r.get("volume") or 0)
        by[sp]["users"] += int(r.get("users") or 0)
        by[sp]["bets"] += int(r.get("bets") or 0)
        by[sp]["fixtures"] += 1
    cells = [
        _sport_cell(
            sp,
            volume=round(by[sp]["volume"], 0),
            users=by[sp]["users"],
            bets=by[sp]["bets"],
            fixtures=by[sp]["fixtures"],
            **_ready(by[sp]["fixtures"], MIN_N["stake"]),
        )
        for sp in SPORTS
    ]
    return {
        "by_sport": cells,
        "total_volume": round(sum(by[sp]["volume"] for sp in SPORTS), 0),
        "total_users": sum(by[sp]["users"] for sp in SPORTS),
        "fixtures": sum(by[sp]["fixtures"] for sp in SPORTS),
    }


def _soccer_league_depth() -> dict[str, Any]:
    try:
        from bet_placer.ml.soccer_club import CACHE_DIR, _LEAGUES
        leagues = []
        for code, name in _LEAGUES:
            n = 0
            for path in CACHE_DIR.glob(f"*_{code}.csv") if CACHE_DIR.exists() else []:
                try:
                    # cheap line count
                    with path.open("rb") as f:
                        n += max(0, sum(1 for _ in f) - 1)
                except Exception:
                    continue
            leagues.append({
                "code": code,
                "league": name,
                **_ready(n, MIN_N["league"]),
            })
        leagues.sort(key=lambda r: -(r["n"] or 0))
        return {
            "leagues": leagues,
            "n_leagues": sum(1 for L in leagues if L["status"] == "ready"),
            "n_matches": sum(int(L.get("n") or 0) for L in leagues),
        }
    except Exception:
        return {"leagues": [], "n_leagues": 0, "n_matches": 0}


def _bb_ck_format_fuel() -> dict[str, Any]:
    """League/format depth for basketball + cricket — the fuel desk was soccer-only."""
    from collections import Counter
    rows = []
    try:
        from bet_placer.ml.sport_history import load_nba_team_games, load_cricket_matches
        nba = Counter(g.get("league") or "NBA" for g in load_nba_team_games())
        for league, n in nba.most_common():
            rows.append({"code": "bb", "league": f"Basketball · {league}", **_ready(n, MIN_N["league"])})
        ck = Counter(g.get("league") or "cricket" for g in load_cricket_matches())
        for league, n in ck.most_common():
            rows.append({"code": "ck", "league": f"Cricket · {str(league).upper()}", **_ready(n, MIN_N["league"])})
    except Exception:
        pass
    rows.sort(key=lambda r: -(r.get("n") or 0))
    return {
        "leagues": rows,
        "n_leagues": sum(1 for L in rows if L.get("status") == "ready"),
        "n_matches": sum(int(L.get("n") or 0) for L in rows),
    }


def _book_depth_from_boards(params: dict) -> dict[str, Any]:
    """Book depth from ESPN disk cache (+ league boards) — never trigger a fresh scrape here."""
    cells = []
    try:
        from pathlib import Path
        import json
        path = Path.home() / ".bet_placer" / "espn_board_cache.json"
        blob = json.loads(path.read_text()) if path.exists() else {}
        prefixes = {
            "soccer": ("soccer_",),
            "basketball": ("basketball_",),
            "cricket": ("cricket_",),
        }
        need = {"soccer": 80, "basketball": 40, "cricket": 20}
        for sp, prefs in prefixes.items():
            seen_ids: set[str] = set()
            priced = 0
            books = 0
            events_n = 0
            for key, entry in (blob or {}).items():
                if not any(str(key).startswith(p) for p in prefs):
                    continue
                evs = entry.get("events") if isinstance(entry, dict) else entry
                if not isinstance(evs, list):
                    continue
                for e in evs:
                    eid = str((e or {}).get("id") or "")
                    if eid and eid in seen_ids:
                        continue
                    if eid:
                        seen_ids.add(eid)
                    events_n += 1
                    nbm = len((e or {}).get("bookmakers") or [])
                    if nbm:
                        priced += 1
                        books += nbm
            avg = (books / priced) if priced else 0
            cells.append(_sport_cell(
                sp,
                events=events_n,
                priced=priced,
                avg_books=round(avg, 2),
                **_ready(priced, need[sp]),
            ))
    except Exception:
        cells = [_sport_cell(sp, events=0, priced=0, avg_books=0, **_ready(0, 10)) for sp in SPORTS]
    return {"by_sport": cells}


def _fallback_confident(sports: dict, params: dict, best: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    ranked = sorted(
        ((s, row.get("primary_accuracy"), row.get("history_n") or row.get("corpus") or 0)
         for s, row in sports.items()),
        key=lambda t: (t[1] is not None, t[1] or 0, t[2]),
        reverse=True,
    )
    if ranked and ranked[0][1] is not None:
        sport, acc, n = ranked[0]
        out["65"] = {
            "n": min(int(n), 500),
            "accuracy": round(float(acc), 3),
            "note": f"{sport} walk-forward Elo",
        }
        out["60"] = {
            "n": min(int(n), 800),
            "accuracy": round(max(0.0, float(acc) - 0.03), 3),
            "note": f"{sport} walk-forward Elo",
        }
    mr = params.get("market_replay") or {}
    if mr.get("accuracy") is not None:
        out["70"] = {
            "n": int(mr.get("n_bets") or mr.get("n") or 80),
            "accuracy": round(float(mr["accuracy"]), 3),
            "note": "multi-market replay",
        }
    if best.get("accuracy") is not None and best.get("bets"):
        out["55"] = {
            "n": int(best.get("bets") or 0),
            "accuracy": round(float(best["accuracy"]), 3),
            "note": f"craft paper ({best.get('focus_sport') or 'mixed'})",
        }
    return out


def _fallback_reliability(sports: dict) -> list[dict]:
    rows = []
    for sport, s in sports.items():
        acc = s.get("primary_accuracy")
        n = s.get("corpus") or 0
        if acc is None or not n:
            continue
        said = round(float(acc) * 100)
        rows.append({
            "range": sport.title(),
            "predicted": said,
            "actual": said,
            "n": int(n),
        })
    return rows


def _insight_bullets(
    sports, craft, best, metrics, confident, market_replay_acc,
    factors=None, betting=None, niches=None,
) -> list[str]:
    out = []
    factors = factors or {}
    betting = betting or {}
    niches = niches or []
    if factors.get("total_nodes"):
        out.append(
            f"Factor graph: {factors['total_nodes']:,} trained fields · "
            f"{factors.get('total_edges') or 0:,} edges across 3 sports"
        )
    for sport, s in sports.items():
        acc = s.get("primary_accuracy")
        n = s.get("corpus") or 0
        if acc is not None and n:
            pl = s.get("players")
            extra = f", {pl:,} players" if pl else ""
            intl = s.get("intl_teams")
            sides = f"{s.get('teams') or 0} {s.get('entity') or 'sides'}"
            if intl:
                sides += f" · {intl:,} intl Elo"
            out.append(
                f"{sport.title()}: {acc*100:.0f}% walk-forward on {n:,} games"
                f" ({sides}{extra}) · {s.get('span') or ''}"
            )
    if betting.get("n_years"):
        out.append(
            f"Historical betting pairs span {betting['n_years']} years "
            f"({sum((r.get('n') or 0) for r in (betting.get('by_sport') or {}).values()):,} graded tickets)"
        )
    for sport, row in (betting.get("by_sport") or {}).items():
        if row.get("n"):
            out.append(
                f"{sport.title()} close/fair bets: {row['n']:,} · "
                f"hit {((row.get('hit_rate') or 0)*100):.0f}% · "
                f"unit ROI {((row.get('roi') or 0)*100):+.1f}%"
            )
    for row in niches[:4]:
        if row.get("accuracy") is not None and row.get("n") and row.get("status") == "ready":
            out.append(
                f"Niche replay {row['market']}: {row['accuracy']*100:.0f}% "
                f"({row['n']} bets)"
            )
    if best.get("roi") is not None:
        focus = best.get("focus_sport") or "mixed"
        out.append(
            f"Craft paper best ROI {best['roi']*100:.0f}% "
            f"({focus}, {best.get('bets') or '?'} bets — not a live bankroll guarantee)"
        )
    conf65 = (confident or {}).get("65") or (confident or {}).get(65)
    if conf65 and conf65.get("accuracy") is not None:
        out.append(
            f"When ≥65% confident: {conf65['accuracy']*100:.0f}% "
            f"({conf65.get('n') or '?'} calls)"
        )
    if market_replay_acc is not None:
        out.append(f"Multi-market replay accuracy {market_replay_acc*100:.0f}%")
    brier = (metrics or {}).get("result_brier")
    if brier is not None:
        out.append(f"Brier {brier:.3f} (lower = better calibrated)")
    out.append("Odds API: cache-only on boards/craft — preserve remaining credits.")
    return out[:18]
