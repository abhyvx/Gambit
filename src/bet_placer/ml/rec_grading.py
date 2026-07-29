"""Grade the bets we actually recommend — not just match-winner picks.

Replays the full slip pipeline on finished World Cup games and scores every leg
in min_loss, singles_focus, value, smart_parlay, and the lead unified pick.
Outcomes feed the model report card and strategy learning weights.
"""

from __future__ import annotations

import re
from typing import Any

from bet_placer.ml.tracker import _grade, _result_of

# Bump when grading / pick logic changes so stale cached scorecards refresh.
REC_GRADING_VERSION = 4

STRATEGY_KEYS = ("match_card", "min_loss", "singles_focus", "value", "smart_parlay", "target_hit", "target_stack")
STRATEGY_LABELS = {
    "match_card": "Spread card",
    "min_loss": "Loss minimize",
    "singles_focus": "One best bet",
    "value": "Value hunt",
    "smart_parlay": "Smart parlay",
    "target_hit": "Target · best path",
    "target_stack": "Target · multi-ticket",
    "easy_money": "Easy money",
    "recommended": "Top recommended",
}


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def grade_leg(
    leg: dict[str, Any],
    *,
    home: str,
    away: str,
    hs: int,
    aws: int,
) -> bool | None:
    """Return True/False if gradable, None if we cannot map the leg."""
    market = (leg.get("market") or "").lower()
    selection = (leg.get("selection") or "").lower()
    line = leg.get("line")
    label = _norm(leg.get("label"))

    if market == "match_winner" or (not market and " to win" in label):
        side = selection or _team_side_from_label(label, home, away)
        if side in ("home", "draw", "away"):
            return bool(_grade(side, hs, aws))
        return None

    if market == "double_chance" or label.startswith("draw or "):
        team = label.replace("draw or ", "").strip() if label.startswith("draw or ") else ""
        if not team:
            team = _team_from_selection(selection, home, away)
        if team == _norm(home) or selection in ("home_draw", "home_or_draw", "1x"):
            return bool(hs >= aws)
        if team == _norm(away) or selection in ("draw_away", "away_or_draw", "x2"):
            return bool(aws >= hs)
        if selection in ("home_away", "12", "no_draw"):
            return bool(hs != aws)
        if team:
            if team in _norm(home):
                return bool(hs >= aws)
            if team in _norm(away):
                return bool(aws >= hs)
        return None

    if market == "draw_no_bet":
        side = selection or _team_side_from_label(label, home, away)
        if side == "home":
            return bool(hs > aws) if hs != aws else False  # push = not a win for DNB
        if side == "away":
            return bool(aws > hs) if hs != aws else False
        return None

    if market == "over_under_goals" or "over" in label or "under" in label:
        sel = selection or ("over" if "over" in label else "under" if "under" in label else "")
        ln = line
        if ln is None:
            m = re.search(r"(over|under)\s*([\d.]+)", label)
            if m:
                sel, ln = m.group(1), float(m.group(2))
        if ln is None:
            return None
        # Team totals: home_over / away_under / "Lakers Over 112.5 points"
        team_side = None
        if sel.startswith("home_") or (home and _norm(home) in label and ("over" in label or "under" in label)):
            team_side = "home"
            sel = sel.replace("home_", "") or ("over" if "over" in label else "under")
        elif sel.startswith("away_") or (away and _norm(away) in label and ("over" in label or "under" in label)):
            team_side = "away"
            sel = sel.replace("away_", "") or ("over" if "over" in label else "under")
        total = float(hs if team_side == "home" else aws if team_side == "away" else (hs + aws))
        if sel == "over":
            return bool(total > float(ln))
        if sel == "under":
            return bool(total < float(ln))
        return None

    if market == "btts" or "both teams" in label or label.startswith("btts"):
        sel = selection or ("yes" if "yes" in label else "no" if "no" in label else "")
        if sel in ("yes", "no"):
            return bool(_grade(sel, hs, aws))
        return None

    if market in ("asian_handicap", "handicap"):
        side = _team_side_from_label(label, home, away) or selection
        if side in ("home", "away") and line is not None:
            adj = (hs + float(line)) - aws if side == "home" else (aws - float(line)) - hs
            return bool(adj > 0) if adj != 0 else False
        return None

    if market == "stake_combo" or leg.get("verified_stake"):
        parts = leg.get("combo_parts") or []
        if not parts and " & " in label:
            parts = [p.strip() for p in label.split(" & ")]
        if parts:
            hits = [grade_leg({"label": p, "market": ""}, home=home, away=away, hs=hs, aws=aws) for p in parts]
            scorable = [h for h in hits if h is not None]
            if scorable:
                return all(scorable)
        return None

    return None


