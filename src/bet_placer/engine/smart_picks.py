"""Match picks: multiple situational bets per game, diverse market types."""

from __future__ import annotations

from bet_placer.ml.poisson import expected_goals, score_matrix

_MAX_SITUATIONAL = 3
_MIN_SITUATIONAL = 2
_MAX_EASY_MONEY = 1

# Easy money = high win-rate spots only. NOT the same as situational narratives.
_EASY_MONEY_CORE = frozenset({
    "match_winner", "double_chance", "draw_no_bet", "over_under_goals", "btts", "asian_handicap",
})
_EASY_MIN_PROB = 0.62
_EASY_MATCH_WINNER_MIN = 0.68
_EASY_MAX_IMPLIED_GAP = 0.18

_SLATE_CAPS: dict[str, int] = {
    "must_win": 5,
    "momentum": 4,
    "control_script": 2,
    "class_gap": 4,
    "striker_mismatch": 5,
    "star_dependent": 4,
    "rivalry": 3,
    "discipline": 4,
    "corner_siege": 3,
    "knockout": 4,
    "fade_public": 3,
    "open_game": 4,
    "cagey": 3,
    "streaky": 3,
    "fragile_fav": 3,
}

_SITUATIONAL_MARKETS = frozenset({
    "match_winner", "double_chance", "draw_no_bet", "over_under_goals",
    "btts", "asian_handicap", "corners", "cards", "player_goal",
    "team_first_goal", "half_time", "situation",
})


def _market_family(market: str) -> str:
    if market in ("match_winner", "double_chance", "draw_no_bet"):
        return "result"
    if market == "asian_handicap":
        return "handicap"
    if market == "over_under_goals":
        return "goals"
    if market == "btts":
        return "btts"
    if market in ("player_goal", "first_goal_team", "team_first_goal", "situation"):
        return "scorer"
    if market == "cards":
        return "cards"
    if market == "corners":
        return "corners"
    if market == "half_time":
        return "half"
    return market


def _selection_cluster(o: dict, home: str, away: str) -> str:
    from bet_placer.engine.bet_builder import _axis_dir

    axis, direction = _axis_dir(o, home, away)
    market = o.get("market") or "other"
    if axis == "result":
        return f"result:{direction}"
    if axis in ("goals", "btts"):
        return f"score_shape:{direction}"
    if market == "player_goal":
        return f"scorer:{(o.get('selection') or '').lower()}"
    if axis in ("corners", "cards", "half"):
        return f"{axis}:{direction}"
    return f"{market}:{direction}"


def first_goal_probs(match) -> tuple[float, float, float]:
    hl, al = expected_goals(match, apply_learned=True)
    M = score_matrix(hl, al, max_goals=8)
    p00 = float(M[0, 0])
    p_any = 1.0 - p00
    if p_any <= 0.01:
        return 0.33, 0.33, 0.34
    ph = (hl / (hl + al)) * p_any
    pa = (al / (hl + al)) * p_any
    return ph, pa, p00


def _stage_note(matchday: int | None) -> str:
    from bet_placer.data.wc_stages import stage_label
    if matchday is None:
        return ""
    return stage_label(matchday)


def _signal_key(angle: dict) -> str:
    sig = angle.get("signal", "")
    if sig.startswith("striker_mismatch"):
        return "striker_mismatch"
    if sig.startswith("star_dependent"):
        return "star_dependent"
    if sig.startswith("streaky"):
        return "streaky"
    if sig.startswith("momentum"):
        return "momentum"
    if sig.startswith("must_win") or sig == "must_win":
        return "must_win"
    if sig.startswith("redemption"):
        return "must_win"
    return sig or "other"


def _slate_ok(signal: str, slate: dict[str, int]) -> bool:
    return slate.get(signal, 0) < _SLATE_CAPS.get(signal, 12)


