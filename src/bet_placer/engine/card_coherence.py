"""Spread-card coherence — no contradictory tickets on the same match card.

Each ticket is a separate single (or one verified Stake combo as the target route).
They must be able to win together in some realistic scoreline, and at least one
route should reach the cashout target when it alone wins.

Stake same-game multis are decomposed into implied legs before checking.
"""

from __future__ import annotations

import math
import re
from typing import Any

from bet_placer.engine.bet_builder import _axis_dir, _sel_side


def _as_dict(o: Any) -> dict:
    if isinstance(o, dict):
        return o
    return {
        "market": getattr(o, "market", None),
        "selection": getattr(o, "selection", None),
        "label": getattr(o, "label", None),
        "line": getattr(o, "line", None),
        "market_label": getattr(o, "label", None),
        "odds": getattr(o, "odds", None),
    }


def _label(o: Any) -> str:
    d = _as_dict(o)
    return (d.get("label") or d.get("selection") or "").lower()


def _market(o: Any) -> str:
    return (_as_dict(o).get("market") or "").lower()


def _selection(o: Any) -> str:
    return (_as_dict(o).get("selection") or "").lower()


def _line(o: Any) -> float | None:
    d = _as_dict(o)
    if d.get("line") is not None:
        try:
            return float(d["line"])
        except (TypeError, ValueError):
            pass
    text = f"{d.get('label') or ''} {d.get('selection') or ''}".lower()
    if _market(o) in ("over_under_goals", "corners", "cards", "asian_corners", "total_corners", "total_bookings"):
        m = re.search(r"([\d.]+)", text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _pick_text(o: Any) -> str:
    d = _as_dict(o)
    return (d.get("selection") or d.get("label") or "").strip()


def _result_side(o: Any, home: str, away: str) -> str | None:
    side = _sel_side(_pick_text(o), home, away)
    return side if side in ("home", "away", "draw") else None


def _is_correct_score(o: Any) -> bool:
    m = _market(o)
    lbl = _label(o)
    return m in ("exact_score", "correct_score") or "correct score" in lbl


def _score_key(o: Any) -> str:
    d = _as_dict(o)
    sel = (d.get("selection") or d.get("label") or "").lower()
    for token in ("correct score", "cs "):
        sel = sel.replace(token, "").strip()
    return sel


def _parse_score_winner(selection: str) -> str | None:
    """home / away / draw implied by a correct-score selection."""
    import re
    m = re.search(r"(\d+)\s*[-:]\s*(\d+)", selection or "")
    if not m:
        return None
    h, a = int(m.group(1)), int(m.group(2))
    if h > a:
        return "home"
    if a > h:
        return "away"
    return "draw"


def score_aligns_thesis(opt: Any, thesis: str | None, home: str, away: str) -> bool:
    """Correct-score picks must match the path's result lean."""
    if not thesis or thesis in ("open", "neutral"):
        return True
    if thesis not in ("home", "away"):
        return True
    winner = _parse_score_winner(_score_key(opt))
    if not winner:
        return True
    if thesis == "home":
        return winner in ("home", "draw")
    if thesis == "away":
        return winner in ("away", "draw")
    return True


def _parse_score_total(selection: str) -> int | None:
    import re
    m = re.search(r"(\d+)\s*[-:]\s*(\d+)", selection or "")
    if not m:
        return None
    return int(m.group(1)) + int(m.group(2))


def _handicap_favoured_side(o: Any, home: str, away: str) -> str | None:
    """Which team this handicap ticket needs to outperform."""
    side = _result_side(o, home, away)
    if side not in ("home", "away"):
        return None
    line = _handicap_line_value(o)
    if line is None:
        return side
    if line < 0:
        return side
    return "away" if side == "home" else "home"


def _handicap_line_value(o: Any) -> float | None:
    """Signed Asian handicap (negative = favourite gives goals)."""
    d = _as_dict(o)
    if _market(o) == "asian_handicap" and d.get("line") is not None:
        try:
            return float(d["line"])
        except (TypeError, ValueError):
            pass
    text = f"{d.get('label') or ''} {d.get('selection') or ''}"
    m = re.search(r"handicap\s*([+-]?\d+\.?\d*)", text, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"\(([+-]?\d+\.?\d*)\)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _min_total_goals_for_handicap_cover(h_line: float) -> int:
    """Smallest integer total goals that can cover a negative AH on the favourite."""
    return math.ceil(abs(h_line) + 0.5)


def _max_total_goals_for_under(u_line: float) -> int:
    return math.floor(u_line)


def _goals_vs_handicap_conflict(ou: Any, ah: Any) -> bool:
    """Under low totals vs large favourite handicap — mutually exclusive scorelines."""
    if _market(ou) != "over_under_goals" or _market(ah) != "asian_handicap":
        return False
    if "under" not in _selection(ou):
        return False
    h_line = _handicap_line_value(ah)
    if h_line is None or h_line >= 0:
        return False
    u_line = _line(ou)
    if u_line is None:
        m = re.search(r"([\d.]+)", _selection(ou))
        u_line = float(m.group(1)) if m else None
    if u_line is None:
        return False
    return _min_total_goals_for_handicap_cover(h_line) > _max_total_goals_for_under(u_line)


def _pair_hard_conflict(a: Any, b: Any, home: str, away: str) -> bool:
    """True when two picks cannot BOTH win (mutually exclusive outcomes)."""
    da, db = _as_dict(a), _as_dict(b)
    ma, mb = _market(a), _market(b)
    sa, sb = _selection(a), _selection(b)

    # Same market, opposite side
    if ma == mb == "over_under_goals" and _line(a) == _line(b):
        if ("over" in sa) != ("over" in sb):
            return True

    if ma == mb == "btts":
        if ("yes" in sa) != ("yes" in sb):
            return True

    if ma == mb in ("corners", "cards", "asian_corners", "total_corners", "total_bookings"):
        if _line(a) == _line(b) and ("over" in sa) != ("over" in sb):
            return True

    # Match winner / result — only one side can win outright
    result_markets = {"match_winner", "draw_no_bet", "asian_handicap", "half_time", "double_chance"}
    if ma in result_markets and mb in result_markets:
        side_a = _result_side(a, home, away)
        side_b = _result_side(b, home, away)
        if side_a in ("home", "away") and side_b in ("home", "away") and side_a != side_b:
            return True
        if side_a == "draw" and side_b in ("home", "away"):
            return True
        if side_b == "draw" and side_a in ("home", "away"):
            return True
        # Handicap on favourite vs outright on underdog can still fight
        if ma == "asian_handicap" and mb == "match_winner":
            ha = _handicap_favoured_side(a, home, away)
            if ha and side_b in ("home", "away") and ha != side_b:
                return True
        if mb == "asian_handicap" and ma == "match_winner":
            hb = _handicap_favoured_side(b, home, away)
            if hb and side_a in ("home", "away") and hb != side_a:
                return True

    # Double chance vs opposite outright (not DC vs DC — that would recurse forever)
    if ma == "double_chance" and mb in result_markets and mb != "double_chance":
        side_dc = _result_side(a, home, away)
        side_other = _result_side(b, home, away)
        if side_dc in ("home", "away") and side_other in ("home", "away") and side_dc != side_other:
            return True

    if mb == "double_chance" and ma in result_markets and ma != "double_chance":
        side_dc = _result_side(b, home, away)
        side_other = _result_side(a, home, away)
        if side_dc in ("home", "away") and side_other in ("home", "away") and side_dc != side_other:
            return True

    # Different correct scores — only one can land
    if _is_correct_score(a) and _is_correct_score(b):
        if _score_key(a) != _score_key(b):
            return True

    # Correct score vs result lean (DNB, ML, handicap)
    for cs, other in ((a, b), (b, a)):
        if not _is_correct_score(cs) or _is_correct_score(other):
            continue
        winner = _parse_score_winner(_score_key(cs))
        if not winner:
            continue
        om = _market(other)
        side = _result_side(other, home, away)
        if om == "draw_no_bet" and side in ("home", "away"):
            if winner not in (side, "draw"):
                return True
        elif om in ("match_winner", "asian_handicap", "half_time") and side in ("home", "away"):
            if winner != side:
                return True

    # Over vs under goals — incompatible totals (e.g. Over 3.0 + Under 1.5)
    if ma == "over_under_goals" and mb == "over_under_goals":
        la, lb = _line(a), _line(b)
        if la is not None and lb is not None:
            if "over" in sa and "under" in sb and la >= lb:
                return True
            if "under" in sa and "over" in sb and la <= lb:
                return True
        elif ("over" in sa and "under" in sb) or ("under" in sa and "over" in sb):
            return True

    # Under low total vs BTTS yes often fights; strict only at extreme lines
    if {ma, mb} == {"over_under_goals", "btts"}:
        ou = a if ma == "over_under_goals" else b
        bt = b if ma == "over_under_goals" else a
        ou_sel, bt_sel = _selection(ou), _selection(bt)
        ou_line = _line(ou) or 2.5
        if "under" in ou_sel and ou_line <= 1.5 and "yes" in bt_sel:
            return True
        if "over" in ou_sel and ou_line >= 3.5 and "no" in bt_sel:
            return True

    # Correct score vs total goals — can't both win if scoreline breaks the line
    if _is_correct_score(a) and _market(b) == "over_under_goals":
        total = _parse_score_total(_score_key(a))
        line = _line(b) or 2.5
        if total is not None:
            if "under" in _selection(b) and total > line:
                return True
            if "over" in _selection(b) and total <= line:
                return True
    if _is_correct_score(b) and _market(a) == "over_under_goals":
        return _pair_hard_conflict(b, a, home, away)

    # Under low total vs favourite giving large goals (e.g. U1.5 + France -2)
    for ou, ah in ((a, b), (b, a)):
        if _goals_vs_handicap_conflict(ou, ah):
            return True

    return False


def _axis_coherence_fails(picks: tuple, home: str, away: str) -> bool:
    """Soft coherence: one direction per axis; don't stack conflicting score reads."""
    from bet_placer.engine.bet_builder import _axis_dir as axis_fn

    axis_dir: dict[str, str] = {}
    scoreline_shape = False  # goals OR btts — not both fighting

    for o in picks:
        d = _as_dict(o)
        axis, direction = axis_fn(d, home, away)

        if _is_correct_score(o):
            continue

        if axis in ("goals", "btts"):
            if scoreline_shape:
                # Second scoreline read — only allow if aligned (under+no, over+yes)
                gdir = axis_dir.get("goals")
                bdir = axis_dir.get("btts")
                if axis == "goals":
                    if bdir == "yes" and direction == "under":
                        return True
                    if bdir == "no" and direction == "over":
                        return True
                if axis == "btts":
                    if gdir == "over" and direction == "no":
                        return True
                    if gdir == "under" and direction == "yes":
                        return True
            else:
                scoreline_shape = True

        if axis in axis_dir and axis_dir[axis] != direction:
            if axis == "result":
                if direction != "nodraw" and axis_dir[axis] != "nodraw":
                    return True
            elif axis in ("goals", "btts", "corners", "cards", "half"):
                return True

        axis_dir[axis] = direction

    return False


def _is_stake_combo(o: Any) -> bool:
    d = _as_dict(o)
    return (
        _market(o) == "stake_combo"
        or d.get("role") == "stake_combo"
        or bool(d.get("stake_market") and "&" in (d.get("stake_market") or ""))
    )


def _parse_combo_segment(text: str, home: str, away: str) -> dict | None:
    """Turn one '&' segment of a Stake SGM into a pseudo pick."""
    raw = (text or "").strip()
    if not raw:
        return None
    t = raw.lower()

    if "both teams" in t or "btts" in t:
        sel = "yes" if ("yes" in t or "— yes" in raw.lower()) else "no" if "no" in t else "yes"
        return {"market": "btts", "selection": sel, "label": raw}

    ou = re.search(r"(over|under)\s*([\d.]+)", t)
    if ou or " goals" in t or t.endswith(" goals"):
        direction = ou.group(1) if ou else ("over" if "over" in t else "under" if "under" in t else None)
        line = float(ou.group(2)) if ou else 2.5
        if direction:
            return {
                "market": "over_under_goals",
                "selection": f"{direction} {line}",
                "line": line,
                "label": raw,
            }

    side = _sel_side(raw, home, away)
    if side in ("home", "away", "draw"):
        return {"market": "match_winner", "selection": raw, "label": raw}

    if "win" in t:
        side = _sel_side(re.sub(r"\s+to\s+win", "", raw, flags=re.I).strip(), home, away)
        if side in ("home", "away", "draw"):
            return {"market": "match_winner", "selection": raw, "label": raw}

    if "double chance" in t or " or draw" in t or "draw or " in t:
        side = _sel_side(raw, home, away)
        if side in ("home", "away"):
            return {"market": "double_chance", "selection": raw, "label": raw}

    if "handicap" in t or re.search(r"\([+-]?\d", raw):
        side = _sel_side(raw, home, away)
        if side in ("home", "away"):
            return {"market": "asian_handicap", "selection": raw, "label": raw}

    return None


def _market_types_from_stake_market(stake_market: str) -> list[str]:
    """Map each '&' chunk of stake_market to an internal market type."""
    sm = (stake_market or "").strip()
    if "&" not in sm:
        return []
    types: list[str] = []
    for chunk in re.split(r"\s*&\s*", sm):
        t = chunk.lower().strip()
        if "1x2" in t or t in ("match result", "match winner"):
            types.append("match_winner")
        elif "both teams" in t or t == "btts":
            types.append("btts")
        elif "total" in t:
            types.append("over_under_goals")
        else:
            types.append("")
    return types


def _segment_to_pick(
    segment: str,
    market_type: str,
    home: str,
    away: str,
) -> dict | None:
    """Turn one combo segment into a pseudo pick using stake_market context."""
    raw = (segment or "").strip()
    if not raw:
        return None
    t = raw.lower()

    if market_type == "btts" or t in ("yes", "no") or "both teams" in t or "btts" in t:
        if t in ("yes", "no"):
            sel = t
        elif re.search(r"\bno\b", t) and not re.search(r"\byes\b", t):
            sel = "no"
        else:
            sel = "yes"
        return {"market": "btts", "selection": sel, "label": raw}

    if market_type == "over_under_goals":
        ou = re.search(r"(over|under)\s*([\d.]+)", t)
        if ou:
            direction, line = ou.group(1), float(ou.group(2))
            return {
                "market": "over_under_goals",
                "selection": f"{direction} {line}",
                "line": line,
                "label": raw,
            }

    if market_type == "match_winner":
        side = _sel_side(raw, home, away)
        if side in ("home", "away", "draw"):
            return {"market": "match_winner", "selection": raw, "label": raw}

    return _parse_combo_segment(raw, home, away)


def _combo_label_segments(combo: dict) -> list[str]:
    """Selection segments from the combo label (not stake_market names)."""
    d = combo if isinstance(combo, dict) else _as_dict(combo)
    for text in (d.get("label"), d.get("selection")):
        text = (text or "").strip()
        if not text or "&" not in text:
            continue
        parts = [c.strip() for c in re.split(r"\s*&\s*", text) if c.strip()]
        if len(parts) >= 2:
            return parts
    return []


def decompose_stake_combo(combo: dict, home: str, away: str) -> list[dict]:
    """Expand a verified Stake SGM into implied single picks."""
    d = combo if isinstance(combo, dict) else _as_dict(combo)
    stake_market = d.get("stake_market") or ""
    segments = _combo_label_segments(d)
    market_types = _market_types_from_stake_market(stake_market)

    picks: list[dict] = []
    if segments:
        for i, seg in enumerate(segments):
            mtype = market_types[i] if i < len(market_types) else ""
            if not mtype and seg.lower() in ("yes", "no"):
                mtype = "btts"
            parsed = _segment_to_pick(seg, mtype, home, away)
            if parsed:
                picks.append(parsed)

    if not picks and segments:
        for seg in segments:
            parsed = _parse_combo_segment(seg, home, away)
            if parsed:
                picks.append(parsed)

    if not picks:
        blob = " ".join(
            x for x in (d.get("label"), d.get("selection"), stake_market) if x
        ).strip()
        side = _sel_side(blob, home, away)
        if side in ("home", "away", "draw"):
            picks.append({"market": "match_winner", "selection": blob, "label": blob})
        ou = re.search(r"(over|under)\s*([\d.]+)", blob.lower())
        if ou:
            line = float(ou.group(2))
            picks.append({
                "market": "over_under_goals",
                "selection": f"{ou.group(1)} {line}",
                "line": line,
                "label": blob,
            })

    return picks


def stake_combo_is_garbage(combo: dict, home: str, away: str) -> bool:
    """Drop redundant Stake combos (e.g. France goal to win & France to win)."""
    d = combo if isinstance(combo, dict) else _as_dict(combo)
    segments = _combo_label_segments(d)
    if len(segments) >= 2:
        bases: list[str] = []
        for seg in segments:
            s = re.sub(r"\s+to\s+win", "", seg.lower(), flags=re.I)
            s = re.sub(r"\s+goal", "", s, flags=re.I)
            s = re.sub(r"\s+", " ", s).strip()
            bases.append(s)
        if len(set(bases)) < len(bases):
            return True
    picks = decompose_stake_combo(d, home, away)
    if len(picks) >= 2:
        winners = [
            p for p in picks
            if (p.get("market") or "").lower() in ("match_winner", "draw_no_bet", "double_chance")
        ]
        if len(winners) >= 2:
            sides = {_result_side(p, home, away) for p in winners}
            sides.discard(None)
            if len(sides) == 1:
                return True
    return False


def path_is_coherent(legs: list[dict], home: str, away: str) -> bool:
    """Every ticket on this path must be able to win together — no internal fights."""
    if len(legs) < 2:
        return True
    expanded: list[dict] = []
    for leg in legs:
        expanded.extend(_expand_pick(leg, home, away))
    if len(expanded) < 2:
        return len(legs) <= 1

    for i, a in enumerate(expanded):
        for b in expanded[i + 1:]:
            if _pair_hard_conflict(a, b, home, away):
                return False
    return not _axis_coherence_fails(tuple(expanded), home, away)


def _expand_pick(o: Any, home: str, away: str) -> list[dict]:
    if _is_stake_combo(o):
        parts = decompose_stake_combo(_as_dict(o), home, away)
        if parts:
            return parts
    d = _as_dict(o)
    m = (d.get("market") or "").lower()
    if m == "over_under_goals" and d.get("line") is None:
        inferred = _line(o)
        if inferred is not None:
            d = {**d, "line": inferred}
    return [d]


def card_result_sides(legs: list[dict], home: str, away: str) -> list[str]:
    """Every team-side lean already on the card (anchor, swing, handicap, etc.)."""
    sides: list[str] = []
    for leg in legs:
        if leg.get("role") == "stake_combo" or leg.get("market") == "stake_combo":
            continue
        m = (leg.get("market") or "").lower()
        if m not in ("match_winner", "draw_no_bet", "asian_handicap", "double_chance", "half_time"):
            continue
        side = _result_side(leg, home, away)
        if side in ("home", "away"):
            sides.append(side)
    return sides


def card_result_side(legs: list[dict], home: str, away: str) -> str | None:
    """Dominant result lean on a spread card."""
    sides = card_result_sides(legs, home, away)
    if not sides:
        return None
    return max(set(sides), key=sides.count)


def thesis_reference_legs(
    pool: list | None,
    home: str,
    away: str,
    human_context: dict | None = None,
) -> list[dict]:
    """Best result lean for filtering standalone SGMs."""
    ctx = human_context or {}
    for pick in (ctx.get("easy_money_picks") or []) + (ctx.get("unified_picks") or []):
        m = (pick.get("market") or "").lower()
        if m in ("match_winner", "draw_no_bet", "double_chance", "asian_handicap"):
            return [{"role": "anchor", **pick}]

    best = None
    for opt in pool or []:
        if getattr(opt, "market", None) != "match_winner":
            continue
        p = getattr(opt, "our_probability", 0) or 0
        if best is None or p > best[0]:
            best = (p, opt)
    if best and best[0] >= 0.52:
        o = best[1]
        return [{
            "role": "anchor",
            "market": o.market,
            "selection": o.selection,
            "label": o.label,
        }]
    return []


def stake_combo_fits_card(combo: dict, legs: list[dict], home: str, away: str) -> bool:
    """True when an SGM can sit on this card without fighting existing tickets."""
    if not combo:
        return False
    expanded_combo = decompose_stake_combo(combo, home, away)
    if not expanded_combo:
        return False

    for i, a in enumerate(expanded_combo):
        for b in expanded_combo[i + 1:]:
            if _pair_hard_conflict(a, b, home, away):
                return False
    if len(expanded_combo) >= 2 and _axis_coherence_fails(tuple(expanded_combo), home, away):
        return False

    card_side = card_result_side(legs, home, away)
    card_sides = card_result_sides(legs, home, away)
    for part in expanded_combo:
        if part.get("market") not in ("match_winner", "draw_no_bet", "asian_handicap", "double_chance"):
            continue
        side = _result_side(part, home, away)
        if side in ("home", "away") and card_side and side != card_side:
            return False
        if side in ("home", "away") and card_sides and side not in card_sides:
            return False
        if side == "draw" and card_side in ("home", "away"):
            return False

    existing = [_as_dict(l) for l in legs]
    for part in expanded_combo:
        for leg in existing:
            if spread_contradicts((part, leg), home, away):
                return False
            if _is_stake_combo(leg):
                for sub in decompose_stake_combo(leg, home, away):
                    if spread_contradicts((part, sub), home, away):
                        return False
    return True


def stake_combo_fits_thesis(
    combo: dict,
    pool: list | None,
    home: str,
    away: str,
    human_context: dict | None = None,
) -> bool:
    """Standalone SGM tab — must agree with the match read, not random sides."""
    ctx = human_context or {}
    ref = thesis_reference_legs(pool, home, away, ctx)
    if not ref:
        thesis = ctx.get("match_thesis") or {}
        rd = thesis.get("result_dir")
        if rd in ("home", "away"):
            team = home if rd == "home" else away
            ref = [{
                "role": "anchor",
                "market": "match_winner",
                "selection": rd,
                "label": f"{team} to win",
            }]
    if not ref:
        return True
    return stake_combo_fits_card(combo, ref, home, away)


def spread_contradicts(picks: tuple, home: str = "", away: str = "") -> bool:
    """True if any pick on this spread card fights another."""
    if len(picks) < 2:
        return False

    if home and away:
        expanded: list[dict] = []
        for p in picks:
            expanded.extend(_expand_pick(p, home, away))

        if len(expanded) < 2:
            return False

        for i, a in enumerate(expanded):
            for b in expanded[i + 1:]:
                if _pair_hard_conflict(a, b, home, away):
                    return True
        if _axis_coherence_fails(tuple(expanded), home, away):
            return True
        return False

    # Fallback when team names unknown
    labels = " ".join(_label(p) for p in picks)
    markets = [_market(p) for p in picks]
    if markets.count("over_under_goals") > 1 and "over" in labels and "under" in labels:
        return True
    if "btts" in markets and "over_under_goals" in markets:
        ou = next(p for p in picks if _market(p) == "over_under_goals")
        bt = next(p for p in picks if _market(p) == "btts")
        if "under" in _selection(ou) and "yes" in _selection(bt):
            return True
    return False


def card_has_target_route(legs: list[dict], target: float, min_ratio: float = 0.85) -> bool:
    """At least one ticket alone — or 2–3 together — should reach the cashout target."""
    if not legs or target <= 0:
        return True
    if any(l.get("hits_target") for l in legs):
        return True
    has_lotto = any(l.get("role") in ("target_lotto", "lottery", "big_lotto") for l in legs)
    if has_lotto and len(legs) >= 3:
        min_ratio = min(min_ratio, 0.55)
    singles = [float(l.get("stake_inr", 0)) * float(l.get("odds", 1)) for l in legs]
    ranked = sorted(singles, reverse=True)
    ratios = [min_ratio]
    if len(legs) >= 3:
        ratios.extend((0.72, 0.65, 0.58))
    for ratio in ratios:
        if max(singles, default=0) >= target * ratio:
            return True
        for k in range(2, min(len(ranked), 4) + 1):
            if sum(ranked[:k]) >= target * ratio:
                return True
    return False


def net_if_only_leg_wins(legs: list[dict], leg_idx: int) -> float:
    """Net profit if only this leg wins (others lose their stakes)."""
    total_stake = sum(float(l.get("stake_inr", 0)) for l in legs)
    leg = legs[leg_idx]
    gross = float(leg.get("stake_inr", 0)) * float(leg.get("odds", 1))
    return gross - total_stake


def _opposing_team_player(leg: dict, card_side: str | None, home: str, away: str) -> bool:
    if (leg.get("market") or "") != "player_goal":
        return False
    text = f"{leg.get('label', '')} {leg.get('selection', '')}".lower()
    if card_side == "home" and away.lower() in text:
        return True
    if card_side == "away" and home.lower() in text:
        return True
    return False


def _leg_axis_readings(leg: dict, home: str, away: str) -> dict[str, str]:
    """Per-leg axis directions (goals over/under, result home/away, etc.)."""
    from bet_placer.engine.bet_builder import _axis_dir

    readings: dict[str, str] = {}
    for part in _expand_pick(leg, home, away):
        axis, direction = _axis_dir(part, home, away)
        if axis not in ("goals", "btts", "result", "corners", "cards") or direction in ("-", ""):
            continue
        # Skip nodraw noise; keep "draw" so Draw legs fight a home/away thesis
        if axis == "result" and direction == "nodraw":
            continue
        readings[axis] = direction
    return readings


def plan_thesis_axes(plan_or_legs, home: str, away: str) -> dict[str, str]:
    """Dominant read on each axis for a whole card — anchor/main legs weigh heavier."""
    if isinstance(plan_or_legs, dict):
        legs = plan_or_legs.get("legs") or []
    else:
        legs = plan_or_legs or []
    weight = {
        "anchor": 3, "main": 3, "support": 2, "swing": 2,
        "target_lotto": 1, "stake_combo": 1, "route": 1,
        "lottery": 0, "lottery2": 0,
    }
    scores: dict[str, dict[str, float]] = {}
    for leg in legs:
        role = leg.get("role") or ""
        w = weight.get(role, 1)
        if w <= 0:
            continue
        for axis, direction in _leg_axis_readings(leg, home, away).items():
            scores.setdefault(axis, {})
            scores[axis][direction] = scores[axis].get(direction, 0) + w
    merged: dict[str, str] = {}
    for axis, dirs in scores.items():
        if dirs:
            merged[axis] = max(dirs, key=dirs.get)
    return merged


def plans_contradict(
    plan_a: dict,
    plan_b: dict,
    home: str,
    away: str,
    *,
    allow_hedge: bool = False,
) -> bool:
    """True when two curated plans fight on result or goals thesis."""
    if allow_hedge or plan_b.get("is_hedge"):
        return False
    legs_a = plan_a.get("legs") or []
    legs_b = plan_b.get("legs") or []
    if not legs_a or not legs_b:
        return False

    for la in legs_a:
        for lb in legs_b:
            if spread_contradicts((la, lb), home, away):
                return True

    ta = plan_thesis_axes(legs_a, home, away)
    tb = plan_thesis_axes(legs_b, home, away)
    for axis in ("goals", "btts", "result"):
        if axis not in ta or axis not in tb:
            continue
        da, db = ta[axis], tb[axis]
        if da == db:
            continue
        if axis in ("goals", "corners", "cards") and da in ("over", "under") and db in ("over", "under"):
            return True
        if axis == "btts" and da in ("yes", "no") and db in ("yes", "no"):
            return True
        if axis == "result" and da in ("home", "away") and db in ("home", "away"):
            return True
    return False


def plan_fights_match_thesis(
    plan: dict,
    thesis: dict | None,
    home: str,
    away: str,
) -> bool:
    """True when a plan backs the wrong side (Draw or Morocco, Draw & No, either-team combos)."""
    from bet_placer.engine.match_card import _aligns_thesis

    if not thesis:
        return False
    rd = thesis.get("result_dir")
    if not rd or thesis.get("draw_scenario") or rd not in ("home", "away"):
        return False
    opp = away if rd == "home" else home
    fav = home if rd == "home" else away
    ol = opp.lower()
    fl = fav.lower()
    hl = home.lower()
    al = away.lower()

    for leg in plan.get("legs") or []:
        m = (leg.get("market") or "").lower()
        lbl = (leg.get("label") or "").lower()
        sel = (leg.get("selection") or "").lower()
        # Outright Draw fights a home/away lean
        if m == "match_winner" and (sel == "draw" or lbl.strip() in ("draw", "x")):
            return True
        if m in ("match_winner", "draw_no_bet", "asian_handicap", "half_time", "double_chance"):
            probe = type("O", (), {
                "market": m, "selection": leg.get("selection"), "label": leg.get("label"),
            })()
            if not _aligns_thesis(probe, rd, home, away):
                return True
        if m == "double_chance" and (f"draw or {ol}" in lbl or (ol in lbl and fl not in lbl)):
            return True
        if m in ("stake_combo",) or leg.get("role") == "stake_combo":
            if f"{ol} to win" in lbl or f"draw or {ol}" in lbl:
                return True
            if f"{fl}/{ol}" in lbl or f"{ol}/{fl}" in lbl:
                return True
            if "draw & no" in lbl and fl not in lbl:
                return True

    blob = " ".join(
        str(plan.get(k) or "")
        for k in ("path_headline", "label", "description", "why", "path_label", "name")
    ).lower()
    if f"draw or {ol}" in blob:
        return True
    if "draw & no" in blob and fl not in blob:
        return True
    if f"{hl}/{al}" in blob or f"{al}/{hl}" in blob:
        return True
    if f"{ol} to win" in blob and fl not in blob:
        return True
    return False


def plan_aligns_match_thesis(
    plan: dict,
    thesis: dict | None,
    home: str,
    away: str,
    *,
    slack: bool = False,
) -> bool:
    """True when a plan's profit-route read matches the match study (goals/result/BTTS)."""
    if not thesis:
        return True
    legs = plan.get("legs") or []
    if not legs:
        return False
    route_roles = {"route", "stake_combo", "target_lotto", "swing", "main", "anchor", "support"}
    route_legs = [l for l in legs if (l.get("role") or "") in route_roles]
    axis_legs = route_legs if len(route_legs) >= 1 else legs
    axes = plan_thesis_axes(axis_legs, home, away)
    for tkey, axis in (("goals_dir", "goals"), ("btts_dir", "btts"), ("result_dir", "result")):
        tdir = thesis.get(tkey)
        pdir = axes.get(axis)
        if not tdir or not pdir:
            continue
        if tdir == pdir:
            continue
        if slack and axis == "result" and thesis.get("draw_scenario"):
            continue
        return False
    return True


def filter_plans_by_thesis(
    plans: list[dict],
    anchor: dict | None,
    thesis: dict | None,
    home: str,
    away: str,
) -> list[dict]:
    """Drop plans that fight the anchor card or the match thesis."""
    kept: list[dict] = []
    for p in plans or []:
        legs = p.get("legs") or []
        if not legs or not path_is_coherent(legs, home, away):
            continue
        if anchor and plans_contradict(anchor, p, home, away):
            continue
        if thesis and not plan_aligns_match_thesis(p, thesis, home, away, slack=True):
            continue
        kept.append(p)
    return kept


def collapse_redundant_goal_legs(legs: list[dict]) -> list[dict]:
    """One goals lean per direction — drop duplicate Over/Under lines on same card."""
    if len(legs) < 2:
        return legs
    seen: dict[str, dict] = {}
    drop: set[int] = set()
    for i, leg in enumerate(legs):
        if (leg.get("market") or "").lower() != "over_under_goals":
            continue
        sel = (leg.get("selection") or "").lower()
        direction = "over" if "over" in sel else "under" if "under" in sel else ""
        if not direction:
            continue
        key = direction
        prev_i = seen.get(key)
        if prev_i is None:
            seen[key] = {"idx": i, "leg": leg}
            continue
        prev = seen[key]["leg"]
        role_rank = {"anchor": 0, "support": 1, "route": 2, "stake_combo": 2, "target_lotto": 3}
        cur_rank = role_rank.get(leg.get("role") or "", 5)
        prev_rank = role_rank.get(prev.get("role") or "", 5)
        cur_line = float(leg.get("line") or 0)
        prev_line = float(prev.get("line") or 0)
        # Keep anchor/support; among routes keep the line closer to thesis middle
        if cur_rank < prev_rank:
            drop.add(seen[key]["idx"])
            seen[key] = {"idx": i, "leg": leg}
        elif cur_rank == prev_rank:
            drop.add(i if abs(cur_line) >= abs(prev_line) else seen[key]["idx"])
            if i in drop:
                seen[key] = {"idx": seen[key]["idx"], "leg": prev}
            else:
                seen[key] = {"idx": i, "leg": leg}
        else:
            drop.add(i)
    if not drop:
        return legs
    return [l for i, l in enumerate(legs) if i not in drop]


def scrub_incoherent_legs(legs: list[dict], home: str, away: str) -> list[dict]:
    """Drop any ticket that fights the card thesis — anchors/swing legs win."""
    if len(legs) < 2:
        return legs

    priority = {
        "anchor": 0, "support": 1, "swing": 2,
        "target_lotto": 3, "lottery": 4, "lottery2": 5,
        "stake_combo": 9, "big_lotto": 10,
    }
    ordered = sorted(
        legs,
        key=lambda l: (priority.get(l.get("role"), 8), -float(l.get("odds", 0))),
    )
    kept: list[dict] = []
    seen_keys: set[tuple] = set()
    for leg in ordered:
        key = (
            (leg.get("market") or "").lower(),
            (leg.get("selection") or "").lower(),
            leg.get("line"),
            (leg.get("label") or "").lower(),
        )
        if key in seen_keys:
            continue
        if leg.get("role") == "stake_combo" or leg.get("market") == "stake_combo":
            if kept and not stake_combo_fits_card(leg, kept, home, away):
                continue
        card_side = card_result_side(kept, home, away) if kept else None
        if card_side and _opposing_team_player(leg, card_side, home, away):
            continue
        trial = kept + [leg]
        if not path_is_coherent(trial, home, away):
            continue
        seen_keys.add(key)
        kept.append(leg)
    return collapse_redundant_goal_legs(kept)


def validate_match_card_legs(
    legs: list[dict], target: float, budget: float, home: str, away: str,
    *, min_legs: int = 3, target_profit: float | None = None,
) -> tuple[bool, str]:
    """Final gate — insurance breaks even solo; swing route present."""
    if len(legs) < min_legs:
        return False, f"Need at least {min_legs} separate tickets."

    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            if spread_contradicts((legs[i], legs[j]), home, away):
                return False, f"Contradictory: {legs[i].get('label')} vs {legs[j].get('label')}"

    from bet_placer.engine.bet_portfolio import _INSURANCE_ROLES, _ROUTE_ROLES, leg_net_if_solo_win

    insurance = [l for l in legs if (l.get("role") or "") in _INSURANCE_ROLES]
    routes = [l for l in legs if (l.get("role") or "") in _ROUTE_ROLES]
    if not routes:
        routes = [l for l in legs if l not in insurance]

    profit_goal = float(target_profit if target_profit is not None else max(0, target - budget))

    anchor = next((l for l in insurance if l.get("role") == "anchor"), insurance[0] if insurance else None)
    if anchor and leg_net_if_solo_win(anchor, legs) < -10:
        partial_ok = any(
            leg_net_if_solo_win(l, legs) >= profit_goal * 0.35
            for l in routes
        )
        if not partial_ok:
            return False, (
                f"Anchor {anchor.get('label')} must break even if it wins alone."
            )

    if not routes:
        return False, "Need a swing ticket (SGM or single) alongside insurance."

    if profit_goal > 0:
        best_route_net = max((leg_net_if_solo_win(l, legs) for l in routes), default=0)
        if best_route_net < profit_goal * 0.95 and best_route_net < profit_goal * 0.35:
            return False, (
                f"Swing ticket must net at least ₹{int(profit_goal * 0.35):,} profit if it wins alone."
            )

    return True, ""


if __name__ == "__main__":
    _u = {"market": "over_under_goals", "selection": "under 1.5", "line": 1.5}
    _h = {"market": "asian_handicap", "selection": "france handicap -2.0", "line": -2.0}
    _o = {"market": "over_under_goals", "selection": "over 3.5", "line": 3.5}
    assert _goals_vs_handicap_conflict(_u, _h)
    assert not _goals_vs_handicap_conflict(_o, _h)
    assert _pair_hard_conflict(_u, _h, "France", "Morocco")
    assert not _pair_hard_conflict(_o, _h, "France", "Morocco")
