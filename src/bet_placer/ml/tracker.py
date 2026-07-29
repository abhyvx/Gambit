"""Self-tracking model: compare predictions with real results, learn, improve.

What this does, end to end:
  1. For every FINISHED World Cup match, replay the raw pre-match model and grade
     it against the actual score (result / totals / BTTS).
  2. Score the model: Brier, log-loss, accuracy, and a reliability (calibration)
     curve — does "70%" actually happen ~70% of the time?
  3. Diagnose what it got wrong and which factors it mis-weighted (overall scoring
     level, home-field edge, over-confidence on favourites/longshots).
  4. LEARN: fit a calibration per market group + global corrections, save them,
     and the live prediction path picks them up automatically.

It also keeps a JSONL log of live predictions so future results extend the
training set beyond the games already played.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from bet_placer.ml.params import (
    DEFAULT_PARAMS,
    PARAMS_PATH,
    _logit,
    load_params,
    market_group,
    save_params,
)

LOG_PATH = PARAMS_PATH.parent / "predictions.jsonl"

# total-goals lines we grade against
_TOTAL_LINES = (1.5, 2.5, 3.5)


# --------------------------------------------------------------------------- #
# Prediction (raw model) for a single match
# --------------------------------------------------------------------------- #

def _match_pred(match, apply_learned: bool):
    from bet_placer.ml.poisson import expected_goals, rebalance_1x2, score_matrix
    from bet_placer.ml.params import calibrate_prob
    from bet_placer.data.team_ratings import TEAM_RATINGS, get_team_rating

    hl, al = expected_goals(match, apply_learned=apply_learned)
    M = score_matrix(hl, al, max_goals=10)
    H = np.arange(M.shape[0])[:, None]
    A = np.arange(M.shape[1])[None, :]
    tot = H + A

    p_home = float(M[H > A].sum())
    p_draw = float(M[H == A].sum())
    p_away = float(M[H < A].sum())
    gap = 20.0
    if match.home_team in TEAM_RATINGS and match.away_team in TEAM_RATINGS:
        gap = abs(get_team_rating(match.home_team) - get_team_rating(match.away_team))
    p_home, p_draw, p_away = rebalance_1x2(p_home, p_draw, p_away, rating_gap=gap)
    p_home = calibrate_prob(p_home, "match_winner", "home") or p_home
    p_draw = calibrate_prob(p_draw, "match_winner", "draw") or p_draw
    p_away = calibrate_prob(p_away, "match_winner", "away") or p_away
    s = p_home + p_draw + p_away
    if s > 0:
        p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s
    btts = 1.0 - float(M[0, :].sum()) - float(M[:, 0].sum()) + float(M[0, 0])

    events = [
        ("result", "home", p_home),
        ("result", "draw", p_draw),
        ("result", "away", p_away),
        ("btts", "yes", btts),
        ("btts", "no", 1 - btts),
    ]
    for ln in _TOTAL_LINES:
        over = float(M[tot > ln].sum())
        events.append(("totals", f"over_{ln}", over))
        events.append(("totals", f"under_{ln}", 1 - over))
    return hl, al, events


def _grade(selection: str, hs: int, aws: int) -> int:
    s = selection
    if s == "home":
        return int(hs > aws)
    if s == "draw":
        return int(hs == aws)
    if s == "away":
        return int(hs < aws)
    if s == "yes":
        return int(hs >= 1 and aws >= 1)
    if s == "no":
        return int(not (hs >= 1 and aws >= 1))
    if s.startswith("over_"):
        return int((hs + aws) > float(s.split("_")[1]))
    if s.startswith("under_"):
        return int((hs + aws) < float(s.split("_")[1]))
    return 0


# --------------------------------------------------------------------------- #
# Backtest dataset over finished matches
# --------------------------------------------------------------------------- #

def _finished_matches():
    from bet_placer.data.worldcup2026 import get_all_group_matches
    out = []
    for wc in get_all_group_matches():
        if wc.status == "completed" and wc.home_score is not None and wc.away_score is not None:
            out.append(wc)
    return out


def build_backtest(apply_learned: bool = False):
    """Returns (rows, matches) where rows are dicts: group,p,y,selection,match."""
    from bet_placer.engine.worldcup_pipeline import wc_match_to_analysis_match

    rows = []
    matches = []
    for wc in _finished_matches():
        try:
            m = wc_match_to_analysis_match(wc)
            hl, al, events = _match_pred(m, apply_learned=apply_learned)
        except Exception:
            continue
        hs, aws = int(wc.home_score), int(wc.away_score)
        top = max((e for e in events if e[0] == "result"), key=lambda e: e[2])
        matches.append({
            "match": f"{wc.home} {hs}-{aws} {wc.away}",
            "home": wc.home, "away": wc.away, "hs": hs, "as": aws,
            "pred_lambda": [round(hl, 2), round(al, 2)],
            "pred_total": round(hl + al, 2), "actual_total": hs + aws,
            "top_pick": top[1], "top_pick_p": round(top[2], 3),
            "top_pick_hit": bool(_grade(top[1], hs, aws)),
        })
        for grp, sel, p in events:
            rows.append({"group": grp, "selection": sel, "p": p,
                         "y": _grade(sel, hs, aws), "match": f"{wc.home}-{wc.away}"})
    return rows, matches


# --------------------------------------------------------------------------- #
# Live scorecard — how the model is calling REAL finished World Cup games,
# whether it's beating the bookmaker, and whether accuracy is trending up.
# --------------------------------------------------------------------------- #

def _result_of(hs: int, aws: int) -> str:
    return "home" if hs > aws else "away" if aws > hs else "draw"


def _conf_tier(p: float) -> str:
    if p >= 0.70:
        return "lock"
    if p >= 0.62:
        return "strong"
    if p >= 0.55:
        return "lean"
    return "coinflip"


def _market_fav(wc) -> str | None:
    odds = {"home": getattr(wc, "home_odds", 0), "draw": getattr(wc, "draw_odds", 0),
            "away": getattr(wc, "away_odds", 0)}
    odds = {k: v for k, v in odds.items() if v and v > 1.0}
    return min(odds, key=odds.get) if odds else None


_scorecard_body_cache: tuple[int, dict] | None = None


def _scorecard_body() -> dict:
    """Cached per-game scorecard — only recomputes when finished-game count changes."""
    global _scorecard_body_cache
    from bet_placer.data.wc_stages import stage_label, stage_short
    from bet_placer.engine.worldcup_pipeline import wc_match_to_analysis_match

    finished = sorted(_finished_matches(),
                      key=lambda w: getattr(w, "kickoff", None) or datetime.now(timezone.utc))
    n_key = len(finished)
    if _scorecard_body_cache and _scorecard_body_cache[0] == n_key:
        return _scorecard_body_cache[1]

    games = []
    for wc in finished:
        try:
            m = wc_match_to_analysis_match(wc)
            hl, al, events = _match_pred(m, apply_learned=True)
        except Exception:
            continue
        hs, aws = int(wc.home_score), int(wc.away_score)
        res = [e for e in events if e[0] == "result"]
        if not res:
            continue
        top = max(res, key=lambda e: e[2])
        pick, pick_p = top[1], float(top[2])
        actual = _result_of(hs, aws)
        mfav = _market_fav(wc)
        team = wc.home if pick == "home" else wc.away if pick == "away" else "Draw"
        md = getattr(wc, "matchday", None)
        games.append({
            "matchday": md,
            "stage": getattr(wc, "stage", None) or stage_short(md),
            "stage_label": stage_label(md),
            "is_knockout": getattr(wc, "is_knockout", False),
            "kickoff": wc.kickoff.isoformat() if getattr(wc, "kickoff", None) else None,
            "home": wc.home, "away": wc.away, "score": f"{hs}-{aws}",
            "our_pick": pick, "our_pick_team": team, "our_pick_pct": round(pick_p * 100),
            "confidence": _conf_tier(pick_p),
            "actual": actual, "hit": bool(pick == actual),
            "market_fav": mfav,
            "market_fav_hit": bool(mfav == actual) if mfav else None,
            "pred_total": round(hl + al, 1), "actual_total": hs + aws,
        })

    n = len(games)
    acc = round(sum(g["hit"] for g in games) / n, 3) if n else None

    bymd: dict = {}
    for g in games:
        bymd.setdefault(g["matchday"], []).append(g["hit"])
    by_matchday = [{"matchday": md, "n": len(v), "accuracy": round(sum(v) / len(v), 3)}
                   for md, v in sorted(bymd.items(), key=lambda kv: (kv[0] is None, kv[0]))]

    bystage: dict = {}
    stage_order: dict = {}
    for g in games:
        key = g.get("stage_label") or stage_label(g.get("matchday"))
        bystage.setdefault(key, []).append(g["hit"])
        stage_order[key] = g.get("matchday") or 0
    by_stage = [{"stage": st, "n": len(v), "accuracy": round(sum(v) / len(v), 3)}
                for st, v in sorted(bystage.items(), key=lambda kv: stage_order.get(kv[0], 99))]

    byconf: dict = {}
    for g in games:
        byconf.setdefault(g["confidence"], []).append(g["hit"])
    by_confidence = [{"tier": t, "n": len(byconf[t]),
                      "accuracy": round(sum(byconf[t]) / len(byconf[t]), 3)}
                     for t in ("lock", "strong", "lean", "coinflip") if t in byconf]

    cumulative, hits = [], 0
    for i, g in enumerate(games, 1):
        hits += g["hit"]
        cumulative.append({"i": i, "accuracy": round(hits / i, 3),
                           "label": f"{g['home']} v {g['away']}"})

    mkt = [g for g in games if g["market_fav_hit"] is not None]
    market_acc = round(sum(g["market_fav_hit"] for g in mkt) / len(mkt), 3) if mkt else None

    body = {
        "n_games": n, "accuracy": acc, "market_accuracy": market_acc,
        "beats_market": (acc is not None and market_acc is not None and acc >= market_acc),
        "by_matchday": by_matchday, "by_stage": by_stage, "by_confidence": by_confidence,
        "cumulative": cumulative,
        "games": list(reversed(games)),
    }
    _scorecard_body_cache = (n_key, body)
    return body


def worldcup_scorecard(refresh_recommendations: bool = False) -> dict:
    """Grade the live model against every finished World Cup game."""
    body = _scorecard_body()
    return {
        **body,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "recommendations": _recommendation_scorecard_cached(
            force=refresh_recommendations, full=refresh_recommendations,
        ),
    }


def _recommendation_scorecard_cached(force: bool = False, *, full: bool = False) -> dict:
    """Bet-slip grading — refresh when pick logic changes or cache is empty."""
    try:
        from bet_placer.ml.rec_grading import (
            REC_GRADING_VERSION,
            apply_strategy_learning,
            grade_all_recommendations,
        )
        params = load_params(force=True)
        cached = params.get("rec_learning") or {}
        if not force:
            if cached.get("n_games"):
                if cached.get("version") != REC_GRADING_VERSION:
                    return {**cached, "stale": True, "needs_refresh": True}
                return cached
            return {}
        stale = not cached.get("n_games") or cached.get("version") != REC_GRADING_VERSION
        if not stale:
            return cached
        report = grade_all_recommendations(
            max_games=None if full else 32,
            include_target=full,
        )
        params = apply_strategy_learning(params, report)
        save_params(params)
        load_params(force=True)
        return params.get("rec_learning") or report
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

def _brier(ps, ys):
    ps, ys = np.asarray(ps), np.asarray(ys)
    return float(np.mean((ps - ys) ** 2)) if len(ps) else None


def _logloss(ps, ys):
    ps = np.clip(np.asarray(ps), 1e-6, 1 - 1e-6)
    ys = np.asarray(ys)
    return float(-np.mean(ys * np.log(ps) + (1 - ys) * np.log(1 - ps))) if len(ps) else None


def _reliability(ps, ys, bins=5):
    ps, ys = np.asarray(ps), np.asarray(ys)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (ps >= lo) & (ps < hi if i < bins - 1 else ps <= hi)
        if mask.sum() == 0:
            continue
        out.append({
            "range": f"{int(lo*100)}-{int(hi*100)}%",
            "predicted": round(float(ps[mask].mean()) * 100, 1),
            "actual": round(float(ys[mask].mean()) * 100, 1),
            "n": int(mask.sum()),
        })
    return out


# --------------------------------------------------------------------------- #
# Fit / learn
# --------------------------------------------------------------------------- #

def _fit_platt(ps, ys):
    """Fit p_cal = sigmoid(a*logit(p)+b). Returns (a, b) or identity."""
    ps, ys = np.asarray(ps, float), np.asarray(ys, float)
    if len(ps) < 24 or len(np.unique(ys)) < 2:
        return 1.0, 0.0
    from sklearn.linear_model import LogisticRegression
    X = np.array([_logit(p) for p in ps]).reshape(-1, 1)
    try:
        lr = LogisticRegression(C=4.0, solver="lbfgs", max_iter=500)
        lr.fit(X, ys)
        a = float(lr.coef_[0][0])
        b = float(lr.intercept_[0])
        # guard against degenerate fits
        if not (0.2 <= a <= 3.0) or abs(b) > 3.0:
            return 1.0, 0.0
        return round(a, 4), round(b, 4)
    except Exception:
        return 1.0, 0.0


def train(verbose: bool = False) -> dict:
    """Learn from the FULL history of international football, then layer the
    World Cup games on top.

    Stage A — historical: replay ~49k real matches to learn an Elo strength per
              nation + the goal model (Elo edge -> goals) + calibration, fitted
              on ~10k recent games (ml/historical.py).
    Stage B — World Cup: with the learned model live, replay the finished WC
              games to report current-tournament accuracy + recent calls.
    Stage C — grade recommended slips → strategy weights.
    Stage D — paper book: spot match gems, bet under budget, P&L + craft weights.
    """
    params = json.loads(json.dumps(DEFAULT_PARAMS))  # deep copy

    # ---- Stage A: learn from history ----
    hist = None
    try:
        from bet_placer.ml.historical import train_history
        hist = train_history()
    except Exception as exc:  # offline / dataset unreachable -> fall back to WC-only
        if verbose:
            print(f"[tracker] historical training unavailable: {exc}")

    if hist:
        params["elo"] = hist["elo"]
        params["goal_model"] = hist["goal_model"]
        params["ad_model"] = hist.get("ad_model", {})
        params["calibration"] = hist["calibration"]
        params["goals_scale"] = 1.0      # goal model is fit directly; no extra scaling
        params["home_edge_adj"] = 0.0
        save_params(params)
        load_params(force=True)

    # ---- Stage A1b: basketball + cricket deep history (teams + players) ----
    sport_hist: dict = {}
    try:
        from bet_placer.ml.sport_history import apply_sport_history, train_sport_history
        sport_hist = train_sport_history(verbose=verbose)
        params = apply_sport_history(params, sport_hist)
        save_params(params)
        load_params(force=True)
    except Exception as exc:
        if verbose:
            print(f"[tracker] sport history unavailable: {exc}")

    # ---- Stage A2: club soccer + basketball + cricket from ESPN boards ----
    board_rep: dict = {}
    try:
        from bet_placer.ml.board_train import apply_board_training, train_from_boards
        board_rep = train_from_boards(
            verbose=verbose,
            seed_elo=params.get("elo_by_sport") or {},
        )
        params = apply_board_training(params, board_rep)
        save_params(params)
        load_params(force=True)
    except Exception as exc:
        if verbose:
            print(f"[tracker] board training unavailable: {exc}")

    # ---- Stage B: World Cup backtest with the learned model live ----
    rows, matches = build_backtest(apply_learned=True)
    wc_n = len(matches)
    wc_acc = float(np.mean([m["top_pick_hit"] for m in matches])) if matches else None
    wc_res = [r for r in rows if r["group"] == "result"]
    wc_brier = _brier([r["p"] for r in wc_res], [r["y"] for r in wc_res]) if wc_res else None

    # ---- Stage B2: multi-market bets on finished games (not just 1X2) ----
    market_rep: dict = {}
    try:
        from bet_placer.ml.market_replay import apply_market_replay, replay_multi_markets
        market_rep = replay_multi_markets(verbose=verbose)
        params = apply_market_replay(params, market_rep)
        save_params(params)
        load_params(force=True)
    except Exception as exc:
        if verbose:
            print(f"[tracker] market replay unavailable: {exc}")

    # ---- Stage C: grade the bets we actually recommend (slips, not just winners) ----
    rec_report: dict = {}
    try:
        from bet_placer.ml.rec_grading import apply_strategy_learning, grade_all_recommendations
        rec_report = grade_all_recommendations(include_target=True)
        params = apply_strategy_learning(params, rec_report)
    except Exception as exc:
        if verbose:
            print(f"[tracker] recommendation grading failed: {exc}")
        rec_report = params.get("rec_learning") or {}

    # ---- Stage D: betting craft — paper book gems under budget, P&L, improve ----
    paper_rep: dict = {}
    try:
        from bet_placer.ml.paper_book import run_paper_walkforward
        paper_rep = run_paper_walkforward(
            bankroll=10_000,
            match_budget=200,
            max_games=60,
            reset=True,
            verbose=verbose,
        )
        params = load_params(force=True)
    except Exception as exc:
        if verbose:
            print(f"[tracker] paper craft walkforward failed: {exc}")
        paper_rep = {"summary": (params.get("craft_learning") or {}).get("summary") or {}}

    h = (hist or {}).get("history", {})
    n_hist = h.get("n_matches", 0)
    n_boards = int((board_rep or {}).get("n_matches") or 0)
    sport_counts = (sport_hist or {}).get("counts") or params.get("trained_on_sport_history") or {}
    n_sport = int((sport_hist or {}).get("n_matches") or sum(sport_counts.values()) or 0)
    hist_acc = h.get("top_pick_accuracy")
    hist_brier = h.get("result_brier")
    confident = h.get("confident", {})

    save_params(params)
    load_params(force=True)

    from bet_placer.ml.activity_log import log_activity
    board_counts = (board_rep or {}).get("counts") or {}
    total_n = n_hist + n_sport + wc_n + n_boards
    log_activity(
        "train_complete",
        (
            f"Retrained on {total_n:,} games "
            f"(soccer/NBA/cricket history + boards + World Cup)"
        ),
        detail={
            "worldcup_accuracy": wc_acc,
            "board_counts": board_counts,
            "sport_history_counts": sport_counts,
            "player_counts": (sport_hist or {}).get("player_counts") or {},
            "market_replay_bets": (market_rep or {}).get("n_bets"),
            "market_replay_accuracy": (market_rep or {}).get("accuracy"),
            "leg_accuracy": rec_report.get("leg_accuracy"),
            "legs_graded": rec_report.get("legs_graded"),
            "strategy_weights": (rec_report.get("strategy_weights") or {}),
            "paper_pnl": (paper_rep.get("summary") or {}).get("pnl"),
            "paper_accuracy": (paper_rep.get("summary") or {}).get("accuracy"),
            "paper_tickets": (paper_rep.get("summary") or {}).get("settled"),
        },
    )

    paper_summary = (paper_rep.get("summary")
                     or (params.get("craft_learning") or {}).get("summary")
                     or {})
    report = {
        "trained_on": total_n,
        "trained_on_history": n_hist,
        "trained_on_sport_history": sport_counts,
        "trained_on_worldcup": wc_n,
        "trained_on_boards": board_counts,
        "sport_history": params.get("sport_history") or {},
        "market_replay": params.get("market_replay") or market_rep or {},
        "craft_learning": params.get("craft_learning") or {},
        "paper_book": paper_summary,
        "player_elo_counts": {
            s: len(t or {}) for s, t in (params.get("player_elo") or {}).items()
        },
        "board_scorecards": params.get("board_scorecards") or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "metrics": {
            "result_brier": hist_brier,
            "top_pick_accuracy": hist_acc,
            "n_outcomes_graded": h.get("n_recent_samples", 0) * 7,
            "holdout_accuracy": h.get("holdout_accuracy"),
            "holdout_log_loss": h.get("holdout_log_loss"),
            "holdout_n": h.get("holdout_n"),
            "worldcup_accuracy": round(wc_acc, 3) if wc_acc is not None else None,
            "worldcup_brier": round(wc_brier, 4) if wc_brier is not None else None,
            "recommendation_leg_accuracy": rec_report.get("leg_accuracy"),
            "recommended_slip_accuracy": rec_report.get("recommended_slip_accuracy"),
            "recommendation_legs_graded": rec_report.get("legs_graded"),
            "paper_accuracy": paper_summary.get("accuracy"),
            "paper_pnl": paper_summary.get("pnl"),
            "paper_roi": paper_summary.get("roi"),
            "board_matches": n_boards,
            "board_accuracy": (params.get("board_scorecards") or {}).get("accuracy") or {},
            "sport_history_accuracy": (params.get("sport_history") or {}).get("accuracy") or {},
        },
        "recommendation_scorecard": rec_report,
        "confident": confident,
        "tuning": (hist or {}).get("tuning", {}),
        "reliability": (hist or {}).get("reliability", []),
        "corrections": {
            "goals_scale": params["goals_scale"],
            "home_edge_adj": params["home_edge_adj"],
            "goal_model": params.get("goal_model", {}),
            "calibration": params.get("calibration", {}),
            "top_teams": h.get("top_teams", []),
        },
        "diagnosis": _diagnose_v2(h, params.get("calibration", {}), wc_acc, wc_n, rec_report, board_counts),
        "recent": sorted(matches, key=lambda m: -abs(m["top_pick_p"] - m["top_pick_hit"]))[:12],
        "sample": {"history_matches": n_hist,
                   "history_accuracy_pct": round(hist_acc * 100, 1) if hist_acc else None,
                   "worldcup_games": wc_n,
                   "board_matches": board_counts,
                   "sport_history_matches": sport_counts},
    }
    run = {
        "at": report["updated_at"],
        "trained_on": report["trained_on"],
        "holdout_accuracy": report["metrics"].get("holdout_accuracy"),
        "holdout_n": report["metrics"].get("holdout_n"),
        "worldcup_accuracy": report["metrics"].get("worldcup_accuracy"),
        "worldcup_games": wc_n,
        "leg_accuracy": report["metrics"].get("recommendation_leg_accuracy"),
        "legs_graded": report["metrics"].get("recommendation_legs_graded"),
        "result_brier": report["metrics"].get("result_brier"),
        "board_counts": board_counts,
        "board_accuracy": (params.get("board_scorecards") or {}).get("accuracy") or {},
        "sport_history_counts": sport_counts,
        "sport_history_accuracy": (params.get("sport_history") or {}).get("accuracy") or {},
    }
    hist_runs = list(params.get("learning_history") or [])
    hist_runs.append(run)
    params["learning_history"] = hist_runs[-40:]
    params["trained_on"] = report["trained_on"]
    params["updated_at"] = report["updated_at"]
    params["report"] = report
    save_params(params)
    load_params(force=True)

    # Equal-depth post-train: filled factor graph + match↔betting evolution
    try:
        from bet_placer.ml.factor_store import rebuild as rebuild_factors
        report["factors"] = rebuild_factors(params)
    except Exception as exc:
        if verbose:
            print(f"[tracker] factor_store rebuild failed: {exc}")
    try:
        from bet_placer.ml.betting_evolution import rebuild_from_corpora
        report["betting"] = rebuild_from_corpora(verbose=verbose)
    except Exception as exc:
        if verbose:
            print(f"[tracker] betting_evolution rebuild failed: {exc}")

    report["learning"] = _learning_snapshot(params)
    if verbose:
        print(json.dumps({k: report[k] for k in report if k != "recent"}, indent=2)[:2000])
    return report


def _diagnose_v2(h: dict, cal: dict, wc_acc, wc_n: int, rec_report: dict | None = None,
                 board_counts: dict | None = None) -> list[str]:
    out = []
    n_hist = h.get("n_matches", 0)
    acc = h.get("top_pick_accuracy")
    brier = h.get("result_brier")
    ho_acc = h.get("holdout_accuracy")
    ho_n = h.get("holdout_n")
    conf = h.get("confident", {})
    if n_hist:
        out.append(f"Learned team strength (Elo) from {n_hist:,} real international matches — "
                   "ratings reflect actual recent results, not reputation. Settings (K-factor, "
                   "home edge) were tuned on a time-split holdout so we optimise for predicting "
                   "the future, not memorising the past.")
    boards = board_counts or {}
    if boards:
        bits = [f"{int(n):,} {s}" for s, n in boards.items() if n]
        if bits:
            out.append(
                "Board Elo (walk-forward) from finished fixtures: "
                + ", ".join(bits)
                + ". Soccer = 3-way; basketball / cricket = moneyline 2-way with sport-specific home edge."
            )
    if ho_acc is not None and ho_n:
        out.append(f"On {ho_n:,} matches it had NEVER trained on (2021→today) it calls the right "
                   f"result {ho_acc*100:.0f}% of the time. Three-way football has a hard ceiling "
                   "near ~60% because draws are near coin-flips — so the number that matters is "
                   "how good we are WHEN WE'RE CONFIDENT.")
    if conf:
        bits = []
        for thr in ("60", "65", "70"):
            if thr in conf:
                bits.append(f"≥{thr}% → right {conf[thr]['accuracy']*100:.0f}% ({conf[thr]['n']:,} games)")
        if bits:
            out.append("Confidence pays off: when our top pick is " + "; ".join(bits) +
                       ". Those are the games to actually bet.")
    if acc is not None:
        out.append(f"Probabilities are calibrated on {h.get('n_recent_samples', 0):,} recent games "
                   f"(Brier {brier}) — a stated 70% genuinely lands ~70% of the time.")
    a = (cal.get("result") or {}).get("a", 1.0)
    if a < 0.9:
        out.append("Calibration gently pulls extreme probabilities toward the middle so a "
                   "stated '70%' really lands ~70% of the time (favourite-longshot bias).")
    elif a > 1.1:
        out.append("Calibration sharpens probabilities — the raw model was under-confident.")
    else:
        out.append("Probabilities are already well calibrated; only a light touch-up applied.")
    tops = h.get("top_teams", [])
    if tops:
        names = ", ".join(t["team"].title() for t in tops[:5])
        out.append(f"Current strongest sides by learned Elo: {names}.")
    if wc_acc is not None and wc_n:
        out.append(f"On the {wc_n} finished World Cup games so far it has called {wc_acc*100:.0f}% correctly.")
    rec = rec_report or {}
    leg_acc = rec.get("leg_accuracy")
    slip_acc = rec.get("recommended_slip_accuracy")
    legs_n = rec.get("legs_graded")
    if leg_acc is not None and legs_n:
        out.append(
            f"On the {legs_n} recommended bet legs it surfaced (recs + target paths), "
            f"{leg_acc*100:.0f}% actually won — that's the number that matters for your slips."
        )
    target_row = next((s for s in (rec.get("by_strategy") or []) if s.get("strategy") == "target_hit"), None)
    if target_row and target_row.get("leg_hit_rate") is not None:
        out.append(
            f"Target-tab best paths hit {(target_row['leg_hit_rate'])*100:.0f}% of graded legs "
            f"({target_row.get('legs_graded', 0)} legs across {target_row.get('games', 0)} games)."
        )
    stack_row = next((s for s in (rec.get("by_strategy") or []) if s.get("strategy") == "target_stack"), None)
    if stack_row and stack_row.get("slip_any_hit_rate") is not None:
        out.append(
            f"Multi-ticket target stacks landed at least one winner "
            f"{stack_row['slip_any_hit_rate']*100:.0f}% of the time."
        )
    if slip_acc is not None:
        out.append(
            f"The top recommended slip per match fully hit {slip_acc*100:.0f}% of the time so far."
        )
    by_strat = rec.get("by_strategy") or []
    if by_strat:
        best = by_strat[0]
        worst = by_strat[-1] if len(by_strat) > 1 else None
        out.append(
            f"Best-performing plan type so far: {best.get('label')} ({(best.get('leg_hit_rate') or 0)*100:.0f}% leg hit rate). "
            + (f"Weakest: {worst.get('label')} ({(worst.get('leg_hit_rate') or 0)*100:.0f}%)." if worst else "")
        )
    return out


def _diagnose(pred_tot, act_tot, pred_home, act_home, cal, acc) -> list[str]:
    out = []
    gd = act_tot - pred_tot
    if gd > 0.25:
        out.append(f"Under-predicting goals: games averaged {act_tot:.2f} but the model expected "
                   f"{pred_tot:.2f}. Raising the scoring baseline (+{(gd):.2f} goals/game).")
    elif gd < -0.25:
        out.append(f"Over-predicting goals: model expected {pred_tot:.2f}, reality was {act_tot:.2f}. "
                   "Trimming the scoring baseline.")
    else:
        out.append(f"Scoring level is well calibrated (model {pred_tot:.2f} vs actual {act_tot:.2f} goals/game).")

    hd = act_home - pred_home
    if hd > 0.06:
        out.append(f"Home sides won more than expected ({act_home*100:.0f}% vs {pred_home*100:.0f}%) — "
                   "nudging the home-field edge up.")
    elif hd < -0.06:
        out.append(f"Home edge over-stated ({pred_home*100:.0f}% expected, {act_home*100:.0f}% real) — easing it down.")
    else:
        out.append("Home-field advantage is about right.")

    a = (cal.get("result") or {}).get("a", 1.0)
    if a < 0.85:
        out.append("Was over-confident on favourites/long-shots — calibration now pulls extreme "
                   "probabilities toward the middle (favourite-longshot bias).")
    elif a > 1.15:
        out.append("Was under-confident — calibration now sharpens probabilities.")

    ta = (cal.get("totals") or {}).get("a", 1.0)
    if ta < 0.85:
        out.append("Over/under reads were too confident — calibration softens total-goals "
                   "probabilities so the prices we flag as value are real.")

    out.append(f"Picks the right match result {acc*100:.0f}% of the time across finished games.")
    return out


def _learning_snapshot(params: dict) -> dict:
    """What the model already knows without a full retrain."""
    elo = params.get("elo") or {}
    cal = params.get("calibration") or {}
    gm = params.get("goal_model") or {}
    hist = list(params.get("learning_history") or [])
    prev = hist[-2] if len(hist) >= 2 else None
    last = hist[-1] if hist else None
    delta = None
    if prev and last and prev.get("holdout_accuracy") is not None and last.get("holdout_accuracy") is not None:
        delta = round(float(last["holdout_accuracy"]) - float(prev["holdout_accuracy"]), 4)
    boards = params.get("trained_on_boards") or {}
    cards = params.get("board_scorecards") or {}
    sh = params.get("sport_history") or {}
    return {
        "elo_teams": len(elo),
        "has_goal_model": bool(gm),
        "goals_scale": params.get("goals_scale"),
        "home_edge_adj": params.get("home_edge_adj"),
        "calibration_keys": list(cal.keys())[:12],
        "trained_on": params.get("trained_on") or 0,
        "updated_at": params.get("updated_at"),
        "learning_runs": len(hist),
        "last_run": last,
        "holdout_delta_vs_prev": delta,
        "history": hist[-12:],
        "board_counts": boards,
        "board_accuracy": cards.get("accuracy") or {},
        "sport_history_counts": params.get("trained_on_sport_history") or sh.get("counts") or {},
        "sport_history_accuracy": sh.get("accuracy") or {},
        "player_counts": sh.get("player_counts") or {
            s: len(t or {}) for s, t in (params.get("player_elo") or {}).items()
        },
        "elo_by_sport_counts": {
            s: len(t or {}) for s, t in (params.get("elo_by_sport") or {}).items()
        },
    }


def _empty_report(msg: str) -> dict:
    return {
        "trained_on": 0, "updated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {}, "reliability": [], "corrections": {},
        "diagnosis": [msg], "recent": [], "sample": {},
        "status": "empty",
        "learning": {},
    }


def _merge_rec_into_report(rep: dict) -> dict:
    """Keep recommendation stats in sync with the latest grading run."""
    params = load_params(force=True)
    rec = params.get("rec_learning") or {}
    out = dict(rep)
    if rec:
        metrics = dict(out.get("metrics") or {})
        metrics["recommendation_leg_accuracy"] = rec.get("leg_accuracy")
        metrics["recommended_slip_accuracy"] = rec.get("recommended_slip_accuracy")
        metrics["recommendation_legs_graded"] = rec.get("legs_graded")
        out["metrics"] = metrics
        out["recommendation_scorecard"] = rec
    out["learning"] = _learning_snapshot(params)
    out["status"] = "ready"
    return out


def get_report(retrain: bool = False) -> dict:
    """Return cached report instantly. Only retrain when explicitly asked.

    ponytail: never auto-train on page load — history fit is minutes and hung the API.
    """
    params = load_params(force=True)
    rep = params.get("report")
    if retrain:
        return train()
    if rep:
        out = _merge_rec_into_report(rep)
        boards = params.get("trained_on_boards") or out.get("trained_on_boards") or {}
        out["trained_on_boards"] = boards
        elo_by = params.get("elo_by_sport") or {}
        out["elo_by_sport"] = {
            sport: len(tbl or {})
            for sport, tbl in elo_by.items()
        }
        out["elo_by_sport_top"] = {
            sport: sorted(
                [{"team": t, "elo": round(float(e), 1)} for t, e in (tbl or {}).items()],
                key=lambda r: -r["elo"],
            )[:12]
            for sport, tbl in elo_by.items()
            if tbl
        }
        cards = params.get("board_scorecards") or out.get("board_scorecards") or {}
        out["board_scorecards"] = cards
        out["trained_on_sport_history"] = (
            params.get("trained_on_sport_history") or out.get("trained_on_sport_history") or {}
        )
        out["sport_history"] = params.get("sport_history") or out.get("sport_history") or {}
        out["market_replay"] = params.get("market_replay") or out.get("market_replay") or {}
        out["craft_learning"] = params.get("craft_learning") or {}
        try:
            from bet_placer.ml.craft_store import progress_snapshot
            from bet_placer.ml.paper_book import summarize
            progress = progress_snapshot()
            out["craft_progress"] = progress
            out["paper_book"] = {
                **(summarize()),
                "progress": progress,
            }
        except Exception:
            out["craft_progress"] = {}
            out["paper_book"] = (params.get("craft_learning") or {}).get("summary") or {}
        out["player_elo_counts"] = {
            s: len(t or {}) for s, t in (params.get("player_elo") or {}).items()
        }
        metrics = dict(out.get("metrics") or {})
        metrics["board_accuracy"] = (cards.get("accuracy") or {})
        metrics["sport_history_accuracy"] = (out["sport_history"].get("accuracy") or {})
        mr = out.get("market_replay") or {}
        if mr:
            metrics["market_replay_accuracy"] = mr.get("accuracy")
            metrics["market_replay_by_market"] = mr.get("accuracy_by_market") or {}
            metrics["market_replay_n_bets"] = mr.get("n_bets")
        out["metrics"] = metrics
        try:
            from bet_placer.ml.model_insights import build_model_insights
            out["insights"] = build_model_insights(params)
        except Exception:
            out["insights"] = {}
        return out
    snap = _learning_snapshot(params)
    empty = _empty_report(
        "Weights are on disk but there is no graded scorecard yet. "
        "Click Retrain to fit history, grade league boards + World Cup slips, and record a learning run."
        if snap.get("elo_teams")
        else "No trained model yet. Click Retrain to learn from international history, ESPN boards, and World Cup results."
    )
    empty["status"] = "needs_train"
    empty["trained_on"] = snap.get("trained_on") or 0
    empty["trained_on_boards"] = params.get("trained_on_boards") or {}
    empty["trained_on_sport_history"] = params.get("trained_on_sport_history") or {}
    empty["sport_history"] = params.get("sport_history") or {}
    empty["board_scorecards"] = params.get("board_scorecards") or {}
    empty["elo_by_sport"] = {
        sport: len(tbl or {})
        for sport, tbl in (params.get("elo_by_sport") or {}).items()
    }
    empty["player_elo_counts"] = {
        s: len(t or {}) for s, t in (params.get("player_elo") or {}).items()
    }
    empty["learning"] = snap
    empty["has_weights"] = bool(snap.get("elo_teams"))
    try:
        from bet_placer.ml.craft_store import progress_snapshot
        from bet_placer.ml.paper_book import summarize
        progress = progress_snapshot()
        empty["craft_progress"] = progress
        empty["paper_book"] = {**(summarize()), "progress": progress}
        empty["craft_learning"] = params.get("craft_learning") or {}
    except Exception:
        empty["craft_progress"] = {}
        empty["paper_book"] = (params.get("craft_learning") or {}).get("summary") or {}
    try:
        from bet_placer.ml.model_insights import build_model_insights
        empty["insights"] = build_model_insights(params)
        # Surface corpus so the UI never shows "0 games" when boards/history exist
        ins = empty["insights"]
        empty["trained_on"] = max(
            int(empty.get("trained_on") or 0),
            int(ins.get("total_corpus") or 0),
        )
        if empty.get("status") == "needs_train" and ins.get("total_corpus"):
            empty["status"] = ins.get("status") or "ready"
    except Exception:
        empty["insights"] = {}
    return empty


# --------------------------------------------------------------------------- #
# Live prediction logging (extends the training set over time)
# --------------------------------------------------------------------------- #

def log_prediction(home: str, away: str, kickoff, win_probability: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "home": home, "away": away,
               "kickoff": kickoff, "win_probability": win_probability}
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