def _matches_angle(o: dict, angle: dict, home: str, away: str) -> bool:
    market = angle["market"]
    selection = angle["selection"]
    line = angle.get("line")
    player = angle.get("player")

    if market == "first_goal_team":
        team = home if selection == "home" else away
        ml = (o.get("market_label") or o.get("label") or "").lower()
        sel = (o.get("selection") or o.get("label") or "").lower()
        return (
            o.get("market") in ("team_first_goal", "situation")
            or ("first" in ml or "score first" in ml)
        ) and team.lower() in sel

    if market == "player_goal":
        if o.get("market") != "player_goal":
            return False
        return bool(player and player.lower() in (o.get("selection") or o.get("label") or "").lower())

    if market == "half_time":
        if o.get("market") != "half_time":
            return False
        return (o.get("selection") or "").lower() == selection

    if o.get("market") != market:
        return False

    if line is not None:
        oline = o.get("line")
        if oline is None or abs(float(oline) - float(line)) > 0.35:
            return False

    osel = (o.get("selection") or "").lower()
    if market in ("match_winner", "draw_no_bet", "asian_handicap", "double_chance"):
        return osel == selection
    if market in ("over_under_goals", "btts", "corners", "cards"):
        return selection in osel
    return osel == selection


def _on_stake(o: dict, angle: dict, ctx: dict) -> bool:
    overlay = ctx.get("stake_overlay")
    from bet_placer.engine.stake_odds import option_on_stake, stake_lines_usable, stake_overlay_ready
    if ctx.get("_board_source") == "stake":
        return True
    if not stake_overlay_ready(overlay):
        return False
    market = angle.get("market", "")
    if market == "first_goal_team":
        market = "team_first_goal"
        sel = angle.get("selection", "")
    elif market == "player_goal":
        sel = angle.get("player") or angle.get("selection", "")
    else:
        sel = angle.get("selection", "")
    return option_on_stake(market, sel, angle.get("line"), overlay)


def _resolve_first_goal_synthetic(
    angle: dict, home: str, away: str, match, pool: list[dict], ctx: dict | None = None,
) -> dict | None:
    selection = angle["selection"]
    team = home if selection == "home" else away
    ph, pa, _ = first_goal_probs(match)
    p = ph if selection == "home" else pa
    if p < 0.50:
        return None
    for o in pool:
        if _matches_angle(o, angle, home, away):
            return o
    overlay = (ctx or {}).get("stake_overlay") or {}
    odds_map = overlay.get("odds", {})
    stake_odds = odds_map.get(("team_first_goal", selection, None))
    odds = round(stake_odds, 2) if stake_odds and stake_odds > 1.0 else round(1.0 / max(p, 0.35), 2)
    return {
        "market": "team_first_goal" if stake_odds else "situation",
        "selection": selection,
        "label": f"{team} to score first",
        "odds": odds,
        "our_probability": round(p, 3),
        "our_probability_pct": round(p * 100, 1),
        "synthetic": not bool(stake_odds),
        "source": "stake" if stake_odds else "model",
    }


def _resolve_angle(
    angle: dict, pool: list[dict], home: str, away: str, match, ctx: dict | None = None,
) -> dict | None:
    if angle.get("market") == "first_goal_team":
        return _resolve_first_goal_synthetic(angle, home, away, match, pool, ctx)
    for o in pool:
        if _matches_angle(o, angle, home, away):
            if (o.get("our_probability") or 0) >= 0.45:
                return o
    return None


def _is_pool_eligible(o: dict, home: str, away: str) -> bool:
    import re
    m = o.get("market")
    if m not in _SITUATIONAL_MARKETS:
        return False
    ml = (o.get("market_label") or o.get("label") or "").lower()
    if any(t in ml for t in ("1st half", "2nd half", "range", "odd", "exact")):
        return False
    sel = (o.get("selection") or "").strip()
    if re.fullmatch(r"\d+\s*[-–]\s*\d+", sel):
        return False
    return True


