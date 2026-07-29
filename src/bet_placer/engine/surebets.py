"""Surebet / arb scanner — lock positive return when books disagree.

Uses best available prices across books (Odds API multi-book, SkipOdds, Stake,
football-data B365 vs Avg). Surfaces only when net return clears a floor.
"""

from __future__ import annotations

from typing import Any


def arb_roi(prices: list[float]) -> float | None:
    """Return locked ROI if sum(1/odds) < 1, else None. prices are decimal odds > 1."""
    inv = 0.0
    for o in prices:
        if not o or o <= 1.01:
            return None
        inv += 1.0 / float(o)
    if inv <= 0 or inv >= 1.0:
        return None
    return round((1.0 / inv) - 1.0, 4)


def stakes_for_arb(budget: float, prices: list[float]) -> list[float] | None:
    roi = arb_roi(prices)
    if roi is None or budget <= 0:
        return None
    inv = sum(1.0 / p for p in prices)
    return [round(budget * (1.0 / p) / inv, 2) for p in prices]


def scan_h2h_books(
    books: list[dict[str, Any]],
    *,
    min_roi: float = 0.01,
) -> dict[str, Any] | None:
    """books: [{book, home, draw?, away}, ...]. 2-way or 3-way.

    Picks the best (max) price per side across books, then checks arb.
    """
    if len(books) < 2:
        return None
    best_h = best_d = best_a = None
    src_h = src_d = src_a = None
    for b in books:
        name = b.get("book") or b.get("key") or "?"
        h, d, a = b.get("home"), b.get("draw"), b.get("away")
        if h and (best_h is None or float(h) > best_h):
            best_h, src_h = float(h), name
        if d and (best_d is None or float(d) > best_d):
            best_d, src_d = float(d), name
        if a and (best_a is None or float(a) > best_a):
            best_a, src_a = float(a), name
    if best_h is None or best_a is None:
        return None
    if best_d is not None:
        prices = [best_h, best_d, best_a]
        legs = [
            {"side": "home", "odds": best_h, "book": src_h},
            {"side": "draw", "odds": best_d, "book": src_d},
            {"side": "away", "odds": best_a, "book": src_a},
        ]
    else:
        prices = [best_h, best_a]
        legs = [
            {"side": "home", "odds": best_h, "book": src_h},
            {"side": "away", "odds": best_a, "book": src_a},
        ]
    roi = arb_roi(prices)
    if roi is None or roi < min_roi:
        return None
    return {
        "kind": "surebet",
        "roi": roi,
        "legs": legs,
        "n_books": len(books),
    }


def books_from_odds_api_event(event: dict) -> list[dict[str, Any]]:
    """Extract per-bookmaker h2h from an Odds API event dict."""
    home = event.get("home_team") or ""
    away = event.get("away_team") or ""
    out: list[dict[str, Any]] = []
    for bm in event.get("bookmakers") or []:
        h = d = a = None
        for mkt in bm.get("markets") or []:
            if mkt.get("key") != "h2h":
                continue
            for o in mkt.get("outcomes") or []:
                name = (o.get("name") or "").strip()
                price = o.get("price")
                if not price:
                    continue
                if name == home:
                    h = float(price)
                elif name == away:
                    a = float(price)
                elif name.lower() == "draw":
                    d = float(price)
        if h and a:
            out.append({"book": bm.get("title") or bm.get("key"), "home": h, "draw": d, "away": a})
    return out


def scan_event_surebet(event: dict, *, min_roi: float = 0.01) -> dict[str, Any] | None:
    hit = scan_h2h_books(books_from_odds_api_event(event), min_roi=min_roi)
    if not hit:
        return None
    return {
        **hit,
        "home": event.get("home_team"),
        "away": event.get("away_team"),
        "commence_time": event.get("commence_time"),
        "sport_key": event.get("sport_key"),
        "id": event.get("id"),
    }
