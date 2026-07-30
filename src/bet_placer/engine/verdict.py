"""Decide whether to bet on a match at all - BET / SKIP / CAUTION."""

from __future__ import annotations

from bet_placer.consensus.bettors import consensus_supports_bet
from bet_placer.consensus.web import web_supports_selection
from bet_placer.markets.labels import format_market_label
from bet_placer.models.stake_types import BettorConsensus, MatchVerdict, Verdict, WebConsensus
from bet_placer.models.types import AnalysisResult, ValueBet


def _plain(text: str) -> str:
    """Ticket / headline copy: plain hyphen, never em/en dash."""
    return (
        str(text or "")
        .replace("\u2014", " - ")
        .replace("\u2013", " - ")
        .replace("  -  ", " - ")
    )


def _human_selection(match, market, selection, line=None) -> str:
    home = getattr(match, "home_team", None) or ""
    away = getattr(match, "away_team", None) or ""
    m = market.value if hasattr(market, "value") else str(market or "")
    try:
        return format_market_label(m, selection, line, home, away)
    except Exception:
        sel = str(selection or "")
        if sel == "home" and home:
            return f"{home} to win"
        if sel == "away" and away:
            return f"{away} to win"
        if sel in ("draw", "x"):
            return "Draw"
        return sel or m


def _pick_label(bet: ValueBet, match=None) -> str:
    m = bet.market.value if hasattr(bet.market, "value") else str(bet.market)
    short = _human_selection(match, m, bet.selection, bet.line) if match is not None else None
    if not short:
        # Fallback without match context - still never emit market:selection
        if bet.selection in ("home", "away", "draw", "x"):
            short = {"home": "Home to win", "away": "Away to win", "draw": "Draw", "x": "Draw"}[
                bet.selection
            ]
        else:
            short = str(bet.selection or m)
    if bet.line is not None and str(bet.line) not in short:
        short = f"{short} {bet.line}"
    return _plain(f"{short} @ {bet.decimal_odds:.2f}")


def _edge_line(bet: ValueBet, match=None) -> str:
    model_pct = round(bet.true_probability * 100)
    book_pct = round((1 / bet.decimal_odds) * 100) if bet.decimal_odds > 1 else 0
    return _plain(
        f"{_pick_label(bet, match)} - model {model_pct}% vs book ~{book_pct}% "
        f"(EV {bet.expected_value:+.0%})"
    )


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
            n_mkts = stake_markets_scanned or len(getattr(match, "market_odds", None) or [])
            # Prefer a priced lean over blank SKIP - board always has something to consider.
            probs = list(getattr(result, "probabilities", None) or [])
            def _mkt(p):
                return p.market.value if hasattr(p.market, "value") else str(p.market)
            # Prefer moneyline lean for the headline - not an exotic handicap.
            core = [p for p in probs if _mkt(p) in ("match_winner", "draw_no_bet")]
            pool = core or probs
            top_p = max(pool, key=lambda p: (p.probability, p.confidence), default=None)
            reasons = [
                f"No clear +EV across {n_mkts or 'available'} priced line(s).",
            ]
            if bettor_consensus and bettor_consensus.notes:
                reasons.extend(bettor_consensus.notes[:2])
            if web_consensus and web_consensus.dominant_narrative:
                reasons.append(web_consensus.dominant_narrative)
            if top_p is not None and top_p.probability >= 0.48:
                mkt = top_p.market.value if hasattr(top_p.market, "value") else str(top_p.market)
                short = _human_selection(match, mkt, top_p.selection, top_p.line)
                if top_p.line is not None and str(top_p.line) not in short:
                    short = f"{short} {top_p.line}"
                reasons.insert(
                    0,
                    _plain(f"Best model lean: {short} (~{round(top_p.probability * 100)}%)."),
                )
                reasons.append("Size small - verify live price on Stake.")
                return MatchVerdict(
                    verdict=Verdict.CAUTION,
                    headline=_plain(f"CAUTION - {short}"),
                    reasoning=[_plain(r) for r in reasons],
                    best_bet=_plain(short),
                    consensus_alignment="neutral",
                    stake_markets_scanned=stake_markets_scanned,
                    value_bets_found=0,
                    risk_flags=["model_lean_only"],
                )
            reasons.append("No clear edge - use board prices or open the slip for model paths.")
            return MatchVerdict(
                verdict=Verdict.CAUTION,
                headline="CAUTION - thin board",
                reasoning=[_plain(r) for r in reasons],
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
                reasoning.append("Public leans the other way - possible contrarian value.")
            elif cs > 0.1:
                alignment = "aligned"
            elif cs < -0.05:
                alignment = "against"
                risk_flags.append("bettor_consensus_against")

        if web_consensus and web_consensus.source_count > 0:
            ws = web_supports_selection(web_consensus, best.selection, best.market.value)
            consensus_score += ws * web_consensus.confidence
            if web_consensus.dominant_narrative:
                reasoning.append(web_consensus.dominant_narrative)
            if web_consensus.fade_public:
                risk_flags.append("extreme_public_sentiment")
                reasoning.append("Crowd is one-sided - we fade public, not chase it.")

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

        best_label = _edge_line(best, match)
        short = _pick_label(best, match)

        if total_score >= 0.55 and best.expected_value >= 0.04 and avg_conf >= 0.6:
            verdict = Verdict.BET
            headline = _plain(f"BET - {short}")
            reasoning.insert(0, f"Clear edge: {best_label}")
            reasoning.append(f"{len(value_bets)} priced value side(s); avg EV {avg_ev:+.0%}.")
            if alignment == "contrarian_edge":
                reasoning.append("Model disagrees with the public - that's often where EV lives.")
        elif total_score >= 0.35 or (best.expected_value >= 0.02 and avg_conf >= 0.55):
            verdict = Verdict.CAUTION
            headline = _plain(f"CAUTION - {short}")
            reasoning.insert(0, f"Thin edge only: {best_label}")
            reasoning.append("Small stake on the top pick - skip the rest.")
            if alignment == "against":
                reasoning.append("Bettor consensus disagrees - cut the stake further.")
        else:
            verdict = Verdict.CAUTION
            headline = _plain(f"CAUTION - {short}")
            reasoning.insert(0, "Signals mixed - still a usable lean, size down.")
            reasoning.append(f"Best available was {best_label}.")

        return MatchVerdict(
            verdict=verdict,
            headline=headline,
            reasoning=[_plain(r) for r in reasoning],
            best_bet=short,
            consensus_alignment=alignment,
            stake_markets_scanned=stake_markets_scanned,
            value_bets_found=len(value_bets),
            risk_flags=risk_flags,
        )