def _norm_team(name: str) -> str:
    return _norm(name)


def _team_side_from_label(label: str, home: str, away: str) -> str | None:
    lh, la = _norm_team(home), _norm_team(away)
    if lh and lh in label:
        return "home"
    if la and la in label:
        return "away"
    if "draw" in label and " or " not in label:
        return "draw"
    return None


def _team_from_selection(selection: str, home: str, away: str) -> str:
    if selection in ("home", "home_draw", "1x"):
        return _norm(home)
    if selection in ("away", "draw_away", "x2"):
        return _norm(away)
    return selection


def grade_slip_legs(
    legs: list[dict[str, Any]],
    *,
    home: str,
    away: str,
    hs: int,
    aws: int,
) -> dict[str, Any]:
    graded = []
    for leg in legs or []:
        hit = grade_leg(leg, home=home, away=away, hs=hs, aws=aws)
        graded.append({**leg, "hit": hit, "graded": hit is not None})
    scorable = [g for g in graded if g["graded"]]
    hits = sum(1 for g in scorable if g["hit"])
    misses = sum(1 for g in scorable if not g["hit"])
    ungraded = sum(1 for g in graded if not g["graded"])
    return {
        "legs": graded,
        "scorable_legs": len(scorable),
        "hits": hits,
        "misses": misses,
        "ungraded": ungraded,
        "all_hit": bool(scorable) and hits == len(scorable),
        "any_hit": hits > 0,
        "target_hit": any(l.get("hits_target") and l.get("hit") for l in graded if l.get("graded")),
        "hit_rate": round(hits / len(scorable), 3) if scorable else None,
    }


def _strategy_bucket_from_plan(plan: dict) -> dict[str, Any]:
    legs = [l for l in plan.get("legs") or [] if float(l.get("stake_inr") or 0) > 0]
    return {
        "option_id": plan.get("option_id"),
        "plan_type": plan.get("plan_type"),
        "ticket_count": plan.get("ticket_count") or len(legs),
        "path_headline": plan.get("path_headline"),
        "legs": legs,
    }


