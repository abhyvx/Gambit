"""Bettor style — what the user wants, not just what the model likes.

Picks and analysis are filtered/ranked to match an explicit goal + risk
appetite. Portfolio history can refine this later; for now the user sets it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


GOALS = {
    "preserve": {
        "label": "Protect bankroll",
        "blurb": "Fewer, higher-probability bets. Skip more matches.",
    },
    "hit_target": {
        "label": "Hit a cashout target",
        "blurb": "Size paths that can reach your ₹ goal. OK to miss some legs.",
    },
    "value": {
        "label": "Find edge / +EV",
        "blurb": "Prefer sides more likely to win; use price edge only as a tie-break.",
    },
    "fun": {
        "label": "Entertainment",
        "blurb": "Parlays and longer shots are fine — still skip garbage.",
    },
}

RISKS = {
    "low": {"label": "Low", "min_prob": 0.58, "max_picks": 2},
    "medium": {"label": "Medium", "min_prob": 0.52, "max_picks": 2},
    "high": {"label": "High", "min_prob": 0.42, "max_picks": 3},
}

STRUCTURES = {
    "singles": {"label": "One best bet", "prefer_parlay": False, "prefer_spread": False},
    "spread": {"label": "Several singles", "prefer_parlay": False, "prefer_spread": True},
    "mixed": {"label": "Singles + occasional combo", "prefer_parlay": False, "prefer_spread": True},
    "parlays": {"label": "Parlays welcome", "prefer_parlay": True, "prefer_spread": False},
}


@dataclass
class BettorStyle:
    goal: str = "preserve"
    risk: str = "medium"
    structure: str = "spread"
    sports: list[str] | None = None  # empty = all featured
    target_cashout_inr: float | None = None
    budget_inr: float = 200.0

    def __post_init__(self):
        if self.goal not in GOALS:
            self.goal = "preserve"
        if self.risk not in RISKS:
            self.risk = "medium"
        if self.structure not in STRUCTURES:
            self.structure = "spread"
        if self.sports is None:
            self.sports = []

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "BettorStyle":
        raw = raw or {}
        return cls(
            goal=str(raw.get("goal") or "preserve"),
            risk=str(raw.get("risk") or "medium"),
            structure=str(raw.get("structure") or "spread"),
            sports=list(raw.get("sports") or []),
            target_cashout_inr=(
                float(raw["target_cashout_inr"])
                if raw.get("target_cashout_inr") not in (None, "")
                else None
            ),
            budget_inr=float(raw.get("budget_inr") or 200),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        g = GOALS[self.goal]["label"]
        r = RISKS[self.risk]["label"]
        s = STRUCTURES[self.structure]["label"]
        return f"{g} · {r} risk · {s}"

    def min_probability(self) -> float:
        base = RISKS[self.risk]["min_prob"]
        if self.goal == "preserve":
            return max(base, 0.55)
        if self.goal == "value":
            # Still require majority chance — value is a tie-break, not a longshot license
            return max(base, 0.55)
        if self.goal == "fun":
            return max(min(base, 0.50), 0.50)
        return max(base, 0.55)

    def max_picks(self) -> int:
        n = RISKS[self.risk]["max_picks"]
        if self.goal == "preserve" or self.structure == "singles":
            return min(n, 2)
        if self.goal == "hit_target" or self.structure == "spread":
            return min(max(n, 2), 3)
        if self.goal == "fun" or self.structure == "parlays":
            return min(max(n, 2), 3)
        return n

    def prefer_spread(self) -> bool:
        return STRUCTURES[self.structure]["prefer_spread"] or self.goal == "hit_target"

    def avoid_parlays(self) -> bool:
        if self.structure == "parlays" or self.goal == "fun":
            return False
        if self.goal == "preserve" or self.structure == "singles":
            return True
        return not STRUCTURES[self.structure]["prefer_parlay"]

    def to_engine_betting_style(self) -> dict[str, Any]:
        """Shape expected by match_card / target_planner / bet_portfolio."""
        return {
            "prefers_spread_singles": self.prefer_spread(),
            "avoid_parlays": self.avoid_parlays(),
            "avg_bets_per_fixture": float(self.max_picks()),
            "min_probability": self.min_probability(),
            "max_picks": self.max_picks(),
            "goal": self.goal,
            "risk": self.risk,
            "structure": self.structure,
            "summary": self.summary(),
        }


def _bet_prob(bet: dict[str, Any]) -> float:
    return float(
        bet.get("true_probability")
        or bet.get("our_probability")
        or bet.get("probability")
        or 0
    )


def _bet_edge(bet: dict[str, Any]) -> float:
    return float(bet.get("edge") or bet.get("edge_pct") or bet.get("ev") or 0)


def _is_parlayish(bet: dict[str, Any]) -> bool:
    market = str(bet.get("market") or bet.get("market_type") or "").lower()
    label = str(bet.get("label") or bet.get("selection") or "").lower()
    return "parlay" in market or "combo" in market or " & " in label


def curate_bets(bets: list[dict[str, Any]], style: BettorStyle) -> list[dict[str, Any]]:
    """Filter and rank raw value bets for this bettor's style."""
    min_p = style.min_probability()
    capped = style.max_picks()
    out: list[dict[str, Any]] = []
    for b in bets or []:
        if style.avoid_parlays() and _is_parlayish(b):
            continue
        if _bet_prob(b) < min_p and style.goal != "value":
            continue
        if style.goal == "value" and _bet_edge(b) <= 0 and _bet_prob(b) < min_p:
            continue
        out.append(b)

    if style.goal == "value":
        # Probability first, then edge — never lead with likely losers
        out.sort(key=lambda b: (_bet_prob(b), _bet_edge(b)), reverse=True)
    elif style.goal == "preserve":
        out.sort(key=lambda b: (_bet_prob(b), _bet_edge(b)), reverse=True)
    elif style.goal == "hit_target":
        # Prefer mid-odds that can move a cashout, then probability
        def _target_key(b: dict) -> tuple:
            odds = float(b.get("decimal_odds") or b.get("odds") or 1)
            return (1.4 <= odds <= 6.0, _bet_prob(b), odds)
        out.sort(key=_target_key, reverse=True)
    else:
        out.sort(key=lambda b: (b.get("rank_score") or _bet_edge(b), _bet_prob(b)), reverse=True)

    return out[:capped]