def _build_easy_money_picks(
    pool: list[dict],
    thesis: dict,
    home: str,
    away: str,
    ctx: dict,
) -> list[dict]:
    """High win-rate spots only — separate from situational story bets.

    Bar is intentionally strict: if nothing clears it, we return [] rather than
    dressing up a 50/50 narrative as 'easy money'.
    """
    from bet_placer.engine.bet_builder import _axis_dir

    def implied(o: dict) -> float:
        return 1.0 / o["odds"] if o.get("odds", 0) > 1.0 else 1.0

    draw_scenario = bool(thesis.get("draw_scenario"))
    fade_public = bool(ctx.get("fade_public"))
    trending = ctx.get("trending_on")
    out: list[dict] = []
    used_clusters: set[str] = set()

    for o in pool:
        market = o.get("market") or ""
        if market not in _EASY_MONEY_CORE:
            continue
        if market in ("player_goal", "team_first_goal", "situation", "corners", "cards", "half_time"):
            continue

        p = o.get("our_probability") or 0
        min_p = _EASY_MATCH_WINNER_MIN if market == "match_winner" else _EASY_MIN_PROB
        if p < min_p:
            continue
        if abs(p - implied(o)) > _EASY_MAX_IMPLIED_GAP:
            continue

        tier = (o.get("verdict") or {}).get("tier")
        if tier in ("trap", "bad"):
            continue
        if crowd_hype(o, fade_public, trending, home, away):
            continue

        axis, direction = _axis_dir(o, home, away)
        if draw_scenario and market in ("match_winner", "draw_no_bet", "asian_handicap"):
            if axis == "result" and direction in ("home", "away"):
                continue

        tdir = {
            "result": thesis.get("result_dir"),
            "goals": thesis.get("goals_dir"),
            "btts": thesis.get("btts_dir"),
        }.get(axis)
        if tdir is not None and direction != tdir and direction != "nodraw":
            continue

        cluster = _selection_cluster(o, home, away)
        if cluster in used_clusters:
            continue
        used_clusters.add(cluster)

        pct = round(p * 100)
        out.append({
            **o,
            "pick_kind": "easy_money",
            "tag": " Easy money",
            "why": (
                f"High-confidence read (~{pct}% to land) on a core market that fits how this "
                "game should play — not a long-shot story bet."
            ),
            "reason": f"~{pct}% win chance · core market · thesis-aligned",
            "confidence_tier": "lock" if p >= 0.70 else "strong",
            "odds_source": o.get("source") or ("stake" if ctx.get("stake_priced") else "live_book"),
        })

    out.sort(key=lambda x: (-(x.get("our_probability") or 0), -(x.get("edge_pct") or 0)))
    return out[:_MAX_EASY_MONEY]


