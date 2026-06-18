"""Plain-English betting language for non-bettors."""

from __future__ import annotations


def payout_text(stake_inr: float, odds: float) -> str:
    """What you get back if you win — the main thing bettors care about."""
    total = round(stake_inr * odds)
    profit = round(total - stake_inr)
    return f"Put {fmt(stake_inr)} → get back {fmt(total)} if it hits (profit {fmt(profit)})"


def fmt(n: float) -> str:
    return f"₹{int(round(n)):,}"


def odds_simple(odds: float) -> str:
    """No jargon — multiplier in plain terms."""
    if odds < 1.5:
        return f"heavy favourite ({odds}x payout)"
    if odds < 2.2:
        return f"slight favourite ({odds}x)"
    if odds < 3.5:
        return f"decent payout ({odds}x)"
    if odds < 6:
        return f"good payout ({odds}x) — riskier"
    return f"long shot ({odds}x) — big if it lands"


def value_label(ev_pct: float) -> str:
    if ev_pct >= 6:
        return "Great value"
    if ev_pct >= 3:
        return "Good value"
    if ev_pct >= 1:
        return "Okay — small edge"
    if ev_pct >= -1:
        return "Fair — no real edge"
    return "Bad — book has advantage"


def chance_label(prob: float) -> str:
    p = prob * 100
    if p >= 70:
        return f"Very likely ({p:.0f}%)"
    if p >= 55:
        return f"Likely ({p:.0f}%)"
    if p >= 40:
        return f"Could go either way ({p:.0f}%)"
    if p >= 25:
        return f"Unlikely but possible ({p:.0f}%)"
    return f"Long shot ({p:.0f}%)"


def recommendation_plain(rec: str) -> str:
    return {
        "BET": "✅ Worth a bet",
        "SKIP": "⏭️ Skip",
        "AVOID": "❌ Don't bet",
    }.get(rec, rec)


def stake_advice(stake: float, budget: float) -> str:
    if stake <= 0:
        return "Don't put money on this"
    pct = stake / budget * 100
    if pct >= 40:
        return f"Big chunk of your match budget ({pct:.0f}%)"
    if pct >= 20:
        return f"Sensible amount ({pct:.0f}% of match budget)"
    return f"Small safe bet ({pct:.0f}% of match budget)"


def trend_note(public_heavy_on: str | None, fade: bool) -> str | None:
    if not public_heavy_on:
        return None
    if fade:
        return f"⚠️ Everyone is on {public_heavy_on} — sometimes the crowd is wrong"
    return f"📈 Trending: most bettors backing {public_heavy_on}"
