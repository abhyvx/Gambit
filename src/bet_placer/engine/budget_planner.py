"""INR budget planner — concrete bet slip for student pocket money."""

from __future__ import annotations

from dataclasses import dataclass, field

from bet_placer.engine.bankroll import recommend_stake
from bet_placer.engine.ev import compute_ev
from bet_placer.models.stake_types import Verdict


@dataclass
class SingleBet:
    match: str
    market: str
    selection: str
    line: float | None
    odds: float
    stake_inr: float
    ev_pct: float
    true_prob: float
    risk: str
    reason: str


@dataclass
class ParlayLeg:
    match: str
    market: str
    selection: str
    odds: float


@dataclass
class ParlayBet:
    legs: list[ParlayLeg]
    combined_odds: float
    stake_inr: float
    potential_return_inr: float
    true_prob: float
    ev_pct: float
    risk: str
    reason: str


@dataclass
class BettingPlan:
    budget_inr: float
    currency: str = "INR"
    singles: list[SingleBet] = field(default_factory=list)
    parlays: list[ParlayBet] = field(default_factory=list)
    skip_matches: list[dict] = field(default_factory=list)
    total_staked_inr: float = 0.0
    total_remaining_inr: float = 0.0
    summary: str = ""
    verdict_overall: str = ""  # bet | partial | skip_all
    rules: list[str] = field(default_factory=list)


STUDENT_PRESETS = [500, 1000, 2000, 3000, 5000]


def build_betting_plan(
    match_analyses: list[dict],
    budget_inr: float = 2000.0,
) -> BettingPlan:
    """
    Concrete plan: which singles, which parlays, what to skip.
    Designed for student pocket money in INR.
    """
    plan = BettingPlan(budget_inr=budget_inr)
    plan.rules = [
        f"Total budget: ₹{budget_inr:,.0f} — never exceed this",
        "Max 5% (₹{:,.0f}) per single bet".format(budget_inr * 0.05),
        "Max 2% (₹{:,.0f}) on any parlay".format(budget_inr * 0.02),
        "Skip any match with SKIP verdict — no exceptions",
        "Only bet singles you're confident in; parlays are optional fun, not core strategy",
    ]

    all_value_bets: list[dict] = []
    for ma in match_analyses:
        verdict = ma.get("verdict", {}).get("verdict", "skip")
        match_name = ma.get("name", "")
        if verdict == "skip":
            plan.skip_matches.append({
                "match": match_name,
                "reason": ma.get("verdict", {}).get("headline", "No edge"),
            })
            continue
        for bet in ma.get("value_bets", []):
            bet["_match_name"] = match_name
            bet["_verdict"] = verdict
            all_value_bets.append(bet)

    all_value_bets.sort(key=lambda b: b.get("rank_score", 0), reverse=True)

    remaining = budget_inr
    max_single = budget_inr * 0.05
    max_parlay = budget_inr * 0.02

    # Top singles — up to 3, only BET verdict matches get full stake
    singles_added = 0
    for bet in all_value_bets:
        if singles_added >= 3 or remaining < 50:
            break
        if bet.get("_verdict") == "skip":
            continue

        rec = recommend_stake(
            bet["true_probability"], bet["decimal_odds"],
            bet["confidence"], bet["risk_score"], budget_inr,
        )
        # Convert to INR-friendly round numbers
        stake = min(rec.recommended_stake, max_single, remaining)
        stake = _round_inr(stake, budget_inr)
        if stake < 20:
            continue

        plan.singles.append(SingleBet(
            match=bet["_match_name"],
            market=bet["market"],
            selection=bet["selection"],
            line=bet.get("line"),
            odds=bet["decimal_odds"],
            stake_inr=stake,
            ev_pct=bet["expected_value"] * 100,
            true_prob=bet["true_probability"],
            risk=rec.risk_level,
            reason=bet.get("explanation", "")[:200],
        ))
        remaining -= stake
        singles_added += 1

    # One conservative 2-leg parlay from top low-risk singles
    if len(plan.singles) >= 2 and remaining >= 30:
        leg1, leg2 = plan.singles[0], plan.singles[1]
        if leg1.risk != "high" and leg2.risk != "high":
            combined = leg1.odds * leg2.odds
            true_p = leg1.true_prob * leg2.true_prob
            ev = compute_ev(true_p, combined)
            parlay_stake = min(max_parlay, remaining, _round_inr(budget_inr * 0.015, budget_inr))
            if parlay_stake >= 20 and ev > -0.05:
                plan.parlays.append(ParlayBet(
                    legs=[
                        ParlayLeg(leg1.match, leg1.market, leg1.selection, leg1.odds),
                        ParlayLeg(leg2.match, leg2.market, leg2.selection, leg2.odds),
                    ],
                    combined_odds=round(combined, 2),
                    stake_inr=parlay_stake,
                    potential_return_inr=round(parlay_stake * combined, 0),
                    true_prob=true_p,
                    ev_pct=ev * 100,
                    risk="high",
                    reason="Optional 2-leg parlay — higher risk, only use leftover budget. Both legs must win.",
                ))
                remaining -= parlay_stake

    plan.total_staked_inr = budget_inr - remaining
    plan.total_remaining_inr = remaining

    if not plan.singles and not plan.parlays:
        plan.verdict_overall = "skip_all"
        plan.summary = (
            f"With ₹{budget_inr:,.0f} budget: **Do not bet today.** "
            f"No group stage matches show enough edge. Keep your ₹{budget_inr:,.0f}."
        )
    elif plan.singles:
        plan.verdict_overall = "bet"
        s_total = sum(s.stake_inr for s in plan.singles)
        p_total = sum(p.stake_inr for p in plan.parlays)
        plan.summary = (
            f"From ₹{budget_inr:,.0f} budget: Stake ₹{s_total:,.0f} on {len(plan.singles)} single(s)"
            + (f", ₹{p_total:,.0f} on {len(plan.parlays)} parlay" if plan.parlays else "")
            + f". Keep ₹{remaining:,.0f} unbet as safety buffer."
        )
    else:
        plan.verdict_overall = "partial"
        plan.summary = f"Marginal edges only. Consider keeping your ₹{budget_inr:,.0f}."

    return plan


def _round_inr(amount: float, budget: float) -> float:
    """Round to student-friendly amounts."""
    if budget <= 500:
        return max(20, round(amount / 10) * 10)
    if budget <= 2000:
        return max(20, round(amount / 25) * 25)
    return max(50, round(amount / 50) * 50)
