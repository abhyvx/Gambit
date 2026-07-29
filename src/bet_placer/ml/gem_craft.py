"""Match-specific gem spotting — not a fixed formula per game.

Each match is scored from its own slip stack (easy money / spotlight /
niche edges / curated card) or, for the fast paper loop, from that match's
multi-market model probabilities. Learned craft weights nudge which kinds of
gems we keep taking after paper-book outcomes.
"""

from __future__ import annotations

from typing import Any

# Core winner alone is rarely "the gem" — prefer niche / high-bar singles.
_NICHE = frozenset({
    "btts", "over_under_goals", "asian_handicap", "handicap", "double_chance",
    "draw_no_bet", "corners", "cards", "player_goal", "team_first_goal",
    "half_time", "stake_combo", "situation",
})
_CORE_OK = frozenset({"match_winner", "moneyline"})

MAX_GEMS_PER_MATCH = 4
MIN_GEM_PROB = 0.48
MIN_NICHE_EDGE = 0.02

_GROUP_TO_MARKET = {
    "result": "match_winner",
    "btts": "btts",
    "totals": "over_under_goals",
    "handicap": "asian_handicap",
}


def load_craft_weights() -> dict[str, Any]:
    try:
        from bet_placer.ml.params import load_params
        return dict((load_params().get("craft_learning") or {}).get("weights") or {})
    except Exception:
        return {}