def build_smart_picks(
    flat: list[dict],
    home: str,
    away: str,
    match,
    probabilities: list,
    human_context: dict | None,
    thesis: dict | None = None,
    matchday: int | None = None,
    slate_usage: dict[str, int] | None = None,
) -> dict:
    from bet_placer.engine.analyst_read import analyst_read
    from bet_placer.engine.bet_builder import _match_thesis
    from bet_placer.engine.game_profile import profile_match

    ctx = human_context or {}
    from bet_placer.engine.stake_odds import option_on_stake, stake_lines_usable, stake_overlay_ready
    from bet_placer.engine.market_advisor import _match_sport
    from bet_placer.ml.craft_store import sport_min_probability

    sport = _match_sport(match)
    # Craft floor when a sport is bleeding; otherwise keep desk usable at 0.58
    sport_floor = max(0.58, float(sport_min_probability(sport, 0.58) or 0.58))

    overlay = ctx.get("stake_overlay")
    board_stake = ctx.get("_board_source") == "stake"
    # ponytail: blanking the whole desk when Stake is cold forced CAUTION / empty tabs
    stake_ok = stake_lines_usable(overlay, ctx) or board_stake

    slate = slate_usage if slate_usage is not None else {}
    thesis = thesis or _match_thesis(flat, home, away)
    fade_public = bool(ctx.get("fade_public"))
    trending = ctx.get("trending_on")

    def implied(o):
        return 1.0 / o["odds"] if o.get("odds", 0) > 1.0 else 1.0

    def plausible(o):
        p = o.get("our_probability")
        return p is not None and abs(p - implied(o)) <= 0.30

    from bet_placer.data.team_stars import player_goal_eligible

    pool = [
        o for o in flat
        if _is_pool_eligible(o, home, away) and plausible(o) and o.get("odds", 0) >= 1.15
        and float(o.get("our_probability") or 0) >= sport_floor
        and (
            o.get("market") != "player_goal"
            or player_goal_eligible(home, away, o.get("selection") or "")
        )
        and (
            not stake_ok
            or board_stake
            or option_on_stake(o.get("market"), o.get("selection"), o.get("line"), overlay)
        )
    ]

    profile = profile_match(match, probabilities, ctx)
    read = analyst_read(home, away, profile, ctx)
    angles = read.get("situational_angles") or read.get("angles") or []

    situational: list[dict] = []
    used_labels: set[str] = set()
    used_families: set[str] = set()
    used_clusters: set[str] = set()

    def enrich(o: dict, angle: dict, score: float) -> dict:
        return {
            **o,
            "why": angle["why"],
            "tag": angle.get("tag", " Situation"),
            "reason": angle["why"],
            "_score": score,
            "game_style": profile.get("style"),
            "pick_kind": "situational",
            "signal": angle.get("signal"),
            "pick_type": angle.get("market"),
            "odds_source": o.get("source") or ("stake" if ctx.get("stake_priced") else "live_book"),
        }

    ranked = sorted(angles, key=lambda a: -a.get("priority", 0))

    for angle in ranked:
        if len(situational) >= _MAX_SITUATIONAL:
            break
        sig = _signal_key(angle)
        if not _slate_ok(sig, slate):
            continue
        fam = _market_family(angle.get("market", ""))
        if fam in used_families and len(situational) >= _MIN_SITUATIONAL:
            continue
        if stake_ok and not _on_stake({}, angle, ctx) and angle.get("market") != "first_goal_team":
            continue
        o = _resolve_angle(angle, pool, home, away, match, ctx)
        if not o:
            continue
        if crowd_hype(o, fade_public, trending, home, away):
            continue
        label = (o.get("label") or "").lower()
        cluster = _selection_cluster(o, home, away)
        if label in used_labels:
            continue
        if cluster in used_clusters:
            continue
        p = o.get("our_probability") or 0
        if p < 0.44:
            continue
        used_labels.add(label)
        used_families.add(fam)
        used_clusters.add(cluster)
        situational.append(enrich(o, angle, p * 50 + angle.get("priority", 5) * 4))
        slate[sig] = slate.get(sig, 0) + 1

    # Second pass: fill to minimum — slate caps are for the page, not this match
    if len(situational) < _MIN_SITUATIONAL:
        for angle in ranked:
            if len(situational) >= _MIN_SITUATIONAL:
                break
            o = _resolve_angle(angle, pool, home, away, match, ctx)
            if not o:
                continue
            label = (o.get("label") or "").lower()
            cluster = _selection_cluster(o, home, away)
            if label in used_labels:
                continue
            if cluster in used_clusters:
                continue
            if crowd_hype(o, fade_public, trending, home, away):
                continue
            if (o.get("our_probability") or 0) < 0.40:
                continue
            used_labels.add(label)
            used_clusters.add(cluster)
            situational.append(enrich(o, angle, 35))

    # Third pass: any story angle at all
    if not situational and ranked:
        for angle in ranked:
            o = _resolve_angle(angle, pool, home, away, match, ctx)
            if o and (o.get("our_probability") or 0) >= 0.38:
                cluster = _selection_cluster(o, home, away)
                if cluster in used_clusters:
                    continue
                used_clusters.add(cluster)
                situational.append(enrich(o, angle, 30))
                break

    situational.sort(key=lambda x: -x.get("_score", 0))

    unified = [{k: v for k, v in o.items() if k != "_score"} for o in situational[:_MAX_SITUATIONAL]]
    easy_money = _build_easy_money_picks(pool, thesis, home, away, ctx)

    stage = _stage_note(matchday)
    if thesis:
        thesis = dict(thesis)
        thesis["easy_money"] = bool(easy_money)
        thesis["game_style"] = profile.get("style")
        thesis["analyst_summary"] = read.get("summary", "")[:280]
        if easy_money:
            thesis["easy_money_note"] = easy_money[0].get("why", "")

    return {
        "easy_money": easy_money,
        "situational_picks": unified,
        "smart_picks": unified,
        "unified_picks": easy_money + [p for p in unified if p.get("label") not in {e.get("label") for e in easy_money}],
        "parlay_suggestion": _parlay_from_picks((easy_money or unified)[:3], home, away),
        "thesis": thesis,
        "game_profile": profile,
        "analyst_read": read,
        "stage_note": stage,
        "skip_reasons": (
            [] if (easy_money or situational)
            else (["No high-confidence or situational market resolved."] if stake_ok else ["Model-priced slate is thin — connect Stake for more lines."])
        ),
        "spotlight": (easy_money[0] if easy_money else unified[0]) if (easy_money or unified) else None,
        "easy_money_note": (
            None if easy_money
            else (
                "No bet cleared the high-confidence bar for this match."
                if stake_ok
                else "High-confidence picks use model prices until Stake is connected."
            )
        ),
        "stake_priced": stake_ok,
    }


