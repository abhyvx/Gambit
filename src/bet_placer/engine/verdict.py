"""Decide whether to bet on a match at all — BET / SKIP / CAUTION."""

from __future__ import annotations

from bet_placer.consensus.bettors import consensus_supports_bet
from bet_placer.consensus.web import web_supports_selection
from bet_placer.models.stake_types import BettorConsensus, MatchVerdict, Verdict, WebConsensus
from bet_placer.models.types import AnalysisResult, ValueBet


class MatchVerdictEngine:
    """
    Combines EV analysis, Stake bettor consensus, and web consensus
    to answer: should I bet on this match?
    """

    def evaluate(
        self,
        result: AnalysisResult,
        bettor_consensus: BettorConsensus | None = None,
        web_consensus: WebConsensus | None = None,
        stake_markets_scanned: int = 0,
    ) -> MatchVerdict:
        match = result.match
        value_bets = result.value_bets
        top = result.top_bets[:3] if result.top_bets else []

        reasoning: list[str] = []
        risk_flags: list[str] = []

        if not value_bets:
            return MatchVerdict(
                verdict=Verdict.SKIP,
                headline=f"SKIP — {match.home_team} vs {match.away_team}",
                reasoning=[
                    "No markets on Stake show positive expected value above threshold.",
                    "Bookmaker pricing appears efficient for this match.",
                    "Wait for line movement or better information before betting.",
                ],
                best_bet=None,
                consensus_alignment="neutral",
                stake_markets_scanned=stake_markets_scanned,
                value_bets_found=0,
                risk_flags=["no_edge"],
            )

        best = top[0]
        avg_ev = sum(b.expected_value for b in value_bets) / len(value_bets)
        avg_conf = sum(b.confidence for b in value_bets) / len(value_bets)
        max_risk = max(b.risk_score for b in value_bets)

        consensus_score = 0.0
        alignment = "neutral"

        if bettor_consensus:
            cs = consensus_supports_bet(
                bettor_consensus, best.selection, best.market.value
            )
            consensus_score += cs
            if bettor_consensus.notes:
                reasoning.extend(bettor_consensus.notes[:2])
            if bettor_consensus.contrarian_signal > 0.15 and cs > 0:
                alignment = "contrarian_edge"
                reasoning.append("Public on opposite side — potential contrarian value")
            elif cs > 0.1:
                alignment = "aligned"
            elif cs < -0.05:
                alignment = "against"
                risk_flags.append("bettor_consensus_against")

        if web_consensus and web_consensus.source_count > 0:
            ws = web_supports_selection(web_consensus, best.selection, best.market.value)
            consensus_score += ws * web_consensus.confidence
            reasoning.append(web_consensus.dominant_narrative)
            if web_consensus.fade_public:
                risk_flags.append("extreme_public_sentiment")
                reasoning.append("Internet consensus is one-sided — we may fade public, not follow it")

        # Scoring for verdict
        edge_score = min(1.0, best.expected_value / 0.15) * 0.4
        depth_score = min(1.0, len(value_bets) / 5) * 0.2
        conf_score = avg_conf * 0.25
        consensus_bonus = consensus_score * 0.15
        risk_penalty = max_risk * 0.25

        total_score = edge_score + depth_score + conf_score + consensus_bonus - risk_penalty

        if max_risk > 0.75:
            risk_flags.append("high_variance")
        if best.kelly_stake_pct > 8:
            risk_flags.append("large_kelly_suggests_uncertainty")
        if stake_markets_scanned > 0 and len(value_bets) < 2:
            risk_flags.append("thin_edge_only_one_market")

        best_label = f"{best.market.value}: {best.selection}" + (
            f" {best.line}" if best.line else ""
        ) + f" @ {best.decimal_odds:.2f} (EV {best.expected_value:+.1%})"

        if total_score >= 0.55 and best.expected_value >= 0.04 and avg_conf >= 0.6:
            verdict = Verdict.BET
            headline = f"BET — {match.home_team} vs {match.away_team}"
            reasoning.insert(0, f"Clear edge found: {best_label}")
            reasoning.append(
                f"{len(value_bets)} value market(s) identified across {stake_markets_scanned or 'available'} Stake markets"
            )
            if alignment == "contrarian_edge":
                reasoning.append("Model disagrees with public — this is where EV often lives")
        elif total_score >= 0.35 or (best.expected_value >= 0.02 and avg_conf >= 0.55):
            verdict = Verdict.CAUTION
            headline = f"CAUTION — {match.home_team} vs {match.away_team}"
            reasoning.insert(0, f"Marginal edge only: {best_label}")
            reasoning.append("Bet selectively — small stake on top pick only, skip the rest")
            if alignment == "against":
                reasoning.append("Bettor consensus disagrees with our top pick — reduce stake")
        else:
            verdict = Verdict.SKIP
            headline = f"SKIP — {match.home_team} vs {match.away_team}"
            reasoning.insert(0, "Edge too thin or signals too mixed to recommend betting")
            reasoning.append(f"Best available: {best_label} but confidence/risk profile unfavorable")

        return MatchVerdict(
            verdict=verdict,
            headline=headline,
            reasoning=reasoning,
            best_bet=best_label if verdict != Verdict.SKIP else None,
            consensus_alignment=alignment,
            stake_markets_scanned=stake_markets_scanned,
            value_bets_found=len(value_bets),
            risk_flags=risk_flags,
        )