def _grade_target_paths(
    match,
    adjusted,
    human_ctx: dict,
    *,
    home: str,
    away: str,
    hs: int,
    aws: int,
    budget_inr: float,
) -> dict[str, Any]:
    """Replay hit-target planner on a finished game and grade surfaced legs."""
    from bet_placer.engine.market_advisor import resolve_portfolio_options
    from bet_placer.engine.target_planner import build_target_plans

    target_cashout = float(human_ctx.get("target_cashout_inr") or max(budget_inr * 2.5, budget_inr + 500))
    ctx = {**human_ctx, "target_hit_mode": True, "target_cashout_inr": target_cashout, "grading_replay": True}
    try:
        options = resolve_portfolio_options(match, adjusted, budget_inr, ctx, home, away)
        result = build_target_plans(
            options, budget_inr, target_cashout, home, away,
            match=match, probabilities=adjusted, human_context=ctx,
        )
    except Exception:
        return {}

    plans = result.get("plans") or []
    if not plans:
        return {}

    out: dict[str, Any] = {}
    top = plans[0]
    g0 = grade_slip_legs(
        [l for l in top.get("legs") or [] if float(l.get("stake_inr") or 0) > 0],
        home=home, away=away, hs=hs, aws=aws,
    )
    out["target_hit"] = {
        "label": STRATEGY_LABELS["target_hit"],
        **_strategy_bucket_from_plan(top),
        "legs": g0["legs"],
        "scorable_legs": g0["scorable_legs"],
        "hits": g0["hits"],
        "misses": g0.get("misses", 0),
        "ungraded": g0.get("ungraded", 0),
        "all_hit": g0["all_hit"],
        "any_hit": g0["any_hit"] or g0.get("target_hit"),
        "hit_rate": g0["hit_rate"],
        "empty": not g0["legs"],
    }

    multi = next(
        (
            p for p in plans
            if (p.get("ticket_count") or len([l for l in p.get("legs") or [] if float(l.get("stake_inr") or 0) > 0])) >= 3
        ),
        None,
    )
    if multi and multi is not top:
        gm = grade_slip_legs(
            [l for l in multi.get("legs") or [] if float(l.get("stake_inr") or 0) > 0],
            home=home, away=away, hs=hs, aws=aws,
        )
        out["target_stack"] = {
            "label": STRATEGY_LABELS["target_stack"],
            **_strategy_bucket_from_plan(multi),
            "legs": gm["legs"],
            "scorable_legs": gm["scorable_legs"],
            "hits": gm["hits"],
            "misses": gm.get("misses", 0),
            "ungraded": gm.get("ungraded", 0),
            "all_hit": gm["all_hit"],
            "any_hit": gm["any_hit"] or gm.get("target_hit"),
            "hit_rate": gm["hit_rate"],
            "empty": not gm["legs"],
        }
    return out


def build_recommendation_bundle(
    wc, budget_inr: float = 300, *, include_target: bool = False,
) -> dict[str, Any] | None:
    """Build the live slip stack for a WC match (pre-result view). Shared by grade + paper book."""
    from bet_placer.data.team_ratings import blended_strength, fan_read
    from bet_placer.data.worldcup2026 import get_all_group_matches, get_group_standings
    from bet_placer.engine.all_markets import predict_all_markets
    from bet_placer.engine.bet_builder import _match_thesis, build_match_flat_board
    from bet_placer.engine.match_slip import build_match_slip, serialize_slip
    from bet_placer.engine.smart_picks import align_slip_with_picks, build_smart_picks
    from bet_placer.engine.stake_odds import hydrate_stake_context
    from bet_placer.engine.worldcup_pipeline import wc_match_to_analysis_match
    from bet_placer.intuition.analyst import AnalystIntuition
    from bet_placer.math.normalize import normalize_estimates
    from bet_placer.models.enums import MarketType

    target_cashout = max(budget_inr * 2.5, budget_inr + 500)
    try:
        match = wc_match_to_analysis_match(wc)
        intuition = AnalystIntuition()
        adjusted = normalize_estimates(intuition.adjust_probabilities(match, predict_all_markets(match)))
        all_wc = get_all_group_matches()
        standings = [] if wc.is_knockout else get_group_standings(wc.group, all_wc)
        home_pts = next((s["pts"] for s in standings if s["team"] == wc.home), 0)
        away_pts = next((s["pts"] for s in standings if s["team"] == wc.away), 0)
        fan_take = fan_read(
            wc.home, wc.away, home_pts, away_pts, wc.home_must_win, wc.away_must_win,
        )
        human_ctx = {
            "narrative": wc.narrative,
            "home_must_win": wc.home_must_win,
            "away_must_win": wc.away_must_win,
            "morale": {"home": wc.home_morale, "away": wc.away_morale},
            "stake_priced": False,
            "is_knockout": wc.is_knockout,
            "status": "upcoming",
            "chemistry_notes": list(getattr(match.chemistry, "notes", None) or []),
            "fan_take": fan_take,
            "team_strength": {
                "home": blended_strength(wc.home, home_pts, wc.home_morale),
                "away": blended_strength(wc.away, away_pts, wc.away_morale),
            },
            "target_cashout_inr": target_cashout,
        }
        flat, board_source = build_match_flat_board(
            match, adjusted, budget_inr, human_ctx, wc.home, wc.away, launch_browser=False,
        )
        human_ctx["_flat_board"] = flat
        human_ctx["_board_source"] = board_source
        human_ctx = hydrate_stake_context(human_ctx, wc.home, wc.away)
        if not human_ctx.get("stake_overlay") and flat:
            human_ctx["grading_replay"] = True
        mw = {
            p.selection: p.probability
            for p in adjusted
            if p.market == MarketType.MATCH_WINNER
        }
        thesis = _match_thesis(flat, wc.home, wc.away, model_probs=mw)
        unified = build_smart_picks(
            flat, wc.home, wc.away, match, adjusted, human_ctx,
            thesis=thesis, matchday=getattr(wc, "matchday", None),
        )
        human_ctx["unified_picks"] = unified.get("unified_picks") or []
        human_ctx["match_thesis"] = thesis
        slip = build_match_slip(
            wc.id, f"{wc.home} vs {wc.away}", wc.home, wc.away,
            match, adjusted, budget_inr, human_ctx, {"verdict": "BET"},
        )
        slip_data = align_slip_with_picks(serialize_slip(slip), unified)
        target_paths = {}
        hs = getattr(wc, "home_score", None)
        aws = getattr(wc, "away_score", None)
        if include_target and hs is not None and aws is not None:
            target_paths = _grade_target_paths(
                match, adjusted, human_ctx,
                home=wc.home, away=wc.away, hs=int(hs), aws=int(aws),
                budget_inr=budget_inr,
            )
    except Exception:
        return None

    return {
        "match_id": getattr(wc, "id", f"{wc.home}-{wc.away}"),
        "home": wc.home,
        "away": wc.away,
        "hs": getattr(wc, "home_score", None),
        "aws": getattr(wc, "away_score", None),
        "matchday": getattr(wc, "matchday", None),
        "slip_data": slip_data,
        "unified": unified,
        "flat": human_ctx.get("_flat_board") or [],
        "thesis": human_ctx.get("match_thesis") or {},
        "target_paths": target_paths,
    }


