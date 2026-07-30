"""Per-match spread card  -  how you actually bet.

2–4 separate Stake singles on a coherent spread: anchor, support, swing,
plus one target lotto route that can pay the cashout goal if it wins alone.
Other legs are budget/thesis-sized  -  not every ticket must hit the full target.
No fake same-game multis (never multiplies single-line odds).
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from bet_placer.engine.bet_portfolio import (
    _combo_contradicts,
    _leg,
    _prob_all_legs_lose,
    _reason,
    _round,
    format_inr,
)
from bet_placer.engine.game_profile import game_fit_score, is_generic_trap

_MIN_STAKE = 10                 # Stake's typical INR min
_MIN_ANCHOR_STAKE = 40          # anchors need real skin, not lottery tickets
_MAX_DEPLOY_PCT = 0.80          # never bet more than 80% of budget
_MIN_RESERVE_PCT = 0.15         # always keep at least this untouched

# Tier definitions  -  odds/probability windows + share of deployable budget.
# Roles selected in this order. `budget_share` is the tier's slice of the
# deployable pot; `target_share` is how much of the user's cashout goal
# each ticket alone should return if it wins.
_TIERS = (
    {"role": "anchor",   "label": "Anchor",    "odds_min": 1.30, "odds_max": 2.10, "min_prob": 0.52, "budget_share": 0.50, "target_share": 0.25, "max_ticket_pct": 0.50},
    {"role": "support",  "label": "Support",   "odds_min": 1.65, "odds_max": 3.20, "min_prob": 0.32, "budget_share": 0.30, "target_share": 0.35, "max_ticket_pct": 0.35},
    {"role": "swing",    "label": "Swing",     "odds_min": 2.20, "odds_max": 5.50, "min_prob": 0.18, "budget_share": 0.10, "target_share": 0.50, "max_ticket_pct": 0.12},
    {"role": "lottery",  "label": "Longshot",  "odds_min": 3.50, "odds_max": 15.0, "min_prob": 0.10, "budget_share": 0.06, "target_share": 0.80, "max_ticket_pct": 0.08},
    {"role": "lottery2", "label": "Longshot",  "odds_min": 5.00, "odds_max": 30.0, "min_prob": 0.06, "budget_share": 0.04, "target_share": 1.00, "max_ticket_pct": 0.06},
)

# Rank-grid variant notes  -  generic; replace with leg names in the UI.
_GENERIC_VARIANT_NOTES = frozenset({
    "Best mix", "Alt support line", "Alt swing line", "Alt longshot", "Alt anchor",
    "Support + swing mix", "More longshots", "Safer anchor mix",
})


def _opt_get(opt, key: str, default=None):
    if isinstance(opt, dict):
        return opt.get(key, default)
    return getattr(opt, key, default)


def _opt_label(opt) -> str:
    return str(_opt_get(opt, "label") or "")


def _opt_market(opt) -> str:
    return str(_opt_get(opt, "market") or "")


def _opt_odds(opt) -> float:
    return float(_opt_get(opt, "odds") or 0)


def _opt_prob(opt) -> float:
    return float(_opt_get(opt, "our_probability") or 0)


def path_label_from_legs(legs: list, max_names: int = 3) -> str:
    """Human-readable path id from the actual tickets  -  not tier template names."""
    names = [l.get("label") or "" for l in legs if l.get("label")]
    if not names:
        return ""
    n = len(names)
    if n == 1:
        return names[0]
    short = ", ".join(names[:max_names])
    if n > max_names:
        short += f" +{n - max_names} more"
    if n == 2:
        return short
    return f"{n}-leg spread · {short}"


# ─────────────────────────── pool + scoring ────────────────────────────

def _match_card_pool(
    options: list, overlay: dict | None, stake_only: bool, home: str, away: str,
    *, board_stake: bool = False,
) -> list:
    """Wider pool than the regular slip tabs  -  keeps longshots the safety filters reject."""
    from bet_placer.data.team_stars import player_goal_eligible
    from bet_placer.engine.stake_odds import option_on_stake, stake_overlay_ready
    from bet_placer.markets.labels import is_core_bet_market

    if not stake_overlay_ready(overlay) and not board_stake:
        if stake_only:
            return []

    pool = []
    for o in options:
        if not is_core_bet_market(o.market):
            continue
        if is_generic_trap(o):
            continue
        if o.market == "player_goal" and not player_goal_eligible(home, away, o.selection):
            continue
        if stake_overlay_ready(overlay) and not option_on_stake(o.market, o.selection, o.line, overlay):
            continue
        if o.our_probability < 0.02:
            continue
        pool.append(o)
    return pool


def _human_context_score_boost(opt, profile: dict, home: str, away: str, ctx: dict) -> float:
    """Fan read, stakes, morale, chemistry  -  heavier when they matter most."""
    boost = 0.0
    label = _opt_label(opt).lower()
    rating_gap = float(profile.get("rating_gap") or 0)
    style = profile.get("style") or ""
    fav = (profile.get("favorite") or "").lower()
    heavy_fav = style == "dominant_favorite" and rating_gap >= 15
    knockout = bool(ctx.get("is_knockout"))
    must_win = bool(ctx.get("home_must_win") or ctx.get("away_must_win"))

    fan = (ctx.get("fan_take") or "").lower()
    if fan and len(fan) > 20:
        for team in (home.lower(), away.lower()):
            if team in fan and team in label:
                boost += 22 if heavy_fav else 14
        if "draw" in fan and "draw" in label:
            boost += 12

    if ctx.get("home_must_win") and home.lower() in label:
        boost += 16 if knockout else 10
    if ctx.get("away_must_win") and away.lower() in label:
        boost += 16 if knockout else 10

    morale = ctx.get("morale") or {}
    mgap = abs(float(morale.get("home", 5)) - float(morale.get("away", 5)))
    if mgap >= 3:
        if home.lower() in label and morale.get("home", 5) > morale.get("away", 5):
            boost += 10 + mgap
        if away.lower() in label and morale.get("away", 5) > morale.get("home", 5):
            boost += 10 + mgap

    if ctx.get("fade_public") and ctx.get("trending_on"):
        trend = (ctx.get("trending_on") or "").lower()
        if trend in label:
            boost -= 18
        elif fav and fav in label and trend != fav:
            boost += 14

    for note in (ctx.get("chemistry_notes") or [])[:2]:
        n = str(note).lower()
        if n and any(w in label for w in n.split()[:5] if len(w) > 3):
            boost += 14 if heavy_fav or must_win else 10

    thesis = ctx.get("match_thesis") or {}
    if isinstance(thesis, dict):
        rd = thesis.get("result_dir")
        if rd == "home" and home.lower() in label:
            boost += 8
        if rd == "away" and away.lower() in label:
            boost += 8

    home_cup = ctx.get("home_cup_win_pct")
    away_cup = ctx.get("away_cup_win_pct")
    if home_cup is not None and away_cup is not None:
        cup_gap = abs(float(home_cup) - float(away_cup))
        if cup_gap >= 8 and heavy_fav:
            if float(home_cup) > float(away_cup) and home.lower() in label:
                boost += min(22, cup_gap * 1.2)
            if float(away_cup) > float(home_cup) and away.lower() in label:
                boost += min(22, cup_gap * 1.2)

    gs = (ctx.get("group_stakes") or "").lower()
    if gs and knockout and ("win" in label or fav in label):
        boost += 6

    # World Cup form  -  xG/GF/GC from match stats snapshot
    form = ctx.get("form_snapshot") or {}
    for side, team in (("home", home), ("away", away)):
        fs = form.get(side) or {}
        if team.lower() not in label:
            continue
        xg, xga = float(fs.get("xg") or 0), float(fs.get("xga") or 0)
        gf, gc = float(fs.get("goals_scored") or 0), float(fs.get("goals_conceded") or 0)
        if xg > xga + 0.25 and "over" in label:
            boost += 10
        if xga < xg - 0.2 and "under" in label and team.lower() in label:
            boost += 8
        if gf >= 2 and "over" in label:
            boost += 6
        if gc <= 0.8 and "under" in label:
            boost += 6

    # Analyst / pundit angles (playstyle, rivalry, form stories)
    read = ctx.get("analyst_read") or {}
    summary = (read.get("summary") or "").lower()
    if summary:
        for kw, amt in (
            ("low scoring", 10), ("tight", 8), ("under", 8),
            ("open game", 10), ("high scoring", 10), ("over", 8),
            ("grudge", 12), ("rivalry", 12), ("must win", 14),
        ):
            if kw in summary and kw.split()[0] in label:
                boost += amt
    for angle in (read.get("angles") or [])[:6]:
        al = (angle.get("selection") or angle.get("label") or "").lower()
        if al and al in label:
            boost += 18
        m = (angle.get("market") or "").lower()
        if m and m.replace("_", " ") in label.replace("_", " "):
            boost += 8

    # Playstyle fit from game profile narrative
    narrative = (profile.get("narrative") or "").lower()
    style = profile.get("style") or ""
    if style == "low_scoring" and "under" in label:
        boost += 12
    elif style == "high_scoring" and "over" in label:
        boost += 12
    elif style == "dominant_favorite" and fav and fav in label:
        boost += 10
    elif style == "tight" and ("draw" in label or "double chance" in label):
        boost += 10
    if narrative and any(w in label for w in narrative.split()[:6] if len(w) > 4):
        boost += 8

    return boost


def _score_option(opt, profile: dict, home: str, away: str, ctx: dict) -> float:
    if is_generic_trap(opt):
        return -999.0
    score = game_fit_score(opt, profile, home, away)
    score += float(_opt_get(opt, "ev_pct", 0) or 0) * 0.4
    labels = {
        (p.get("label") or "").lower()
        for p in (ctx.get("unified_picks") or []) + (ctx.get("easy_money_picks") or [])
    }
    if _opt_label(opt).lower() in labels:
        score += 25
    score += _human_context_score_boost(opt, profile, home, away, ctx)
    verdict = _opt_get(opt, "verdict") or {}
    tier = verdict.get("tier") if isinstance(verdict, dict) else None
    if tier in ("value", "strong"):
        score += 8
    elif tier in ("trap", "bad"):
        score -= 25
    return score


def _option_result_side(opt, home: str, away: str) -> str | None:
    from bet_placer.engine.card_coherence import _result_side
    return _result_side(
        {"market": opt.market, "selection": opt.selection, "label": opt.label},
        home, away,
    )


def _handicap_line_value(opt) -> float | None:
    """Signed handicap from label/selection (e.g. -1.5, +2.25)."""
    import re
    text = f"{getattr(opt, 'selection', '') or ''} {getattr(opt, 'label', '') or ''}".lower()
    m = re.search(r"handicap\s*([+-]?\d+\.?\d*)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"\(([+-]?\d+\.?\d*)\)", text)
    if m and "handicap" in text:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _is_sensible_pick(opt, tier_role: str) -> bool:
    """Block bizarre extreme lines on core tiers  -  keep spreads realistic."""
    m = (opt.market or "").lower()
    if m == "asian_handicap":
        line = _handicap_line_value(opt)
        if line is not None:
            caps = {
                "anchor": 1.5, "support": 2.0, "swing": 2.5,
                "target_lotto": 3.5, "lottery": 3.0, "lottery2": 3.5,
            }
            cap = caps.get(tier_role, 2.5)
            if abs(line) > cap:
                return False
    if tier_role in ("anchor", "support") and m not in (
        "match_winner", "draw_no_bet", "asian_handicap", "double_chance",
        "over_under_goals", "btts", "half_time", "corners", "cards",
    ):
        return False
    return True


def _thesis_side_from_ctx(ctx: dict | None) -> str | None:
    """Map match_thesis dict to home / away / neutral lean."""
    thesis = (ctx or {}).get("match_thesis") or {}
    if thesis.get("draw_scenario"):
        return "neutral"
    rd = thesis.get("result_dir")
    if rd in ("home", "away"):
        return rd
    if thesis.get("home", 0) >= thesis.get("away", 0) + 0.08:
        return "home"
    if thesis.get("away", 0) >= thesis.get("home", 0) + 0.08:
        return "away"
    return None


def _aligns_thesis(opt, thesis: str | None, home: str, away: str) -> bool:
    """Filter picks so each path tells one story (home lean, away lean, or no result)."""
    if not thesis or thesis == "open":
        return True
    m = (opt.market or "").lower()
    lbl = (opt.label or "").lower()
    if m in ("exact_score", "correct_score") or "correct score" in lbl:
        from bet_placer.engine.card_coherence import score_aligns_thesis
        return score_aligns_thesis(opt, thesis, home, away)
    side = _option_result_side(opt, home, away)
    if thesis == "neutral":
        return m not in ("match_winner", "draw_no_bet", "asian_handicap", "double_chance", "half_time")
    if thesis in ("home", "away"):
        opp = away if thesis == "home" else home
        fav = home if thesis == "home" else away
        pick_text = f"{lbl} {(getattr(opt, 'selection', '') or '').lower()}".strip()
        if m in ("over_under_goals", "btts", "corners", "cards"):
            return True
        if m == "player_goal" or "goalscorer" in lbl or " scorer" in lbl:
            if opp.lower() in pick_text:
                return False
            from bet_placer.data.team_stars import player_on_squad
            pick_name = getattr(opt, "selection", None) or getattr(opt, "label", "") or ""
            fav_team = home if thesis == "home" else away
            opp_team = away if thesis == "home" else home
            if player_on_squad(opp_team, pick_name) and not player_on_squad(fav_team, pick_name):
                return False
        if m in ("match_winner", "draw_no_bet", "asian_handicap", "half_time"):
            # Never pair a home/away lean with an outright Draw (or wrong side)
            if side == "draw":
                return False
            return side == thesis
        if m == "double_chance":
            lbl = (opt.label or "").lower()
            fav = home.lower() if thesis == "home" else away.lower()
            opp = away.lower() if thesis == "home" else home.lower()
            if opp in lbl and fav not in lbl:
                return False
            # "Draw or Away" fights a home lean
            if side == "draw":
                return False
            return side in (thesis, None)
        return True
    return True


def _route_odds_candidates(ctx: dict, pool: list, budget: float, target: float) -> list[float]:
    """Odds levels we may need to pair with an insurance anchor."""
    odds_set: set[float] = set()
    overlay = ctx.get("stake_overlay")
    if overlay:
        for c in overlay.get("stake_combos") or []:
            o = float(c.get("odds") or 0)
            if 3.0 <= o <= 14.0:
                odds_set.add(o)
    for opt in pool:
        o = float(getattr(opt, "odds", 0) or 0)
        if o >= 3.5:
            odds_set.add(o)
    if not odds_set:
        odds_set.add(max(3.5, target / max(budget * 0.55, 1)))
    return sorted(odds_set, key=lambda o: -abs(math.log(max(o, 1.01)) - math.log(6.0)))


def _pick_feasible_anchor(
    pool: list,
    picked: list,
    profile: dict,
    home: str,
    away: str,
    ctx: dict,
    budget: float,
    target: float,
    thesis: str | None = None,
    rank: int = 0,
) -> Any | None:
    """Anchor that pairs with a real profit-sized swing combo within deploy cap."""
    from bet_placer.engine.bet_portfolio import (
        estimate_balanced_spread_stakes,
        target_profit_inr,
    )
    from bet_placer.engine.card_coherence import stake_combo_fits_card
    from bet_placer.engine.stake_sgm import estimate_stake_combo_probability

    target_profit = float(ctx.get("target_profit_inr") or target_profit_inr(budget, target))
    max_deploy = budget * _MAX_DEPLOY_PCT
    tier = _TIERS[0]
    used_markets = {p.market for p in picked}
    used_labels = {(p.label or "").lower() for p in picked}
    overlay = ctx.get("stake_overlay") or {}
    combos = [
        c for c in (overlay.get("stake_combos") or [])
        if 3.0 <= float(c.get("odds") or 0) <= 14.0
    ]
    combos.sort(
        key=lambda c: -abs(math.log(max(float(c.get("odds") or 1), 1.01)) - math.log(6.0)),
    )
    feasible: list[tuple] = []

    for opt in pool:
        if opt in picked or (opt.label or "").lower() in used_labels:
            continue
        if not _aligns_thesis(opt, thesis, home, away):
            continue
        if opt.market in used_markets:
            continue
        a_odds = float(opt.odds or 0)
        if a_odds < tier["odds_min"] or a_odds > 3.50:
            continue
        min_prob = tier["min_prob"] if a_odds <= tier["odds_max"] else 0.32
        if float(opt.our_probability or 0) < min_prob:
            continue
        if not _is_sensible_pick(opt, "anchor"):
            if opt.market != "asian_handicap":
                continue
            line = _handicap_line_value(opt)
            if line is None or abs(line) > 3.5:
                continue
        if _combo_contradicts(tuple(picked + [opt]), home, away):
            continue

        best: tuple[float, float, dict] | None = None
        anchor_leg = _leg(opt, _MIN_ANCHOR_STAKE, "anchor", "", home, away)
        for combo in combos[:80]:
            c_odds = float(combo.get("odds") or 0)
            if c_odds < 3.5 or c_odds > 9.0:
                continue
            if not stake_combo_fits_card(combo, [anchor_leg], home, away):
                continue
            est = estimate_balanced_spread_stakes(a_odds, c_odds, target_profit)
            if not est or est[0] + est[1] > max_deploy:
                continue
            hit_prob = estimate_stake_combo_probability(combo, pool, home, away)
            if hit_prob < 0.06:
                continue
            combo_score = hit_prob * 2 - est[1] / budget
            if best is None or combo_score > best[0]:
                best = (combo_score, est[0], est[0] + est[1], combo)

        if best is None:
            for r_odds in _route_odds_candidates(ctx, pool, budget, target)[:20]:
                if r_odds < 3.5 or r_odds > 9.0:
                    continue
                est = estimate_balanced_spread_stakes(a_odds, r_odds, target_profit)
                if est and est[0] + est[1] <= max_deploy:
                    best = (0.5, est[0], est[0] + est[1], {})
                    break
        if best is None:
            continue
        prob = float(opt.our_probability or 0)
        if prob < 0.35:
            continue
        sc = _score_option(opt, profile, home, away, ctx) + prob * 120 + best[0] * 5
        if prob < tier["min_prob"]:
            sc -= (tier["min_prob"] - prob) * 80
        if a_odds > tier["odds_max"]:
            sc -= 40
        anchor_stake_est = best[1] if best else 999
        feasible.append((sc, prob, anchor_stake_est, opt))

    if feasible:
        feasible.sort(key=lambda x: (x[1], x[0]), reverse=True)
        if rank < len(feasible):
            return feasible[rank][3]

    return None


def _pick_for_tier(pool, tier, picked, profile, home, away, ctx, rank: int = 0, thesis: str | None = None) -> Any | None:
    used_markets = {p.market for p in picked}
    used_labels = {(p.label or "").lower() for p in picked}
    cands: list[tuple] = []

    # For longshots, look at situational/unified picks first (penalty scorer, upset etc.)
    if tier["role"].startswith("lottery"):
        for pick in (ctx.get("unified_picks") or []):
            odds = float(pick.get("odds") or 0)
            if odds < tier["odds_min"] or odds > tier["odds_max"]:
                continue
            label = (pick.get("label") or "").lower()
            for opt in pool:
                if opt in picked or (opt.label or "").lower() in used_labels:
                    continue
                if (opt.label or "").lower() == label:
                    if not _aligns_thesis(opt, thesis, home, away):
                        continue
                    if not _is_sensible_pick(opt, tier["role"]):
                        continue
                    if not _combo_contradicts(tuple(picked + [opt]), home, away):
                        return opt

    for opt in pool:
        if opt in picked or (opt.label or "").lower() in used_labels:
            continue
        if not _aligns_thesis(opt, thesis, home, away):
            continue
        # Never repeat the same market twice unless we're on a lottery tier
        if opt.market in used_markets and not tier["role"].startswith("lottery"):
            continue
        if opt.odds < tier["odds_min"] or opt.odds > tier["odds_max"]:
            continue
        if opt.our_probability < tier["min_prob"]:
            continue
        if not _is_sensible_pick(opt, tier["role"]):
            continue
        if _combo_contradicts(tuple(picked + [opt]), home, away):
            continue
        sc = _score_option(opt, profile, home, away, ctx)
        if sc < -100:
            continue
        cands.append((sc, opt))

    if not cands:
        return None
    cands.sort(key=lambda x: x[0], reverse=True)
    if rank < len(cands):
        return cands[rank][1]
    return None


# ─────────────────────────── stake allocation ──────────────────────────

def _round_stake(x: float) -> float:
    """Stake INR increments  -  nearest ₹10, min ₹10."""
    return max(_MIN_STAKE, round(x / 10.0) * 10.0)


def _size_leg(opt_or_leg, target: float, budget: float, tier: dict) -> float:
    """
    Pick the stake that gets us CLOSEST to the intended tier return, without
    ever exceeding the per-ticket budget cap.

    Two candidates:
      * `target_share * target / odds`   -  sized to contribute this share of the goal
      * `budget_share * deploy`          -  flat proportional slice of the bankroll
    Take the smaller of the two, floored by tier minimum, capped by max_ticket_pct.
    """
    odds = float(opt_or_leg.get("odds") if isinstance(opt_or_leg, dict) else opt_or_leg.odds)
    if odds <= 1.0:
        return 0.0
    deploy = budget * _MAX_DEPLOY_PCT
    by_target = tier["target_share"] * target / odds
    by_budget = tier["budget_share"] * deploy
    stake = min(by_target, by_budget)
    stake = _round_stake(stake)
    if tier["role"] == "anchor":
        stake = max(stake, _MIN_ANCHOR_STAKE)
    cap = _round_stake(budget * tier["max_ticket_pct"])
    stake = min(stake, cap)
    return max(_MIN_STAKE, stake)


def _pick_stake_combos(
    overlay: dict | None,
    picked_labels: set,
    max_n: int = 1,
    *,
    card_legs: list[dict] | None = None,
    home: str = "",
    away: str = "",
) -> list[dict]:
    """Real Stake combos aligned with the card  -  at most one small SGM add-on."""
    if not overlay:
        return []
    from bet_placer.engine.card_coherence import stake_combo_fits_card

    combos = overlay.get("stake_combos") or []
    # Sort: 3x–15x sweet spot first, then price
    def key(c):
        odds = float(c.get("odds") or 0)
        sweetness = -abs(math.log(max(odds, 1.01)) - math.log(6.0))
        return (sweetness, odds)
    picked: list[dict] = []
    for c in sorted(combos, key=key, reverse=True):
        odds = float(c.get("odds") or 0)
        if odds < 2.5 or odds > 25.0:
            continue
        lbl = (c.get("label") or c.get("stake_market") or "").lower()
        if any(lbl.startswith(p[:15]) for p in picked_labels):
            continue
        if card_legs and home and away and not stake_combo_fits_card(c, card_legs, home, away):
            continue
        picked.append(c)
        if len(picked) >= max_n:
            break
    return picked


def _partial_win_returns(legs: list[dict], k: int) -> float:
    """Best return if exactly k of the picks land (top-k highest gross returns)."""
    returns = sorted((float(l["stake_inr"]) * float(l["odds"]) for l in legs), reverse=True)
    return sum(returns[:k])


def _prob_at_least_k(probs: list[float], k: int) -> float:
    """P(at least k of the independent events happen). Small n → enumerate directly."""
    n = len(probs)
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    total = 0.0
    for r in range(k, n + 1):
        for combo in combinations(range(n), r):
            p = 1.0
            for i in range(n):
                p *= probs[i] if i in combo else (1 - probs[i])
            total += p
    return total


def _scenarios_card(legs: list[dict], reserve: float, budget: float, target: float) -> dict:
    total = sum(l["stake_inr"] for l in legs)
    probs = [l["our_probability"] for l in legs]
    p_all_lose = _prob_all_legs_lose(legs)
    p_any = 1.0 - p_all_lose
    p_2_plus = _prob_at_least_k(probs, 2) if len(probs) >= 2 else 0.0

    ev = sum(l["stake_inr"] * (l["odds"] - 1) * l["our_probability"] - l["stake_inr"] * (1 - l["our_probability"]) for l in legs)

    return_1 = _partial_win_returns(legs, 1)
    return_2 = _partial_win_returns(legs, min(2, len(legs)))
    return_all = sum(l["stake_inr"] * l["odds"] for l in legs)

    profit_1 = return_1 - total
    profit_2 = return_2 - total
    profit_all = return_all - total

    return {
        "worst_case": {
            "label": "All miss",
            "profit_inr": round(-total, 0),
            "description": (
                f"Every ticket loses (~{p_all_lose:.0%})  -  down {format_inr(total)}. "
                f"{format_inr(reserve)} stays unbet, no bankroll wipeout."
            ),
        },
        "likely_case": {
            "label": "Some land",
            "profit_inr": round(profit_1, 0),
            "description": (
                f"~{p_any:.0%} chance ≥1 hits · ~{p_2_plus:.0%} chance ≥2 hit. "
                f"1 win of the best line: {'+' if profit_1 >= 0 else ''}{format_inr(profit_1)} net."
            ),
        },
        "best_case": {
            "label": "Multiple hit",
            "profit_inr": round(profit_all, 0),
            "description": (
                f"1 hits → net {'+' if profit_1 >= 0 else ''}{format_inr(profit_1)} · "
                f"2 hit → net {'+' if profit_2 >= 0 else ''}{format_inr(profit_2)} · "
                f"all hit → net {'+' if profit_all >= 0 else ''}{format_inr(profit_all)}"
            ),
        },
        "expected_value_inr": round(ev, 0),
        "p_any_win_pct": round(p_any * 100, 1),
        "p_two_or_more_win_pct": round(p_2_plus * 100, 1),
        "return_if_1": round(return_1, 0),
        "return_if_2": round(return_2, 0),
        "return_if_all": round(return_all, 0),
    }


# ─────────────────────────── main builder ──────────────────────────────

def _n_legs(betting_style: dict | None, target_multiplier: float, budget: float = 300) -> int:
    from bet_placer.engine.bet_portfolio import max_tickets_for_budget

    # Match-discretion ticket count — Settings style does not drive main cards
    cap = max_tickets_for_budget(budget)
    base = 3 if target_multiplier >= 3.5 else 2
    if target_multiplier >= 4.0:
        base = min(cap, base + 1)
    return max(base, min(base, cap))


def _min_stake_for_target(odds: float, target: float) -> float:
    """Stake (INR) so this single pays at least the cashout goal."""
    return max(_MIN_STAKE, math.ceil(target / max(odds, 1.01) / 10) * 10)


def _build_target_hit_legs(
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    ctx: dict,
    *,
    thesis: str | None = None,
    max_legs: int = 4,
    min_legs: int = 2,
) -> list[dict]:
    """Separate singles  -  each sized to hit the profit target if it wins alone."""
    from bet_placer.engine.bet_portfolio import (
        max_tickets_for_budget,
        size_independent_route_stakes,
        target_profit_inr,
    )

    profit_goal = target_profit_inr(budget, target)
    deploy_cap = budget * 0.88
    floor_net = profit_goal * 0.95
    max_legs = min(max_legs, max_tickets_for_budget(budget))

    cands: list[tuple[float, Any, float]] = []
    for opt in pool:
        if not _aligns_thesis(opt, thesis, home, away):
            continue
        if is_generic_trap(opt):
            continue
        odds = float(opt.odds or 0)
        if odds < 1.12:
            continue
        solo = size_independent_route_stakes([odds], budget, profit_goal)
        if not solo:
            continue
        stake = solo[0]
        if float(opt.our_probability or 0) < 0.04:
            continue
        score = float(opt.our_probability or 0) + game_fit_score(opt, profile, home, away) * 0.05
        tier = (getattr(opt, "verdict", None) or {}).get("tier")
        if tier in ("trap", "bad"):
            score -= 0.15
        elif tier in ("value", "strong"):
            score += 0.04
        cands.append((score, opt, stake))

    cands.sort(key=lambda x: -x[0])
    if len(cands) < min_legs:
        return []

    best_legs: list[dict] = []
    best_p_any = -1.0
    top = [c[1] for c in cands[:28]]

    for n in range(min_legs, min(max_legs, len(top)) + 1):
        for combo in combinations(top, n):
            if len({c.market for c in combo}) < n:
                continue
            if _combo_contradicts(combo, home, away):
                continue
            odds_list = [float(c.odds or 1) for c in combo]
            stakes = size_independent_route_stakes(odds_list, budget, profit_goal)
            if not stakes or sum(stakes) > deploy_cap:
                continue
            legs = [
                _leg(c, stakes[i], "route", _reason(c, profile, "Route to target"), home, away)
                for i, c in enumerate(combo)
            ]
            from bet_placer.engine.bet_portfolio import leg_net_if_solo_win
            for leg in legs:
                leg["hits_target"] = leg_net_if_solo_win(leg, legs) >= floor_net
            if not any(l.get("hits_target") for l in legs):
                continue
            probs = [float(c.our_probability or 0) for c in combo]
            p_any = 1.0 - math.prod(1.0 - p for p in probs)
            if p_any > best_p_any:
                best_p_any = p_any
                best_legs = legs

    return best_legs


def _build_card_legs(
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    ctx: dict,
    n: int,
    tier_ranks: dict[str, int] | None = None,
    thesis: str | None = None,
    *,
    placeholder_stakes: bool = False,
) -> list[dict]:
    picked: list = []
    legs: list[dict] = []
    ranks = tier_ranks or {}
    for tier in _TIERS[:n]:
        if placeholder_stakes and tier["role"] == "anchor":
            opt = _pick_feasible_anchor(
                pool, picked, profile, home, away, ctx, budget, target,
                thesis=thesis, rank=ranks.get("anchor", 0),
            )
        else:
            opt = _pick_for_tier(
                pool, tier, picked, profile, home, away, ctx,
                rank=ranks.get(tier["role"], 0),
                thesis=thesis,
            )
        if not opt:
            continue
        picked.append(opt)
        if placeholder_stakes and tier["role"] == "anchor":
            stake = _MIN_ANCHOR_STAKE
        else:
            stake = _size_leg(opt, target, budget, tier)
        legs.append(_leg(opt, stake, tier["role"], _reason(opt, profile, tier["label"]), home, away))

    return legs


def _append_target_lotto(
    legs: list[dict],
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    ctx: dict,
    thesis: str | None = None,
) -> list[dict]:
    """Pick swing SGM/single sized to net profit target  -  balanced with insurance."""
    from bet_placer.engine.bet_portfolio import (
        estimate_balanced_spread_stakes,
        fit_spread_stakes_to_budget,
        leg_net_if_solo_win,
        min_stake_for_profit,
        risk_budget_profile,
        target_profit_inr,
    )

    target_profit = float(ctx.get("target_profit_inr") or target_profit_inr(budget, target))
    profit_floor = target_profit * 0.95
    max_deploy = budget * _MAX_DEPLOY_PCT
    risk = risk_budget_profile(budget, target, len(pool))
    min_prob = risk["min_route_prob"]
    picked_labels = {(l["label"] or "").lower() for l in legs}
    overlay = ctx.get("stake_overlay")
    search_pool = list(pool)

    anchor = next((l for l in legs if l.get("role") == "anchor"), None)
    anchor_odds = float(anchor.get("odds") or 1) if anchor else None

    def _trial_legs(anchor_stake: float, route_stake: float, route_odds: float) -> list[dict]:
        trial: list[dict] = []
        for l in legs:
            tl = dict(l)
            if tl.get("role") == "anchor" and anchor:
                tl["stake_inr"] = anchor_stake
            trial.append(tl)
        trial.append({"stake_inr": route_stake, "odds": route_odds})
        return trial

    def _route_min_prob(_hit_prob: float, _provably_hits: bool) -> float:
        return min_prob

    if overlay:
        from bet_placer.engine.stake_sgm import estimate_stake_combo_probability
        from bet_placer.engine.card_coherence import stake_combo_fits_card

        combo_cands: list[tuple] = []
        for c in overlay.get("stake_combos") or []:
            odds = float(c.get("odds") or 0)
            if odds < 2.5 or odds > 10.0:
                continue
            hit_prob = estimate_stake_combo_probability(c, pool, home, away)
            if not stake_combo_fits_card(c, legs, home, away):
                continue
            if anchor_odds:
                fitted = fit_spread_stakes_to_budget(anchor_odds, odds, budget, target_profit)
                if not fitted:
                    continue
                anchor_est, need = fitted
            else:
                anchor_est = 0
                need = min_stake_for_profit(odds, target_profit, 0)
                if need > max_deploy:
                    need = max(_MIN_STAKE, max_deploy)
            if anchor_est + need > max_deploy:
                continue
            trial = _trial_legs(anchor_est, need, odds)
            net = leg_net_if_solo_win(trial[-1], trial)
            if net < profit_floor * 0.45:
                continue
            provably_hits = net >= profit_floor
            if hit_prob < _route_min_prob(hit_prob, provably_hits):
                continue
            combo_cands.append((hit_prob, hit_prob - need / budget, c, need, odds, hit_prob, net, anchor_est))

        if combo_cands:
            from bet_placer.engine.stake_sgm import _sgm_sweetness
            combo_cands.sort(
                key=lambda x: (x[0] >= 0.18, _sgm_sweetness(x[4]), x[0], x[1]),
                reverse=True,
            )
            _score, _score2, combo, stake, odds, hit_prob, net, _anchor_est = combo_cands[0]
            from bet_placer.engine.leg_explain import explain_leg

            route_leg = {
                "label": combo.get("label") or combo.get("stake_market"),
                "market": "stake_combo",
                "selection": combo.get("selection"),
                "line": combo.get("line"),
                "odds": odds,
                "stake_inr": stake,
                "our_probability": hit_prob,
                "our_probability_pct": round(hit_prob * 100, 1),
                "ev_pct": 0,
                "role": "target_lotto",
                "payout_text": f"₹{int(stake):,} → ₹{int(stake * odds):,}",
                "return_inr": round(stake * odds, 0),
                "profit_if_solo_inr": round(net, 0),
                "hits_target": net >= profit_floor,
                "odds_source": "stake",
                "live_odds": True,
                "stake_market": combo.get("stake_market"),
                "verified_stake": True,
            }
            route_leg["reason"] = explain_leg(
                route_leg,
                home=home,
                away=away,
                budget=budget,
                target_cashout=target,
                all_legs=legs + [route_leg],
                ctx=ctx,
            )
            legs.append(route_leg)
            return legs

    from bet_placer.data.team_stars import player_goal_eligible

    candidates: list[tuple] = []
    for opt in search_pool:
        if _opt_label(opt).lower() in picked_labels:
            continue
        if not _aligns_thesis(opt, thesis, home, away):
            continue
        if not _is_sensible_pick(opt, "target_lotto"):
            continue
        if _opt_market(opt) == "player_goal" and not player_goal_eligible(home, away, _opt_get(opt, "selection")):
            continue
        if _opt_market(opt) == "player_goal":
            continue  # never the main profit route  -  too volatile for target cards
        odds = _opt_odds(opt)
        if odds < 3.5:
            continue
        hit_prob = float(opt.our_probability or 0)
        if anchor_odds:
            fitted = fit_spread_stakes_to_budget(anchor_odds, odds, budget, target_profit)
            if not fitted:
                continue
            anchor_est, need = fitted
        else:
            anchor_est = 0
            need = min_stake_for_profit(odds, target_profit, 0)
            if need > max_deploy:
                need = max(_MIN_STAKE, max_deploy)
        if anchor_est + need > max_deploy:
            continue
        trial = _trial_legs(anchor_est, need, odds)
        net = leg_net_if_solo_win(trial[-1], trial)
        if net < profit_floor:
            continue
        if hit_prob < _route_min_prob(hit_prob, net >= profit_floor):
            continue
        candidates.append((hit_prob, hit_prob - need / budget, opt, need, net))

    if not candidates:
        # Best-effort profit route within budget when full target won't fit.
        best_partial: tuple | None = None
        for opt in search_pool:
            if _opt_label(opt).lower() in picked_labels:
                continue
            if not _aligns_thesis(opt, thesis, home, away):
                continue
            if not _is_sensible_pick(opt, "target_lotto"):
                continue
            if _opt_market(opt) == "player_goal":
                continue
            odds = _opt_odds(opt)
            if odds < 3.5:
                continue
            fitted = fit_spread_stakes_to_budget(
                anchor_odds or 1.5, odds, budget, target_profit, allow_partial=True,
            ) if anchor_odds else None
            if fitted:
                anchor_est, need = fitted
            elif anchor_odds:
                anchor_est = float(anchor.get("stake_inr") or _MIN_ANCHOR_STAKE) if anchor else _MIN_ANCHOR_STAKE
                need = max(_MIN_STAKE, max_deploy - anchor_est - sum(
                    float(l.get("stake_inr") or 0) for l in legs if l.get("role") == "support"
                ))
            else:
                continue
            trial = _trial_legs(anchor_est, need, odds)
            net = leg_net_if_solo_win(trial[-1], trial)
            hit_prob = _opt_prob(opt)
            if hit_prob < min_prob * 0.85:
                continue
            score = hit_prob * 0.6 + net / max(target_profit, 1) * 0.4
            if best_partial is None or score > best_partial[0]:
                best_partial = (score, opt, need, net, anchor_est)
        if best_partial:
            _hp, opt, stake, net, _ae = best_partial
            leg = _leg(opt, stake, "target_lotto", _reason(opt, profile, "Best route in budget"), home, away)
            leg["profit_if_solo_inr"] = round(net, 0)
            leg["hits_target"] = net >= profit_floor
            leg["partial_profit_route"] = net < profit_floor
            legs.append(leg)
        return legs

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _hp, _s2, opt, stake, net = candidates[0]
    leg = _leg(opt, stake, "target_lotto", _reason(opt, profile, "Target single"), home, away)
    leg["profit_if_solo_inr"] = round(net, 0)
    leg["hits_target"] = net >= profit_floor
    leg["partial_profit_route"] = net < profit_floor
    legs.append(leg)
    return legs


def _fold_stake_combos_into_legs(
    legs: list[dict], overlay: dict | None, budget: float, target: float, remaining: float,
    home: str = "", away: str = "", pool: list | None = None, ctx: dict | None = None,
) -> list[dict]:
    """Add one swing SGM when no target route exists yet."""
    if any(l.get("role") == "target_lotto" for l in legs):
        return legs

    from bet_placer.engine.bet_portfolio import risk_budget_profile

    risk = risk_budget_profile(budget, target, len(pool or []))
    picked_labels = {(l["label"] or "").lower() for l in legs}
    combos = _pick_stake_combos(
        overlay, picked_labels, max_n=3, card_legs=legs, home=home, away=away,
    )
    if not combos:
        return legs

    from bet_placer.engine.stake_sgm import estimate_stake_combo_probability

    route_cap = budget * risk["max_route_pct"]
    for c in combos:
        odds = float(c.get("odds") or 0)
        if odds <= 1.0 or odds > 12.0 or remaining < _MIN_STAKE:
            continue
        hit_prob = estimate_stake_combo_probability(c, pool, home, away)
        if hit_prob < risk["min_route_prob"] * 0.75:
            continue
        stake = min(max(_MIN_STAKE, round(route_cap / 10) * 10), remaining)
        if stake > remaining:
            continue
        legs.append({
            "label": c.get("label") or c.get("stake_market"),
            "market": "stake_combo",
            "selection": c.get("selection"),
            "line": c.get("line"),
            "odds": odds,
            "stake_inr": stake,
            "our_probability": hit_prob,
            "our_probability_pct": round(hit_prob * 100, 1),
            "ev_pct": 0,
            "role": "target_lotto",
            "reason": "Swing SGM  -  small stake mixed with singles",
            "payout_text": f"₹{int(stake):,} → ₹{int(stake * odds):,}",
            "return_inr": round(stake * odds, 0),
            "odds_source": "stake",
            "live_odds": True,
            "stake_market": c.get("stake_market"),
            "verified_stake": True,
        })
        break
    return legs


def _finalize_spread_card(legs: list[dict], budget: float) -> list[dict]:
    """Dedupe to one swing + max 3 tickets  -  sizing handled by calibrate."""
    from bet_placer.engine.bet_portfolio import _INSURANCE_ROLES, _ROUTE_ROLES

    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    insurance = [l for l in legs if (l.get("role") or "") in _INSURANCE_ROLES]
    if len(routes) > 1:
        routes.sort(
            key=lambda l: (
                -float(l.get("odds") or 0),
                -float(l.get("our_probability") or 0),
            ),
        )
        legs = insurance + [routes[0]]
    if len(legs) > 3:
        priority = {"anchor": 0, "support": 1, "target_lotto": 2, "stake_combo": 3}
        legs = sorted(legs, key=lambda l: priority.get(l.get("role"), 9))[:3]
    return legs


def _rebalance_to_budget(legs: list[dict], budget: float, target: float = 0) -> tuple[list[dict], float]:
    """Trim/scale so total stake ≤ budget * MAX_DEPLOY_PCT; protect target lotto stake."""
    if not legs:
        return legs, budget
    max_deploy = _round_stake(budget * _MAX_DEPLOY_PCT)
    total = sum(l["stake_inr"] for l in legs)
    if total <= max_deploy:
        reserve = budget - total
        return legs, reserve

    protected = [l for l in legs if l.get("role") == "target_lotto"]
    flexible = [l for l in legs if l.get("role") != "target_lotto"]
    prot_stake = sum(l["stake_inr"] for l in protected)
    flex_cap = max(0, max_deploy - prot_stake)

    if flexible and flex_cap >= _MIN_STAKE * len(flexible):
        flex_total = sum(l["stake_inr"] for l in flexible)
        scale = min(1.0, flex_cap / flex_total) if flex_total > 0 else 1.0
        for l in flexible:
            new_stake = _round_stake(l["stake_inr"] * scale)
            if l.get("role") == "anchor":
                new_stake = max(new_stake, _MIN_ANCHOR_STAKE)
            l["stake_inr"] = max(_MIN_STAKE, new_stake)
            l["return_inr"] = round(l["stake_inr"] * l["odds"], 0)
            l["payout_text"] = f"₹{int(l['stake_inr']):,} → ₹{int(l['return_inr']):,}"
    else:
        scale = max_deploy / total
        for l in legs:
            new_stake = _round_stake(l["stake_inr"] * scale)
            if l.get("role") == "anchor":
                new_stake = max(new_stake, _MIN_ANCHOR_STAKE)
            l["stake_inr"] = max(_MIN_STAKE, new_stake)
            l["return_inr"] = round(l["stake_inr"] * l["odds"], 0)
            l["payout_text"] = f"₹{int(l['stake_inr']):,} → ₹{int(l['return_inr']):,}"

    # Re-boost target lotto if rebalance shrunk it below the profit goal.
    if target > 0:
        from bet_placer.engine.bet_portfolio import leg_net_if_solo_win, min_stake_for_profit, target_profit_inr

        target_profit = target_profit_inr(budget, target)
        profit_floor = target_profit * 0.95
        for l in legs:
            if l.get("role") != "target_lotto":
                continue
            other = sum(x["stake_inr"] for x in legs if x is not l)
            need = min(
                min_stake_for_profit(l.get("odds") or 1, target_profit, other),
                _round_stake(budget * 0.55),
            )
            trial = [dict(x) for x in legs]
            for t in trial:
                if t.get("role") == "target_lotto":
                    t["stake_inr"] = need
            if leg_net_if_solo_win(l, trial) < profit_floor and need >= _MIN_STAKE:
                if other + need <= max_deploy:
                    l["stake_inr"] = need
                    l["return_inr"] = round(need * l["odds"], 0)
                    l["payout_text"] = f"₹{int(need):,} → ₹{int(l['return_inr']):,}"
                    l["profit_if_solo_inr"] = round(leg_net_if_solo_win(l, legs), 0)
                    l["hits_target"] = l["profit_if_solo_inr"] >= profit_floor

    total = sum(l["stake_inr"] for l in legs)
    reserve = max(0, budget - total)
    return legs, reserve


def _trim_to_ticket_count(
    legs: list[dict], max_n: int, home: str, away: str,
) -> list[dict]:
    """Keep the best max_n tickets without breaking path coherence."""
    from bet_placer.engine.card_coherence import path_is_coherent

    if len(legs) <= max_n:
        return legs
    priority = {
        "anchor": 0, "support": 1, "main": 1, "swing": 2,
        "target_lotto": 3, "lottery": 4, "lottery2": 5,
        "stake_combo": 6, "big_lotto": 7,
    }
    ordered = sorted(
        legs,
        key=lambda l: (
            priority.get(l.get("role"), 9),
            -float(l.get("our_probability") or 0),
            -float(l.get("stake_inr") or 0),
        ),
    )
    kept: list[dict] = []
    for leg in ordered:
        if len(kept) >= max_n:
            break
        trial = kept + [leg]
        if path_is_coherent(trial, home, away):
            kept.append(leg)
    return kept if kept else ordered[:max(1, max_n)]


def _drop_conflicting_legs(
    legs: list[dict], target: float, budget: float, home: str, away: str,
) -> list[dict]:
    """Remove legs that fight the rest  -  keep target routes and anchors first."""
    from bet_placer.engine.card_coherence import path_is_coherent

    if len(legs) < 2:
        return legs

    priority = {
        "anchor": 0, "support": 1, "swing": 2,
        "target_lotto": 3, "lottery": 4, "lottery2": 5,
        "stake_combo": 8, "big_lotto": 9,
    }
    ordered = sorted(
        legs,
        key=lambda l: (priority.get(l.get("role"), 9), -float(l.get("odds", 0))),
    )
    kept: list[dict] = []
    for leg in ordered:
        trial = kept + [leg]
        if not path_is_coherent(trial, home, away):
            continue
        kept.append(leg)
    return kept


def _partial_calibrate_spread(
    legs: list[dict], budget: float, target_profit: float,
) -> list[dict]:
    """Scale stakes to budget when full profit target won't fit  -  still build the spread."""
    from bet_placer.engine.bet_portfolio import (
        TARGET_MIN_STAKE,
        _INSURANCE_ROLES,
        _ROUTE_ROLES,
        fit_spread_stakes_to_budget,
        leg_net_if_solo_win,
        min_stake_break_even_solo,
    )

    if not legs:
        return []
    max_deploy = budget * _MAX_DEPLOY_PCT
    insurance = [dict(l) for l in legs if (l.get("role") or "") in _INSURANCE_ROLES]
    routes = [dict(l) for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not routes:
        return []
    route = routes[0]
    anchor = next((l for l in insurance if l.get("role") == "anchor"), insurance[0] if insurance else None)
    support = [l for l in insurance if (l.get("role") or "") != "anchor"]
    odds_r = float(route.get("odds") or 1)
    anchor_stake = 0.0
    if anchor:
        a_odds = float(anchor.get("odds") or 1)
        fitted = fit_spread_stakes_to_budget(
            a_odds, odds_r, budget, target_profit, min_profit_pct=0.35, allow_partial=True,
        )
        if fitted:
            anchor_stake, route_stake = fitted
        else:
            anchor_stake = min(
                min_stake_break_even_solo(a_odds, 0),
                max(TARGET_MIN_STAKE, max_deploy * 0.35),
            )
            route_stake = max(TARGET_MIN_STAKE, max_deploy - anchor_stake)
        anchor["stake_inr"] = anchor_stake
    else:
        route_stake = max(TARGET_MIN_STAKE, min(max_deploy, max_deploy * 0.65))
    route["stake_inr"] = route_stake
    remaining = max(0.0, max_deploy - anchor_stake - route_stake)
    for leg in support:
        if remaining >= TARGET_MIN_STAKE:
            leg["stake_inr"] = min(TARGET_MIN_STAKE * 2, remaining)
            remaining -= leg["stake_inr"]
        else:
            leg["stake_inr"] = 0
    support_stake = sum(float(l.get("stake_inr") or 0) for l in support)
    if anchor:
        a_odds = float(anchor.get("odds") or 1)
        other = route_stake + support_stake
        need_anchor = min_stake_break_even_solo(a_odds, other)
        if need_anchor + other <= max_deploy + 0.01:
            anchor_stake = need_anchor
        else:
            anchor_stake = max(TARGET_MIN_STAKE, max_deploy - other)
        anchor["stake_inr"] = anchor_stake
    out: list[dict] = []
    if anchor:
        out.append(anchor)
    out.extend(l for l in support if float(l.get("stake_inr") or 0) >= TARGET_MIN_STAKE)
    out.append(route)
    if sum(float(l.get("stake_inr") or 0) for l in out) > max_deploy + 1:
        return []
    soft = target_profit * 0.35
    best_net = max(leg_net_if_solo_win(l, out) for l in out if (l.get("role") or "") in _ROUTE_ROLES)
    if best_net < max(20, soft * 0.5):
        return []
    for leg in out:
        st = float(leg.get("stake_inr") or 0)
        od = float(leg.get("odds") or 1)
        leg["return_inr"] = round(st * od, 0)
        role = leg.get("role") or ""
        net = leg_net_if_solo_win(leg, out)
        if role in _ROUTE_ROLES:
            leg["payout_text"] = f"₹{int(st):,} → ₹{int(leg['return_inr']):,} if wins (+₹{int(round(net)):,} profit)"
        elif role in _INSURANCE_ROLES and net >= -5:
            leg["payout_text"] = f"₹{int(st):,} → ₹{int(leg['return_inr']):,} if wins (covers stake)"
        else:
            leg["payout_text"] = f"₹{int(st):,} → ₹{int(leg['return_inr']):,} if wins"
        leg["partial_profit_route"] = net < target_profit * 0.95
    return out


def build_match_card_slip(
    pool: list,
    budget: float,
    profile: dict,
    home: str,
    away: str,
    stake_only: bool,
    human_context: dict | None = None,
    all_options: list | None = None,
    target: float | None = None,
    tier_ranks: dict[str, int] | None = None,
    thesis_side: str | None = None,
    variant_note: str = "",
    *,
    tier_count: int | None = None,
    skip_lotto: bool = False,
    skip_combo_fold: bool = False,
    min_legs: int = 1,
) -> dict | None:
    ctx = human_context or {}
    betting_style = ctx.get("betting_style") or {}
    overlay = ctx.get("stake_overlay")

    if target is None:
        target = float((ctx or {}).get("target_cashout_inr") or max(budget * 2.5, budget + 500))
    target_mult = target / max(budget, 1)
    n = tier_count if tier_count is not None else _n_legs(betting_style, target_mult, budget)
    n = max(min_legs, min(n, len(_TIERS)))

    board_stake = ctx.get("_board_source") == "stake"
    card_pool = _match_card_pool(
        all_options or pool, overlay, stake_only, home, away, board_stake=board_stake,
    )
    if not card_pool:
        card_pool = _match_card_pool(
            pool, overlay, stake_only, home, away, board_stake=board_stake,
        )

    if thesis_side is None:
        thesis_side = _thesis_side_from_ctx(ctx)

    ctx = {**ctx, "_all_options": all_options or pool}

    # Anchor (+ optional support) before profit route  -  3-ticket spreads when tier_count >= 3.
    want_tickets = tier_count if tier_count is not None else n
    tier_n = min(max(1, want_tickets - 1), len(_TIERS)) if not skip_lotto else min(2, n)
    legs = _build_card_legs(
        card_pool, budget, target, profile, home, away, ctx, tier_n,
        tier_ranks=tier_ranks, thesis=thesis_side,
        placeholder_stakes=not skip_lotto,
    )
    if len(legs) < 1:
        return None

    if not skip_lotto:
        legs = _append_target_lotto(
            legs, card_pool, budget, target, profile, home, away, ctx, thesis=thesis_side,
        )
    if not any((l.get("role") or "") in ("target_lotto", "stake_combo", "route") for l in legs):
        if len(legs) >= 1 and any((l.get("role") or "") in ("anchor", "support") for l in legs):
            pass  # keep insurance-only card when profit route impossible
        else:
            return None

    legs = _drop_conflicting_legs(legs, target, budget, home, away)
    legs = _finalize_spread_card(legs, budget)

    target_profit = float(ctx.get("target_profit_inr") or max(0, target - budget))
    from bet_placer.engine.bet_portfolio import (
        annotate_leg_profit_flags,
        calibrate_spread_stakes,
        risk_budget_profile,
    )

    pre_cal = [dict(l) for l in legs]
    legs = calibrate_spread_stakes(
        legs, budget, target_profit,
        target_cashout=target, pool_size=len(card_pool),
    )
    if not legs:
        legs = _partial_calibrate_spread(pre_cal, budget, target_profit)
    if not legs:
        return None

    # Optional extra insurance  -  only if likely (≥48% model) and coherent.
    if not skip_lotto and len(legs) < want_tickets:
        deployed = sum(l["stake_inr"] for l in legs)
        spare = budget * _MAX_DEPLOY_PCT - deployed
        if spare >= _MIN_STAKE * 2:
            from bet_placer.engine.card_coherence import spread_contradicts

            used_labels = {(l.get("label") or "").lower() for l in legs}
            picked_opts = [o for o in card_pool if (o.label or "").lower() in used_labels]
            support_opt = _pick_for_tier(
                card_pool, _TIERS[1], picked_opts,
                profile, home, away, ctx, thesis=thesis_side,
            )
            if support_opt and float(support_opt.our_probability or 0) >= 0.48:
                trial_leg = _leg(
                    support_opt, _MIN_STAKE * 2, "support",
                    _reason(support_opt, profile, "Insurance cushion"), home, away,
                )
                if not any(spread_contradicts((trial_leg, l), home, away) for l in legs):
                    legs.insert(1, trial_leg)
                    legs = calibrate_spread_stakes(
                        legs, budget, target_profit,
                        target_cashout=target, pool_size=len(card_pool),
                    )
                    if not legs:
                        return None

    total = sum(l["stake_inr"] for l in legs)
    reserve = max(0, budget - total)
    risk = risk_budget_profile(budget, target, len(card_pool))
    from bet_placer.engine.bet_portfolio import max_tickets_for_budget
    max_tickets = min(max_tickets_for_budget(budget), risk["max_tickets"], len(legs))
    if len(legs) > max_tickets:
        legs = _trim_to_ticket_count(legs, max_tickets, home, away)

    from bet_placer.engine.card_coherence import path_is_coherent, scrub_incoherent_legs, validate_match_card_legs

    legs = scrub_incoherent_legs(legs, home, away)
    if len(legs) < min(2, min_legs):
        return None
    if not path_is_coherent(legs, home, away):
        return None

    annotate_leg_profit_flags(legs, target_profit)

    ok, reason = validate_match_card_legs(
        legs, target, budget, home, away, min_legs=min(2, min_legs),
        target_profit=target_profit,
    )
    if not ok:
        return None

    if ctx.get("target_hit_mode") and thesis_side in ("home", "away"):
        fav = home if thesis_side == "home" else away
        opp = away if thesis_side == "home" else home
        for leg in legs:
            m = (leg.get("market") or "").lower()
            lbl = (leg.get("label") or "").lower()
            probe = type("O", (), {
                "market": m, "selection": leg.get("selection"), "label": leg.get("label"),
            })()
            if not _aligns_thesis(probe, thesis_side, home, away):
                return None
            if f"draw or {opp.lower()}" in lbl or lbl.strip() in ("draw & no", "draw & yes"):
                if fav.lower() not in lbl:
                    return None
            if m == "stake_combo" and f"{opp.lower()} to win" in lbl:
                return None

    path_label = variant_note
    if not path_label and thesis_side == "home":
        path_label = f"{home} path"
    elif not path_label and thesis_side == "away":
        path_label = f"{away} path"
    elif not path_label and thesis_side == "neutral":
        path_label = "Goals & props path"
    leg_label = path_label_from_legs(legs)
    if leg_label and (not path_label or path_label in _GENERIC_VARIANT_NOTES):
        path_label = leg_label

    total = sum(l["stake_inr"] for l in legs)
    sc = _scenarios_card(legs, reserve, budget, target)
    p_any = sc.get("p_any_win_pct", 0) / 100.0

    combos_used = [l for l in legs if l.get("role") == "stake_combo"]
    singles = [l for l in legs if l.get("role") != "stake_combo"]

    return_1 = sc.get("return_if_1", 0)
    return_2 = sc.get("return_if_2", 0)
    label_parts = ", ".join(l["label"] for l in legs[:4])
    if len(legs) > 4:
        label_parts += f" +{len(legs) - 4} more"

    profit_1 = return_1 - total
    profit_2 = return_2 - total
    p2 = sc.get("p_two_or_more_win_pct", 0)
    route_legs = [l for l in legs if (l.get("role") or "") in ("target_lotto", "stake_combo", "route")]
    best_route_net = max((float(l.get("profit_if_solo_inr") or 0) for l in route_legs), default=0)
    partial_note = ""
    if route_legs and best_route_net < target_profit * 0.95:
        partial_note = (
            f" Full ₹{int(target_profit):,} profit is not reachable on this budget; "
            f"best route nets about ₹{int(best_route_net):,} if it wins alone."
        )

    return {
        "id": "match_card",
        "name": f" {path_label}" if path_label else " Your match card",
        "description": (
            (f"{path_label} · " if path_label else "")
            + f"{len(singles)} separate singles"
            + (f" + {len(combos_used)} verified Stake combo" if combos_used else "")
            + f" · {label_parts}"
        ),
        "why": (
            (f"{path_label} · " if path_label else "")
            + f"Spread card for {format_inr(target)} goal  -  anchor, support, and a profit route."
            + partial_note
            + f" {format_inr(total)} across {len(legs)} tickets, {format_inr(reserve)} kept."
            + f" One winner: {'+' if profit_1 >= 0 else ''}{format_inr(profit_1)} net."
            + (f" Two winners ({p2:.0f}%): {'+' if profit_2 >= 0 else ''}{format_inr(profit_2)} net." if len(legs) >= 2 else "")
        ),
        "risk": "medium",
        "slip_type": "spread_card",
        "placement_mode": "separate_singles",
        "loss_min_style": "spread_card",
        "legs": legs,
        "total_stake_inr": total,
        "reserve_inr": reserve,
        "scenarios": sc,
        "stake_only": stake_only,
        "expected_value_inr": sc.get("expected_value_inr", 0),
        "win_probability_pct": sc.get("p_any_win_pct"),
        "hit_probability": p_any,
        "game_style": profile.get("style"),
        "target_return_inr": target,
        "target_cashout_inr": target,
        "target_profit_inr": target_profit,
        "return_if_1_win_inr": return_1,
        "return_if_2_win_inr": return_2,
        "verified_stake_combos": len(combos_used),
        "path_thesis": thesis_side,
        "path_label": path_label,
        "coherence_checked": True,
        "home_team": home,
        "away_team": away,
    }


def _favorite_side(pool: list, home: str, away: str) -> str | None:
    best_p, best_side = 0.0, None
    for opt in pool:
        if opt.market != "match_winner":
            continue
        p = opt.our_probability or 0
        side = _option_result_side(opt, home, away)
        if side in ("home", "away") and p > best_p:
            best_p, best_side = p, side
    return best_side if best_p >= 0.50 else None


def build_target_match_slips(
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    stake_only: bool,
    human_context: dict | None = None,
    max_slips: int = 2,
) -> list[dict]:
    """Target-sized match cards  -  separate coherent paths, same logic as Hit target."""
    from bet_placer.engine.card_coherence import path_is_coherent

    ctx = human_context or {}
    all_opts = ctx.get("_all_options") or pool
    fav = _favorite_side(all_opts, home, away)

    attempts: list[tuple[str | None, str, dict | None]] = []
    if fav == "home":
        attempts.append(("home", f"{home} · target {format_inr(target)}", None))
    elif fav == "away":
        attempts.append(("away", f"{away} · target {format_inr(target)}", None))
    else:
        attempts.append(("home", f"{home} · target {format_inr(target)}", None))

    underdog = "away" if fav == "home" else "home" if fav == "away" else None
    strict = bool(ctx.get("target_hit_mode"))
    thesis = ctx.get("match_thesis") or {}
    if underdog and not strict:
        alt_name = away if underdog == "away" else home
        attempts.append((underdog, f"{alt_name} alt · target {format_inr(target)}", None))
    elif underdog and strict and thesis.get("draw_scenario"):
        alt_name = away if underdog == "away" else home
        attempts.append((underdog, f"{alt_name} alt · target {format_inr(target)}", None))

    slips: list[dict] = []
    seen: set = set()

    def _try_add(thesis: str | None, note: str, tier_ranks: dict | None) -> None:
        if len(slips) >= max_slips:
            return
        slip = build_match_card_slip(
            pool, budget, profile, home, away, stake_only, ctx,
            all_options=all_opts,
            target=target,
            thesis_side=thesis,
            tier_ranks=tier_ranks,
            variant_note=note,
            min_legs=2,
        )
        if not slip:
            return
        legs = slip.get("legs") or []
        if len(legs) < 2 or not path_is_coherent(legs, home, away):
            return
        sig = tuple(sorted(
            (l.get("market"), l.get("selection"), l.get("line"))
            for l in legs
        ))
        if sig in seen:
            return
        seen.add(sig)
        slips.append(slip)

    for thesis, note, ranks in attempts:
        _try_add(thesis, note, ranks)

    # Neutral goals/props path when fav + underdog paths exist
    if len(slips) < max_slips:
        _try_add("neutral", f"Goals & props · target {format_inr(target)}", None)

    # Tier-rank alternates for more distinct leg mixes on the same thesis
    if len(slips) < max_slips and fav:
        alt_side = underdog or ("away" if fav == "home" else "home")
        alt_name = away if alt_side == "away" else home
        _try_add(alt_side, f"{alt_name} alt lines", {"support": 1, "swing": 1})
    if len(slips) < max_slips:
        _try_add("neutral", "Cards & corners route", {"lottery": 1})

    return slips


def build_coherent_match_paths(
    pool: list,
    budget: float,
    profile: dict,
    home: str,
    away: str,
    stake_only: bool,
    human_context: dict | None = None,
    max_paths: int = 3,
    target: float | None = None,
) -> list[dict]:
    """Separate paths per team/read  -  each path is internally non-contradictory."""
    from bet_placer.engine.card_coherence import path_is_coherent

    ctx = human_context or {}
    all_opts = ctx.get("_all_options") or pool
    fav = _favorite_side(all_opts, home, away)
    underdog = "away" if fav == "home" else "home" if fav == "away" else None

    attempts: list[tuple[str | None, str]] = []
    if fav == "home":
        attempts.append(("home", f"{home} path"))
    elif fav == "away":
        attempts.append(("away", f"{away} path"))
    if underdog:
        under_name = away if underdog == "away" else home
        attempts.append((underdog, f"{under_name} alt path"))
    attempts.append(("neutral", "Goals & props path"))

    paths: list[dict] = []
    seen_sigs: set = set()
    for thesis, note in attempts:
        slip = build_match_card_slip(
            pool, budget, profile, home, away, stake_only, ctx,
            all_options=all_opts,
            target=target or float(ctx.get("target_cashout_inr") or max(budget * 2.5, budget + 500)),
            thesis_side=thesis,
            variant_note=note,
        )
        if not slip or not path_is_coherent(slip.get("legs") or [], home, away):
            continue
        sig = tuple(sorted(
            (l.get("market"), l.get("selection"), l.get("line"))
            for l in slip.get("legs", [])
        ))
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        paths.append(slip)
        if len(paths) >= max_paths:
            break
    return paths


def build_match_card_plan(
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    stake_only: bool,
    human_context: dict | None = None,
    tier_ranks: dict[str, int] | None = None,
    variant_note: str = "",
    thesis_side: str | None = None,
) -> dict | None:
    """Hit-target plan: spread card sized for partial wins."""
    ctx = human_context or {}
    if thesis_side is None:
        thesis_side = _thesis_side_from_ctx(ctx)
    slip = build_match_card_slip(
        pool, budget, profile, home, away, stake_only, human_context,
        all_options=ctx.get("_all_options"),
        target=target,
        tier_ranks=tier_ranks,
        variant_note=variant_note,
        thesis_side=thesis_side,
    )
    if not slip:
        return None

    legs = slip["legs"]
    return_1 = slip.get("return_if_1_win_inr", 0)
    return_2 = slip.get("return_if_2_win_inr", 0)
    combos = [l for l in legs if l.get("role") == "stake_combo"]
    singles = [l for l in legs if l.get("role") != "stake_combo"]

    total = slip["total_stake_inr"]
    profit_1 = return_1 - total
    profit_2 = return_2 - total
    headline = (
        f"{len(legs)} separate tickets · 1 hits → net "
        f"{'+' if profit_1 >= 0 else ''}{format_inr(profit_1)} · "
        f"2 hit → net {'+' if profit_2 >= 0 else ''}{format_inr(profit_2)}"
    )
    if variant_note:
        headline = f"{variant_note} · {headline}"

    label = f"Match card · {len(singles)} separate singles"
    if combos:
        label += f" + {len(combos)} Stake combo"
    if variant_note:
        label = f"{variant_note} · {label}"

    return {
        "plan_type": "match_card",
        "plan_type_label": label,
        "name": " Your match card",
        "description": slip["description"],
        "why": slip["why"],
        "path_headline": headline,
        "legs": legs,
        "total_stake_inr": slip["total_stake_inr"],
        "reserve_inr": slip["reserve_inr"],
        "target_return_inr": target,
        "target_profit_inr": slip.get("target_profit_inr") or round(
            target - (slip.get("total_stake_inr") or 0) - (slip.get("reserve_inr") or 0), 0
        ),
        "hit_probability": slip.get("hit_probability", 0),
        "hit_probability_pct": round(slip.get("hit_probability", 0) * 100, 1),
        "model_alignment": round(sum(l.get("our_probability", 0) for l in legs) / len(legs) * 100, 1),
        "scenarios": slip["scenarios"],
        "stake_only": stake_only,
        "expected_value_inr": slip["scenarios"].get("expected_value_inr", 0),
        "feasibility": "medium" if slip.get("hit_probability", 0) >= 0.35 else "low",
        "placement_mode": "separate_singles",
        "game_style": profile.get("style"),
        "return_if_1_win_inr": return_1,
        "return_if_2_win_inr": return_2,
        "verified_stake_combos": slip.get("verified_stake_combos", 0),
        "verified_stake": True,
    }


def build_match_card_variants(
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    stake_only: bool,
    human_context: dict | None = None,
    max_variants: int = 3,
) -> list[dict]:
    """A few distinct spread cards  -  quality over quantity."""
    variants: list[dict] = []
    seen: set = set()

    rank_grid = [
        {},
        {"support": 1},
        {"swing": 1},
        {"lottery": 1},
        {"anchor": 1},
        {"support": 1, "swing": 1},
        {"lottery": 1, "lottery2": 1},
        {"anchor": 1, "support": 1},
    ]
    notes = [
        "Best mix",
        "Alt support line",
        "Alt swing line",
        "Alt longshot",
        "Alt anchor",
        "Support + swing mix",
        "More longshots",
        "Safer anchor mix",
    ]

    for ranks, note in zip(rank_grid, notes):
        plan = build_match_card_plan(
            pool, budget, target, profile, home, away, stake_only, human_context,
            tier_ranks=ranks or None,
            variant_note=note if ranks else "",
        )
        if not plan:
            continue
        sig = tuple(sorted(
            (l.get("market"), l.get("selection"), l.get("line"), l.get("role"))
            for l in plan.get("legs", [])
        ))
        if sig in seen:
            continue
        seen.add(sig)
        variants.append(plan)
        if len(variants) >= max_variants:
            break

    return variants


def build_balanced_sized_paths(
    pool: list,
    budget: float,
    target: float,
    profile: dict,
    home: str,
    away: str,
    stake_only: bool,
    human_context: dict | None = None,
) -> list[dict]:
    """2 / 3 / 4-ticket spreads  -  distinct sizes, not always 5–6 legs."""
    ctx = human_context or {}
    all_opts = ctx.get("_all_options") or pool
    fav = _favorite_side(all_opts, home, away)
    thesis = fav or "home"

    from bet_placer.engine.bet_portfolio import max_tickets_for_budget

    specs: list[tuple[int, bool, bool, str, str | None]] = []
    cap = max_tickets_for_budget(budget)
    start_n = 3 if float(ctx.get("target_cashout_inr") or 0) / max(budget, 1) >= 3.5 else 2
    for n in range(start_n, min(cap, 12) + 1):
        specs.append((n, False, True, f"{n} tickets", thesis))
    if cap >= 3:
        specs.append((min(4, cap), False, True, "Goals and props", "neutral"))
    paths: list[dict] = []
    seen: set = set()
    for tier_count, skip_lotto, skip_combo, note, path_thesis in specs:
        slip = build_match_card_slip(
            pool, budget, profile, home, away, stake_only, ctx,
            all_options=all_opts,
            target=target,
            thesis_side=path_thesis,
            variant_note=note,
            tier_count=tier_count,
            skip_lotto=skip_lotto,
            skip_combo_fold=skip_combo,
            min_legs=1,
        )
        if not slip:
            continue
        sig = tuple(sorted(
            (l.get("market"), l.get("selection"), l.get("line"))
            for l in slip.get("legs", [])
        ))
        if sig in seen:
            continue
        seen.add(sig)
        paths.append(slip)
    return paths
