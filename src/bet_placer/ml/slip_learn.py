"""Learn craft / strategy weights from user bet-slip tickets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bet_placer.ml.paper_book import apply_paper_learning, load_book, save_book, summarize


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_slip_tickets(legs: list[dict[str, Any]]) -> dict[str, Any]:
    """Append open user-slip tickets into the paper book for later grading."""
    book = load_book()
    existing = {t.get("id") for t in (book.get("tickets") or [])}
    placed = 0
    bank = float(book.get("bankroll") or 0)
    for leg in legs or []:
        tid = str(leg.get("id") or "").strip()
        if not tid or tid in existing:
            continue
        odds = float(leg.get("odds") or 0)
        if odds <= 1.0:
            continue
        # Unit-track recs even before the user types a stake (model learning).
        stake = float(leg.get("stake") or 0)
        if stake < 1:
            stake = 1.0
        if stake > bank * 0.5 and bank > 0:
            stake = min(stake, max(10.0, bank * 0.05))
        ticket = {
            "id": tid,
            "match_id": leg.get("eventId") or leg.get("match_id") or tid,
            "home": leg.get("home"),
            "away": leg.get("away"),
            "sport": leg.get("sport") or leg.get("sportKey"),
            "market": str(leg.get("market") or "match_winner").lower(),
            "selection": leg.get("selection") or leg.get("label"),
            "label": leg.get("label") or leg.get("selection"),
            "line": leg.get("line"),
            "odds": odds,
            "stake": round(stake, 2),
            "gem_kind": leg.get("gem_kind") or "user_slip",
            "our_probability": leg.get("our_probability"),
            "placed_at": _now(),
            "status": "open",
            "source": "user_slip",
        }
        bank = max(0.0, bank - stake)
        book.setdefault("tickets", []).append(ticket)
        existing.add(tid)
        placed += 1
    book["bankroll"] = round(bank, 2)
    book["updated_at"] = _now()
    save_book(book)
    return {"placed": placed, "summary": summarize(book)}


def settle_slip_ticket(ticket_id: str, *, won: bool, sport: str | None = None) -> dict[str, Any]:
    """Mark one user-slip ticket won/lost and blend into craft learning."""
    book = load_book()
    tid = str(ticket_id or "").strip()
    hit = None
    for t in book.get("tickets") or []:
        if t.get("id") != tid:
            continue
        if t.get("status") in ("won", "lost"):
            hit = t
            break
        stake = float(t.get("stake") or 0)
        odds = float(t.get("odds") or 0)
        t["status"] = "won" if won else "lost"
        t["hit"] = bool(won)
        t["return_inr"] = round(stake * odds, 2) if won else 0.0
        t["pnl"] = round(float(t["return_inr"]) - stake, 2)
        t["settled_at"] = _now()
        if sport and not t.get("sport"):
            t["sport"] = sport
        book["bankroll"] = round(float(book.get("bankroll") or 0) + float(t["return_inr"] or 0), 2)
        hit = t
        break
    if not hit:
        return {"ok": False, "error": "ticket_not_found"}
    book.setdefault("curve", []).append({"t": _now(), "bankroll": book["bankroll"]})
    book["updated_at"] = _now()
    save_book(book)
    params = apply_paper_learning(book=book)
    return {
        "ok": True,
        "ticket": hit,
        "craft_learning": (params or {}).get("craft_learning"),
        "summary": summarize(book),
    }