def replay_match_recommendations(
    wc, budget_inr: float = 300, *, include_target: bool = True,
) -> dict[str, Any] | None:
    """Rebuild slips for a finished match and grade every recommended leg."""
    if wc.status != "completed" or wc.home_score is None or wc.away_score is None:
        return None

    bundle = build_recommendation_bundle(wc, budget_inr, include_target=include_target)
    if not bundle:
        return None

    slip_data = bundle["slip_data"]
    unified = bundle["unified"]
    target_paths = bundle.get("target_paths") or {}
    hs, aws = int(bundle["hs"]), int(bundle["aws"])
    actual = _result_of(hs, aws)
    strategies: dict[str, Any] = {}
    plans = slip_data.get("strategy_plans") or {}
    for key in STRATEGY_KEYS:
        plan_list = plans.get(key) or []
        top = plan_list[0] if plan_list else {}
        legs = top.get("legs") or []
        g = grade_slip_legs(legs, home=wc.home, away=wc.away, hs=hs, aws=aws)
        strategies[key] = {
            "label": STRATEGY_LABELS.get(key, key),
            "option_id": top.get("option_id"),
            "legs": g["legs"],
            "scorable_legs": g["scorable_legs"],
            "hits": g["hits"],
            "misses": g.get("misses", 0),
            "ungraded": g.get("ungraded", 0),
            "all_hit": g["all_hit"],
            "any_hit": g["any_hit"],
            "hit_rate": g["hit_rate"],
            "empty": not legs,
        }

    curated = slip_data.get("curated_picks") or {}
    primary = curated.get("primary") or {}
    if primary.get("legs"):
        g = grade_slip_legs(primary["legs"], home=wc.home, away=wc.away, hs=hs, aws=aws)
        strategies["recommended"] = {
            "label": STRATEGY_LABELS["recommended"],
            "legs": g["legs"],
            "scorable_legs": g["scorable_legs"],
            "hits": g["hits"],
            "misses": g.get("misses", 0),
            "ungraded": g.get("ungraded", 0),
            "all_hit": g["all_hit"],
            "any_hit": g["any_hit"],
            "hit_rate": g["hit_rate"],
            "empty": False,
        }

    easy = (unified.get("easy_money") or [])
    if not easy:
        strategies["easy_money"] = {
            "label": STRATEGY_LABELS["easy_money"],
            "legs": [],
            "scorable_legs": 0,
            "hits": 0,
            "all_hit": None,
            "hit_rate": None,
            "empty": True,
            "skipped": "No pick cleared the high-confidence bar",
        }
    else:
        easy_g = grade_slip_legs([easy[0]], home=wc.home, away=wc.away, hs=hs, aws=aws)
        strategies["easy_money"] = {
            "label": STRATEGY_LABELS["easy_money"],
            "legs": easy_g["legs"],
            "scorable_legs": easy_g["scorable_legs"],
            "hits": easy_g["hits"],
            "all_hit": easy_g["all_hit"],
            "hit_rate": easy_g["hit_rate"],
            "empty": False,
        }

    strategies.update(target_paths)

    rec_id = slip_data.get("recommended_strategy") or slip_data.get("recommended_slip_id", "")
    if rec_id and "_" in str(rec_id):
        rec_id = str(rec_id).rsplit("_", 1)[0]
    rec_plan = strategies.get("recommended") or strategies.get(rec_id) or strategies.get("match_card") or strategies.get("singles_focus")

    return {
        "home": wc.home,
        "away": wc.away,
        "score": f"{hs}-{aws}",
        "actual_result": actual,
        "matchday": wc.matchday,
        "recommended_strategy": rec_id,
        "recommended_hit": rec_plan.get("any_hit") if rec_plan else None,
        "recommended_leg_hit_rate": rec_plan.get("hit_rate") if rec_plan else None,
        "strategies": strategies,
    }


