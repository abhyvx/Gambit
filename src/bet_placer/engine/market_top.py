"""Market top bets for live/upcoming only — ranked by handle / books, not win%."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from bet_placer.data.providers import UnifiedOddsProvider

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_TTL = 60
_SKIP_KEY = "skipodds-demo-2026"


def _devig(h: float | None, d: float | None, a: float | None) -> tuple[float, float, float] | None:
    prices = []
    if h and h > 1:
        prices.append(("home", 1.0 / h))
    if d and d > 1:
        prices.append(("draw", 1.0 / d))
    if a and a > 1:
        prices.append(("away", 1.0 / a))
    if len(prices) < 2:
        return None
    s = sum(p for _, p in prices)
    if s <= 0:
        return None
    m = {k: v / s for k, v in prices}
    return m.get("home", 0.0), m.get("draw", 0.0), m.get("away", 0.0)


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _kickoff_open(kickoff: str | None, status: str | None) -> bool:
    if status in ("live", "upcoming"):
        return True
    if status in ("completed", "final", "closed", "settled"):
        return False
    if not kickoff:
        return False
    try:
        raw = str(kickoff).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # allow a short live grace; drop if kickoff was > 4h ago with no live flag
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return age_h < 4
    except Exception:
        return False


def _fetch_skipodds(limit: int = 80) -> list[dict]:
    try:
        r = requests.get(
            "https://skipodds.com/v1/fixtures",
            params={"api_key": _SKIP_KEY, "limit": limit},
            timeout=12,
            headers={"User-Agent": "Gambit/1.0"},
        )
        r.raise_for_status()
        return list((r.json() or {}).get("fixtures") or [])
    except Exception as exc:
        logger.debug("SkipOdds unavailable: %s", exc)
        return []


def _stake_volume_rows() -> list[dict]:
    try:
        from pathlib import Path
        import json
        path = Path.home() / ".bet_placer" / "stake_overlay_cache.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        fixtures = data.get("fixtures") or {}
        rows = []
        items = fixtures.values() if isinstance(fixtures, dict) else fixtures
        for fx in items:
            if not isinstance(fx, dict):
                continue
            st = str(fx.get("status") or "").lower()
            if st in ("closed", "resolved", "settled", "final", "completed"):
                continue
            vol = float(fx.get("total_bet_value") or 0)
            users = int(fx.get("total_user_count") or 0)
            bets = int(fx.get("total_bet_count") or 0)
            if vol <= 0 and users <= 0:
                continue
            rows.append({
                "home": fx.get("home_team") or "",
                "away": fx.get("away_team") or "",
                "league": fx.get("league") or "",
                "volume": vol,
                "users": users,
                "bets": bets,
                "id": fx.get("id"),
                "kickoff": fx.get("kickoff"),
                "status": st,
            })
        return rows
    except Exception as exc:
        logger.debug("Stake volume unavailable: %s", exc)
        return []


def market_top_bets(limit: int = 8) -> dict:
    """Top bets on open matches only (live / upcoming)."""
    now = time.time()
    if _CACHE["payload"] and now - _CACHE["ts"] < _TTL:
        return _CACHE["payload"]

    provider = UnifiedOddsProvider()
    # Soccer first (cached after home load). Only pull hoop/cricket if the board is thin.
    soccer = provider.fetch_events("soccer_all")
    events = list(soccer.events)
    open_n = sum(1 for e in events if e.status in ("live", "upcoming"))
    if open_n < 12:
        hoop = provider.fetch_events("basketball_all")
        cricket = provider.fetch_events("cricket_all")
        events = events + list(hoop.events) + list(cricket.events)
    by_pair = {
        (_norm(e.home_team), _norm(e.away_team)): e
        for e in events
        if e.status in ("live", "upcoming")
    }

    skip = _fetch_skipodds(80)
    skip_by_pair = {}
    for f in skip:
        so = f.get("skipodds") or {}
        if not so:
            continue
        # SkipOdds status when present
        st = str(f.get("status") or "").lower()
        if st in ("completed", "final", "closed", "settled"):
            continue
        key = (_norm(f.get("home_team", "")), _norm(f.get("away_team", "")))
        skip_by_pair[key] = so

    bets: list[dict] = []

    # Stake handle only when the match is still on our open board
    for s in _stake_volume_rows():
        key = (_norm(s["home"]), _norm(s["away"]))
        e = by_pair.get(key)
        if not e:
            continue  # finished / not scraped → never surface as "top"
        so = skip_by_pair.get(key)
        price = None
        side, label, p = "home", f"{e.home_team} to win", None
        if so:
            ph, pd, pa = float(so.get("home") or 0), float(so.get("draw") or 0), float(so.get("away") or 0)
            fair = so.get("fair_odds") or {}
            side, label, p, price = "home", f"{e.home_team} to win", ph, fair.get("home")
            if pd >= (p or 0) and pd >= pa:
                side, label, p, price = "draw", "Draw", pd, fair.get("draw")
            if pa >= (p or 0) and pa >= (pd or 0):
                side, label, p, price = "away", f"{e.away_team} to win", pa, fair.get("away")
        else:
            probs = _devig(e.home_odds, e.draw_odds, e.away_odds)
            if probs:
                ph, pd, pa = probs
                side, label, p, price = "home", f"{e.home_team} to win", ph, e.home_odds
                if pd >= p and pd >= pa:
                    side, label, p, price = "draw", "Draw", pd, e.draw_odds
                if pa >= p and pa >= pd:
                    side, label, p, price = "away", f"{e.away_team} to win", pa, e.away_odds
        if not price:
            continue
        score = float(s["volume"]) / 1000.0 + float(s["users"]) * 0.05 + float(s["bets"]) * 0.002
        if e.status == "live":
            score += 50
        bets.append({
            "event_id": e.id,
            "sport_key": e.sport_key,
            "league": e.league,
            "home_team": e.home_team,
            "away_team": e.away_team,
            "home_logo": e.home_logo,
            "away_logo": e.away_logo,
            "kickoff": e.kickoff,
            "status": e.status,
            "selection": side,
            "market": "match_winner",
            "label": label if side != "draw" else "Draw",
            "market_prob": round(p, 4) if p is not None else None,
            "decimal_odds": round(float(price), 2),
            "books": int((so or {}).get("books_surveyed") or e.bookmaker_count or 0),
            "bettors": int(s["users"]),
            "handle_usd": round(float(s["volume"]), 0),
            "source": "stake_handle",
            "score": round(score, 2),
            "credible": True,
        })

    seen = {(_norm(b["home_team"]), _norm(b["away_team"])) for b in bets}
    for key, e in by_pair.items():
        if key in seen:
            continue
        so = skip_by_pair.get(key)
        books = int((so or {}).get("books_surveyed") or e.bookmaker_count or 0)
        if not so and not (e.home_odds and e.away_odds):
            continue
        if so:
            ph, pd, pa = float(so.get("home") or 0), float(so.get("draw") or 0), float(so.get("away") or 0)
            fair = so.get("fair_odds") or {}
            side, label, p, price = "home", f"{e.home_team} to win", ph, fair.get("home")
            if pd >= p and pd >= pa:
                side, label, p, price = "draw", "Draw", pd, fair.get("draw")
            if pa >= p and pa >= pd:
                side, label, p, price = "away", f"{e.away_team} to win", pa, fair.get("away")
            source = "skipodds"
        else:
            probs = _devig(e.home_odds, e.draw_odds, e.away_odds)
            if not probs:
                continue
            ph, pd, pa = probs
            side, label, p, price = "home", f"{e.home_team} to win", ph, e.home_odds
            if pd >= p and pd >= pa:
                side, label, p, price = "draw", "Draw", pd, e.draw_odds
            if pa >= p and pa >= pd:
                side, label, p, price = "away", f"{e.away_team} to win", pa, e.away_odds
            source = "espn_books"
        if not price:
            continue
        score = max(books, 1) * 12.0 + (50 if e.status == "live" else 0) + (25 if so else 0)
        if 1.4 <= float(price) <= 5.0:
            score += 8
        bets.append({
            "event_id": e.id,
            "sport_key": e.sport_key,
            "league": e.league,
            "home_team": e.home_team,
            "away_team": e.away_team,
            "home_logo": e.home_logo,
            "away_logo": e.away_logo,
            "kickoff": e.kickoff,
            "status": e.status,
            "selection": side,
            "market": "match_winner",
            "label": label if side != "draw" else "Draw",
            "market_prob": round(p, 4) if p is not None else None,
            "decimal_odds": round(float(price), 2),
            "books": books,
            "bettors": None,
            "handle_usd": None,
            "source": source,
            "score": round(score, 2),
            "credible": True,
        })

    # Hard filter: open matches with a real price only
    bets = [
        b for b in bets
        if b.get("decimal_odds") and _kickoff_open(b.get("kickoff"), b.get("status"))
    ]
    # Prefer missed-value band — not juice favorites (<1.40) and not lottery tickets
    for b in bets:
        price = float(b.get("decimal_odds") or 0)
        if 1.75 <= price <= 4.2:
            b["score"] = float(b.get("score") or 0) + 40
        elif 1.50 <= price < 1.75:
            b["score"] = float(b.get("score") or 0) + 10
        elif price < 1.40:
            b["score"] = float(b.get("score") or 0) - 35
        # Balance sports so home isn't soccer-only
        sk = b.get("sport_key") or ""
        if sk.startswith("basket"):
            b["score"] = float(b.get("score") or 0) + 8
        elif sk.startswith("cricket"):
            b["score"] = float(b.get("score") or 0) + 8

    # Surebets from Odds API disk cache ONLY (force=False) — never burn credits here
    surebets: list[dict] = []
    try:
        from bet_placer.engine.surebets import scan_event_surebet
        from bet_placer.data.odds_api import OddsAPIClient
        client = OddsAPIClient()
        if client.is_configured:
            for key in ("soccer_epl", "basketball_nba"):
                try:
                    for ev in client.fetch_odds(key, markets="h2h", force=False) or []:
                        hit = scan_event_surebet(ev, min_roi=0.01)
                        if hit:
                            surebets.append({**hit, "sport_key": key})
                except Exception:
                    continue
    except Exception:
        surebets = []
    surebets.sort(key=lambda s: -float(s.get("roi") or 0))

    # Diversify: take best per sport then fill
    by_sport: dict[str, list] = {"soccer": [], "basketball": [], "cricket": [], "other": []}
    for b in sorted(bets, key=lambda x: -float(x.get("score") or 0)):
        sk = b.get("sport_key") or ""
        if sk.startswith("basket"):
            by_sport["basketball"].append(b)
        elif sk.startswith("cricket"):
            by_sport["cricket"].append(b)
        elif sk.startswith("soccer") or not sk:
            by_sport["soccer"].append(b)
        else:
            by_sport["other"].append(b)
    pool: list[dict] = []
    for key in ("soccer", "basketball", "cricket", "other"):
        pool.extend(by_sport[key][: max(2, limit // 3)])
    seen_ids = set()
    ordered = []
    for b in sorted(pool, key=lambda x: -float(x.get("score") or 0)):
        eid = b.get("event_id")
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        ordered.append(b)
    for b in sorted(bets, key=lambda x: -float(x.get("score") or 0)):
        if len(ordered) >= limit:
            break
        eid = b.get("event_id")
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        ordered.append(b)

    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": ["stake_handle", "skipodds", "espn", "surebets_cached"],
        "rank_by": "value_band_and_books",
        "open_only": True,
        "bets": ordered[:limit],
        "surebets": surebets[:8],
        "count": len(ordered[:limit]),
        "scanned": len(by_pair),
    }
    _CACHE.update({"ts": now, "payload": payload})
    return payload