def _w(weights: dict, key: str, default: float = 1.0) -> float:
    try:
        return float(weights.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _leg_key(leg: dict) -> str:
    m = (leg.get("market") or "").lower()
    s = (leg.get("selection") or leg.get("label") or "").lower()
    line = leg.get("line")
    return f"{m}|{s}|{line}"


def _prob(leg: dict) -> float:
    return float(
        leg.get("our_probability")
        or leg.get("true_probability")
        or leg.get("win_probability")
        or 0
    )


def _odds(leg: dict) -> float:
    try:
        o = float(leg.get("odds") or leg.get("decimal_odds") or 0)
    except (TypeError, ValueError):
        return 0.0
    return o if o > 1.0 else 0.0


def _edge(leg: dict) -> float:
    if leg.get("edge_pct") is not None:
        try:
            return float(leg["edge_pct"]) / 100.0
        except (TypeError, ValueError):
            pass
    p, o = _prob(leg), _odds(leg)
    if p > 0 and o > 1:
        return p - (1.0 / o)
    return float(leg.get("expected_value") or 0)


def _kind_score(kind: str, market: str, weights: dict) -> float:
    base = {
        "spotlight": 1.35,
        "easy_money": 1.30,
        "niche": 1.20,
        "card_leg": 1.05,
        "single": 0.95,
    }.get(kind, 1.0)
    return base * _w(weights, f"kind:{kind}") * _w(weights, f"market:{market or 'other'}")


def _score_leg(leg: dict, kind: str, weights: dict) -> float:
    market = (leg.get("market") or "").lower()
    p = _prob(leg)
    score = (
        _kind_score(kind, market, weights)
        * (0.55 + 0.45 * max(p, 0.4))
        * (1.0 + max(0.0, min(_edge(leg), 0.25)))
    )
    if market in _CORE_OK and kind not in ("spotlight", "easy_money") and p < 0.62:
        score *= 0.55
    return score


def spot_gems_from_events(
    events: list[tuple[str, str, float]],
    *,
    craft_weights: dict | None = None,
    max_gems: int = MAX_GEMS_PER_MATCH,
) -> list[dict[str, Any]]:
    """Fast match-specific gems from this game's model markets (no full slip)."""
    weights = craft_weights if craft_weights is not None else load_craft_weights()
    # Paper craft: take several angles per match, not only the ultra-strict bar
    by_group: dict[str, list[tuple[str, str, float]]] = {}
    for grp, sel, p in events or []:
        if p is None:
            continue
        by_group.setdefault(grp, []).append((grp, sel, float(p)))

    raw: list[tuple[str, str, float]] = []
    for grp, floor in (("result", 0.42), ("btts", 0.52), ("totals", 0.52), ("handicap", 0.55)):
        rows = sorted(by_group.get(grp) or [], key=lambda x: -x[2])
        taken = 0
        for row in rows:
            # skip absurd overconfidence — not a real market read
            if row[2] > 0.78:
                continue
            if row[2] >= floor:
                raw.append(row)
                taken += 1
            if taken >= (1 if grp == "handicap" else 2):
                break
    # Prefer result / niche totals over extreme handicaps when sorting
    raw = sorted(raw, key=lambda x: (
        0 if x[0] == "result" else 1 if x[0] in ("btts", "totals") else 2,
        -x[2],
    ))
    seen = set()
    picks = []
    for row in raw:
        key = (row[0], row[1])
        if key in seen:
            continue
        seen.add(key)
        picks.append(row)
        if len(picks) >= max(max_gems, 3):
            break

    gems: list[dict[str, Any]] = []
    for grp, sel, p in picks:
        market = _GROUP_TO_MARKET.get(grp, grp)
        kind = "niche" if grp != "result" else ("easy_money" if p >= 0.65 else "single")
        line = None
        label = sel
        selection = sel
        if grp == "totals":
            # Formats: "over|219.5", "home_over|112.5", or legacy "over_219.5"
            raw_sel = sel
            if "|" in raw_sel:
                selection, _, rest = raw_sel.partition("|")
                try:
                    line = float(rest)
                except ValueError:
                    line = None
            elif "_" in raw_sel:
                # home_over_112.5 / over_219.5
                parts = raw_sel.rsplit("_", 1)
                try:
                    line = float(parts[-1])
                    selection = parts[0]
                except ValueError:
                    side, _, rest = raw_sel.partition("_")
                    selection = side
                    try:
                        line = float(rest)
                    except ValueError:
                        line = None
            unit = "pts" if (line or 0) >= 50 else "goals"
            if selection in ("home_over", "home_under", "away_over", "away_under"):
                side = "Over" if selection.endswith("over") else "Under"
                who = "Home" if selection.startswith("home") else "Away"
                label = f"{who} {side} {line}" if line is not None else f"{who} {side}"
            else:
                label = f"{selection.title()} {line} {unit}".strip() if line is not None else selection
        elif grp == "handicap" and "_" in sel:
            side, _, rest = sel.partition("_")
            try:
                line = float(rest)
            except ValueError:
                line = None
            selection = side
            label = f"{side.title()} {rest}" if rest else sel
            kind = "niche"
        elif grp == "btts":
            label = f"BTTS {sel.title()}"
        elif grp == "result":
            label = {"home": "Home", "away": "Away", "draw": "Draw"}.get(sel, sel)
        fair_p = min(max(float(p), 0.28), 0.72)
        fair = 1.0 / fair_p
        vig = 0.96 if fair_p >= 0.58 else 0.93
        odds = round(max(1.28, min(4.0, fair * vig)), 3)
        # Tag synthetic — craft ROI gate must not treat this as book CLV
        leg = {
            "market": market,
            "selection": selection,
            "label": label,
            "line": line,
            "our_probability": float(p),
            "odds": odds,
            "odds_source": "synthetic_fair",
            "edge_pct": round((p - 1.0 / odds) * 100, 2) if odds > 1 else 0,
            "gem_kind": kind,
            "gem_why": f"{market} p≈{round(p * 100)}%",
        }
        leg["gem_score"] = round(_score_leg(leg, kind, weights), 4)
        gems.append(leg)
    gems.sort(key=lambda g: -float(g.get("gem_score") or 0))
    return gems[: max(1, max_gems)]


def spot_match_gems(
    *,
    unified: dict | None = None,
    slip_data: dict | None = None,
    flat: list | None = None,
    craft_weights: dict | None = None,
    max_gems: int = MAX_GEMS_PER_MATCH,
) -> list[dict[str, Any]]:
    """Pick the specific angles for THIS match — different mix every time."""
    weights = craft_weights if craft_weights is not None else load_craft_weights()
    unified = unified or {}
    slip_data = slip_data or {}
    flat = list(flat or [])
    gems: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(leg: dict, kind: str, why: str) -> None:
        if not leg:
            return
        key = _leg_key(leg)
        if key in seen:
            return
        market = (leg.get("market") or "").lower()
        p = _prob(leg)
        if p and p < MIN_GEM_PROB and kind not in ("spotlight", "easy_money"):
            return
        tier = ((leg.get("verdict") or {}) if isinstance(leg.get("verdict"), dict) else {}).get("tier")
        if tier in ("trap", "bad"):
            return
        score = _score_leg(leg, kind, weights)
        seen.add(key)
        gems.append({
            **leg,
            "gem_kind": kind,
            "gem_score": round(score, 4),
            "gem_why": why,
            "market": market or leg.get("market"),
            "our_probability": p or _prob(leg),
            "odds": _odds(leg) or leg.get("odds"),
        })

    spot = unified.get("spotlight")
    if isinstance(spot, dict):
        _add(spot, "spotlight", spot.get("why") or "Match spotlight — highest-confidence read")
    for em in (unified.get("easy_money") or [])[:2]:
        _add(em, "easy_money", em.get("why") or "Cleared the high-confidence bar for this game")

    for o in flat:
        market = (o.get("market") or "").lower()
        if market not in _NICHE:
            continue
        if _prob(o) < MIN_GEM_PROB:
            continue
        if _edge(o) < MIN_NICHE_EDGE and _prob(o) < 0.58:
            continue
        why = (
            f"Niche {market} edge for this matchup"
            + (f" (~{round(_prob(o)*100)}%)" if _prob(o) else "")
        )
        _add(o, "niche", why)

    curated = slip_data.get("curated_picks") or {}
    primary = curated.get("primary") or {}
    for leg in (primary.get("legs") or [])[:3]:
        market = (leg.get("market") or "").lower()
        kind = "niche" if market in _NICHE else "card_leg"
        _add(leg, kind, primary.get("why") or "From the curated match card for this game")

    if len(gems) < 2:
        for u in (unified.get("unified_picks") or [])[:4]:
            _add(u, "single", u.get("why") or "Situational single for this match")

    gems.sort(key=lambda g: -float(g.get("gem_score") or 0))
    return gems[: max(1, max_gems)]


def update_craft_weights_from_tickets(tickets: list[dict]) -> dict[str, float]:
    """Online craft signal: boost gem kinds / markets that cash, dampen misses."""
    from collections import defaultdict

    stats: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0.0, "hits": 0.0})
    for t in tickets or []:
        if t.get("status") not in ("won", "lost"):
            continue
        kind = t.get("gem_kind") or "single"
        market = (t.get("market") or "other").lower()
        hit = 1.0 if t.get("status") == "won" else 0.0
        for key in (f"kind:{kind}", f"market:{market}"):
            stats[key]["n"] += 1
            stats[key]["hits"] += hit

    weights: dict[str, float] = {}
    for key, s in stats.items():
        if s["n"] < 2:
            weights[key] = 1.0
            continue
        rate = s["hits"] / s["n"]
        weights[key] = round(max(0.55, min(1.35, 0.55 + rate)), 3)
    return weights