def grade_all_recommendations(
    budget_inr: float = 300,
    *,
    max_games: int | None = None,
    include_target: bool = True,
) -> dict[str, Any]:
    """Aggregate recommendation grading across all finished World Cup games."""
    from bet_placer.ml.tracker import _finished_matches

    games = []
    strat_stats: dict[str, dict[str, int]] = {
        k: {
            "graded": 0, "hits": 0, "misses": 0, "ungraded": 0,
            "games": 0, "any_wins": 0, "target_route_games": 0, "target_route_wins": 0,
        }
        for k in (*STRATEGY_KEYS, "easy_money", "recommended")
    }
    leg_stats = {"graded": 0, "hits": 0, "misses": 0, "ungraded": 0}
    result_counts = {"home": 0, "draw": 0, "away": 0}

    finished = sorted(_finished_matches(), key=lambda w: getattr(w, "kickoff", None) or "")
    if max_games is not None and max_games > 0:
        finished = finished[-max_games:]

    for wc in finished:
        row = replay_match_recommendations(
            wc, budget_inr=budget_inr, include_target=include_target,
        )
        if not row:
            continue
        games.append(row)
        actual = row.get("actual_result")
        if actual in result_counts:
            result_counts[actual] += 1
        for key, st in row.get("strategies", {}).items():
            bucket = strat_stats.setdefault(
                key, {
                    "graded": 0, "hits": 0, "misses": 0, "ungraded": 0,
                    "games": 0, "any_wins": 0, "target_route_games": 0, "target_route_wins": 0,
                },
            )
            if st.get("empty") or st.get("skipped"):
                continue
            bucket["games"] += 1
            if st.get("any_hit"):
                bucket["any_wins"] += 1
            target_legs = [
                l for l in st.get("legs") or []
                if l.get("hits_target") and l.get("graded")
            ]
            if target_legs:
                bucket["target_route_games"] += 1
                if any(l.get("hit") for l in target_legs):
                    bucket["target_route_wins"] += 1
            bucket["graded"] += st.get("scorable_legs") or 0
            bucket["hits"] += st.get("hits") or 0
            bucket["misses"] += st.get("misses") or 0
            bucket["ungraded"] += st.get("ungraded") or 0
            for leg in st.get("legs") or []:
                if leg.get("graded"):
                    leg_stats["graded"] += 1
                    if leg.get("hit"):
                        leg_stats["hits"] += 1
                    else:
                        leg_stats["misses"] += 1
                elif leg.get("graded") is False:
                    leg_stats["ungraded"] += 1

    n = len(games)
    by_strategy = []
    for key, stats in strat_stats.items():
        if stats["games"] == 0:
            continue
        trg = stats.get("target_route_games") or 0
        by_strategy.append({
            "strategy": key,
            "label": STRATEGY_LABELS.get(key, key),
            "games": stats["games"],
            "slip_any_hit_rate": round(stats["any_wins"] / stats["games"], 3) if stats["games"] else None,
            "cashout_route_hit_rate": (
                round(stats["target_route_wins"] / trg, 3) if trg else None
            ),
            "cashout_route_games": trg,
            "leg_hit_rate": round(stats["hits"] / stats["graded"], 3) if stats["graded"] else None,
            "leg_miss_rate": round(stats["misses"] / stats["graded"], 3) if stats["graded"] else None,
            "legs_graded": stats["graded"],
            "legs_missed": stats["misses"],
            "legs_ungraded": stats["ungraded"],
        })
    by_strategy.sort(key=lambda x: -(x.get("leg_hit_rate") or 0))

    rec_hits = [g for g in games if g.get("recommended_hit") is not None]
    rec_acc = round(sum(1 for g in rec_hits if g["recommended_hit"]) / len(rec_hits), 3) if rec_hits else None

    return {
        "n_games": n,
        "leg_accuracy": round(leg_stats["hits"] / leg_stats["graded"], 3) if leg_stats["graded"] else None,
        "leg_miss_rate": round(leg_stats["misses"] / leg_stats["graded"], 3) if leg_stats["graded"] else None,
        "legs_graded": leg_stats["graded"],
        "legs_missed": leg_stats["misses"],
        "legs_ungraded": leg_stats["ungraded"],
        "result_breakdown": result_counts,
        "recommended_slip_accuracy": rec_acc,
        "by_strategy": by_strategy,
        "games": list(reversed(games)),
        "strategy_weights": _strategy_weights_from_stats(by_strategy),
    }