def crowd_hype(o, fade_public: bool, trending: str | None, home: str, away: str) -> bool:
    from bet_placer.engine.bet_builder import _axis_dir
    if not fade_public or not trending:
        return False
    axis, d = _axis_dir(o, home, away)
    if axis != "result" or d not in ("home", "away"):
        return False
    hyped = home if d == "home" else away
    return hyped == trending


def _parlay_from_picks(picks: list[dict], home: str, away: str) -> dict | None:
    legs = [p for p in picks if (p.get("our_probability") or 0) >= 0.48 and p.get("odds", 0) >= 1.15]
    if len(legs) < 2:
        return None
    prob = 1.0
    odds = 1.0
    for p in legs[:3]:
        prob *= p.get("our_probability") or 0.5
        odds *= p.get("odds") or 1.0
    return {
        "legs": [{"label": p.get("label"), "odds": p.get("odds"), "probability_pct": p.get("our_probability_pct")} for p in legs[:3]],
        "combined_odds": round(odds, 2),
        "combined_probability_pct": round(prob * 100, 1),
        "note": "Illustrative only — not a verified Stake combo. Check Stake Combos for real SGM prices.",
    }


def options_to_flat(options) -> list[dict]:
    flat = []
    for o in options:
        flat.append({
            "market": o.market,
            "selection": o.selection,
            "line": o.line,
            "label": o.label,
            "market_label": o.label,
            "odds": o.odds,
            "our_probability": o.our_probability,
            "our_probability_pct": round(o.our_probability * 100, 1),
            "edge_pct": o.edge_pct,
            "source": o.source,
            "verdict": {"ev_pct": o.ev_pct, "tier": o.recommendation},
        })
    return flat


def align_slip_with_picks(slip_dict: dict, picks: dict) -> dict:
    if not slip_dict or not picks:
        return slip_dict
    easy = picks.get("easy_money") or []
    unified = picks.get("unified_picks") or picks.get("situational_picks") or []
    slip_dict["unified_picks"] = unified
    slip_dict["situational_picks"] = picks.get("situational_picks") or unified
    slip_dict["easy_money"] = easy
    slip_dict["spotlight_pick"] = picks.get("spotlight")
    slip_dict["parlay_suggestion"] = picks.get("parlay_suggestion")
    slip_dict["game_profile"] = picks.get("game_profile")
    slip_dict["match_stories"] = (picks.get("analyst_read") or {}).get("stories", [])
    slip_dict["match_thesis"] = picks.get("thesis")
    curated = slip_dict.get("curated_picks") or {}
    primary = curated.get("primary")
    if primary and slip_dict.get("verdict") != "SKIP_MATCH":
        slip_dict["recommended_strategy"] = primary.get("tab_id") or primary.get("id") or "singles_focus"
        slip_dict["recommended_slip_id"] = primary.get("option_id") or primary.get("id")
        return slip_dict
    if easy and slip_dict.get("verdict") != "SKIP_MATCH":
        slip_dict["easy_money_headline"] = easy[0].get("label")
        slip_dict["easy_money_why"] = easy[0].get("why")
    if not easy:
        slip_dict["easy_money_note"] = "No bet cleared the high-confidence bar for this match — situational picks are lower conviction."
    if easy and slip_dict.get("strategy_plans", {}).get("singles_focus"):
        plans = slip_dict["strategy_plans"]["singles_focus"]
        if plans and isinstance(plans, list):
            plans[0]["easy_money_legs"] = easy
    return slip_dict