def style_meta(style: BettorStyle) -> dict[str, Any]:
    return {
        "style": style.to_dict(),
        "summary": style.summary(),
        "min_probability": style.min_probability(),
        "max_picks": style.max_picks(),
        "goal_label": GOALS[style.goal]["label"],
        "goal_blurb": GOALS[style.goal]["blurb"],
        "catalog": {
            "goals": [{"id": k, **v} for k, v in GOALS.items()],
            "risks": [{"id": k, "label": v["label"]} for k, v in RISKS.items()],
            "structures": [{"id": k, "label": v["label"]} for k, v in STRUCTURES.items()],
        },
    }


def resolve_engine_style(
    goal: str | None = None,
    risk: str | None = None,
    structure: str | None = None,
    *,
    budget_inr: float | None = None,
    target_cashout_inr: float | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """User Settings style wins; portfolio profile is fallback only.

    Callers used to hardcode portfolio prefers_spread / avoid_parlays, so every
    slip looked the same regardless of goal/risk/structure.
    """
    payload: dict[str, Any] = dict(raw or {})
    if goal:
        payload["goal"] = goal
    if risk:
        payload["risk"] = risk
    if structure:
        payload["structure"] = structure
    if budget_inr is not None:
        payload["budget_inr"] = budget_inr
    if target_cashout_inr is not None:
        payload["target_cashout_inr"] = target_cashout_inr

    has_user = any(payload.get(k) for k in ("goal", "risk", "structure"))
    if has_user:
        style = BettorStyle.from_dict(payload)
        return style.to_engine_betting_style()

    try:
        from bet_placer.portfolio.store import get_portfolio_profile
        prof = get_portfolio_profile() or {}
        if any(prof.get(k) is not None for k in (
            "prefers_spread_singles", "avoid_parlays", "avg_bets_per_fixture",
        )):
            return {
                "prefers_spread_singles": prof.get("prefers_spread_singles", True),
                "avoid_parlays": prof.get("avoid_parlays", False),
                "avg_bets_per_fixture": float(prof.get("avg_bets_per_fixture") or 2),
                "goal": prof.get("goal") or "value",
                "risk": prof.get("risk") or "medium",
                "structure": prof.get("structure") or "spread",
                "summary": prof.get("summary") or "Portfolio profile",
            }
    except Exception:
        pass
    return BettorStyle.from_dict(payload).to_engine_betting_style()


def spend_pct_for_style(style: BettorStyle | dict[str, Any] | None) -> float:
    """How much of the match budget to actually put on picks."""
    if isinstance(style, dict):
        style = BettorStyle.from_dict(style)
    if style is None:
        return 0.85
    pct = 0.85
    if style.goal == "preserve" or style.risk == "low":
        pct = 0.55
    elif style.goal == "hit_target":
        pct = 0.92
    elif style.goal == "fun" or style.risk == "high":
        pct = 0.80
    if style.structure == "singles":
        pct = min(pct, 0.70)
    return pct


# ponytail: one assert-based check — fails if curation ever returns parlays for preserve
if __name__ == "__main__":
    s = BettorStyle(goal="preserve", risk="low", structure="singles")
    sample = [
        {"label": "Home win", "true_probability": 0.62, "edge": 0.05, "decimal_odds": 1.7},
        {"label": "A & B", "true_probability": 0.7, "edge": 0.1, "decimal_odds": 2.0, "market": "parlay"},
        {"label": "Longshot", "true_probability": 0.3, "edge": 0.2, "decimal_odds": 5.0},
    ]
    curated = curate_bets(sample, s)
    assert len(curated) <= 2
    assert all(not _is_parlayish(b) for b in curated)
    assert all(_bet_prob(b) >= s.min_probability() for b in curated)
    eng = resolve_engine_style(goal="parlays", risk="high", structure="parlays")
    # invalid goal falls back inside from_dict → preserve; use fun+parlays
    eng = resolve_engine_style(goal="fun", risk="high", structure="parlays")
    assert eng["avoid_parlays"] is False
    assert eng["prefers_spread_singles"] is False
    assert spend_pct_for_style(s) < spend_pct_for_style(BettorStyle(goal="hit_target"))
    print("bettor_style ok", s.summary(), "→", [b["label"] for b in curated])