def _strategy_weights_from_stats(by_strategy: list[dict]) -> dict[str, float]:
    """Learning signal: boost strategies that actually hit, dampen chronic misses."""
    if not by_strategy:
        return {k: 1.0 for k in STRATEGY_KEYS}
    weights = {}
    for row in by_strategy:
        key = row["strategy"]
        rate = row.get("leg_hit_rate")
        slip = row.get("slip_any_hit_rate")
        if rate is None:
            weights[key] = 0.85
            continue
        combined = 0.55 * rate + 0.45 * (slip or rate)
        miss = row.get("leg_miss_rate") or (1 - rate)
        if miss > 0.45:
            combined *= 0.70
        elif rate >= 0.78:
            combined *= 1.08
        weights[key] = round(max(0.45, min(1.45, 0.7 + combined)), 3)
    for key in STRATEGY_KEYS:
        weights.setdefault(key, 1.0)
    return weights


def apply_strategy_learning(params: dict, rec_report: dict) -> dict:
    """Persist learned strategy weights into model params."""
    weights = rec_report.get("strategy_weights") or {}
    learning = {
        "version": REC_GRADING_VERSION,
        "strategy_weights": weights,
        "leg_accuracy": rec_report.get("leg_accuracy"),
        "recommended_slip_accuracy": rec_report.get("recommended_slip_accuracy"),
        "legs_graded": rec_report.get("legs_graded"),
        "by_strategy": rec_report.get("by_strategy"),
        "n_games": rec_report.get("n_games"),
    }
    params["rec_learning"] = learning
    from bet_placer.ml.activity_log import log_activity
    log_activity(
        "strategy_weights",
        "Updated strategy weights from graded recommendations",
        detail={
            "weights": weights,
            "n_games": rec_report.get("n_games"),
            "leg_accuracy": rec_report.get("leg_accuracy"),
            "target_hit_rate": next(
                (r.get("leg_hit_rate") for r in (rec_report.get("by_strategy") or [])
                 if r.get("strategy") == "target_hit"),
                None,
            ),
        },
    )
    return params
