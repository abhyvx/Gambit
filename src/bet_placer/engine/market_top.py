"""Market top bets for live/upcoming — popular across sports, singles + combos."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from bet_placer.data.providers import UnifiedOddsProvider
from bet_placer.config import data_path

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_TTL = 60
_SKIP_KEY = "skipodds-demo-2026"

# Stake market name fragments → our market keys (core only — no player props)
_CORE_MARKET_MAP = (
    ("both teams to score", "btts"),
    ("btts", "btts"),
    ("asian total", "over_under_goals"),
    ("total", "over_under_goals"),
    ("asian handicap", "asian_handicap"),
    ("handicap", "asian_handicap"),
    ("1x2 & total", "combo_1x2_total"),
    ("1x2", "match_winner"),
    ("match winner", "match_winner"),
    ("moneyline", "match_winner"),
    ("to win", "match_winner"),
)


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
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return age_h < 4
    except Exception:
        return False


def _sport_bucket(sk: str) -> str:
    sk = (sk or "").lower()
    if sk.startswith("basket"):
        return "basketball"
    if sk.startswith("cricket"):
        return "cricket"
    if sk.startswith("soccer") or not sk:
        return "soccer"
    return "other"


def _map_market(name: str) -> str | None:
    n = (name or "").lower()
    if "player" in n or "shots" in n or "passes" in n or "tackles" in n or "assists" in n:
        return None
    if "exact" in n or "correct score" in n or "penalty" in n:
        return None
    for frag, key in _CORE_MARKET_MAP:
        if frag in n:
            return key
    return None


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


_STAKE_MAX_AGE_H = 24  # reject cache for live betting older than this


def _stake_cache_payload(*, allow_stale: bool = False) -> tuple[dict, float | None]:
    """Load Stake disk cache. Returns (data, age_hours). age None if unknown."""
    from pathlib import Path
    import json
    path = data_path("stake_overlay_cache.json")
    if not path.exists():
        return {}, None
    data = json.loads(path.read_text())
    age_h = None
    updated = data.get("updated_at")
    if updated:
        try:
            raw = str(updated).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except Exception:
            age_h = None
    if not allow_stale and age_h is not None and age_h > _STAKE_MAX_AGE_H:
        logger.info("Stake cache stale (%.0fh old), skipping", age_h)
        return {}, age_h
    return data if isinstance(data, dict) else {}, age_h


def _stake_fixtures() -> list[dict]:
    try:
        data, _age = _stake_cache_payload(allow_stale=False)
        fixtures = data.get("fixtures") or {}
        items = fixtures.values() if isinstance(fixtures, dict) else fixtures
        out = []
        for fx in items:
            if not isinstance(fx, dict):
                continue
            st = str(fx.get("status") or "").lower()
            if st in ("closed", "resolved", "settled", "final", "completed"):
                continue
            out.append(fx)
        return out
    except Exception as exc:
        logger.debug("Stake overlay unavailable: %s", exc)
        return []


def _stake_volume_rows(*, allow_stale: bool = True) -> list[dict]:
    """Stake handle/bettors rows for Model desk. allow_stale=True so UI isn't zeroed."""
    try:
        data, age_h = _stake_cache_payload(allow_stale=allow_stale)
        if not data:
            return []
        rows: list[dict] = []
        fixtures = data.get("fixtures") or {}
        items = fixtures.values() if isinstance(fixtures, dict) else fixtures
        for fx in items or []:
            if not isinstance(fx, dict):
                continue
            vol = float(fx.get("total_bet_value") or 0)
            users = int(fx.get("total_user_count") or 0)
            bets = int(fx.get("total_bet_count") or 0)
            if vol <= 0 and users <= 0:
                continue
            rows.append({
                "home": fx.get("home_team"),
                "away": fx.get("away_team"),
                "league": fx.get("league") or fx.get("sport"),
                "sport": fx.get("sport"),
                "volume": vol,
                "users": users,
                "bets": bets,
                "status": fx.get("status"),
                "kickoff": fx.get("kickoff"),
                "age_h": age_h,
                "stale": bool(age_h is not None and age_h > _STAKE_MAX_AGE_H),
            })
        # Overlays may carry stats even if fixtures list is empty/partial
        for key, ov in (data.get("overlays") or {}).items():
            if not isinstance(ov, dict):
                continue
            stats = ov.get("stats") or {}
            vol = float(stats.get("total_bet_value_usd") or 0)
            users = int(stats.get("total_bettors") or 0)
            bets = int(stats.get("total_bets") or 0)
            if vol <= 0 and users <= 0:
                continue
            home = ov.get("home") or (str(key).split("|")[0] if "|" in str(key) else None)
            away = ov.get("away") or (str(key).split("|")[1] if "|" in str(key) else None)
            # De-dupe against fixtures already listed
            if any(_norm(r.get("home") or "") == _norm(home or "") and _norm(r.get("away") or "") == _norm(away or "") for r in rows):
                continue
            ov_sport = ov.get("sport") or stats.get("sport") or stats.get("tournament") or ""
            rows.append({
                "home": home,
                "away": away,
                "league": stats.get("tournament") or "Stake",
                "sport": ov_sport or "Soccer",
                "volume": vol,
                "users": users,
                "bets": bets,
                "status": "cached",
                "kickoff": None,
                "age_h": age_h,
                "stale": bool(age_h is not None and age_h > _STAKE_MAX_AGE_H),
                "markets": len(ov.get("available_markets") or []),
                "combos": len(ov.get("stake_combos") or []),
            })
        return rows
    except Exception as exc:
        logger.debug("Stake volume rows unavailable: %s", exc)
        return []


def _hot_doubles(singles: list[dict], n: int = 2) -> list[dict]:
    """Pack popular cross-match doubles so Top bets aren't singles-only."""
    pool = [b for b in singles if b.get("ticket_kind") == "single" and float(b.get("decimal_odds") or 0) >= 1.4]
    pool = sorted(pool, key=lambda x: -float(x.get("score") or 0))
    out: list[dict] = []
    used: set[str] = set()

    def _leg_payload(src: dict) -> dict:
        """Full slip-ready leg so Add expands into a real multi, not one fused single."""
        return {
            "event_id": src.get("event_id"),
            "sport_key": src.get("sport_key"),
            "league": src.get("league"),
            "home_team": src.get("home_team"),
            "away_team": src.get("away_team"),
            "home_logo": src.get("home_logo"),
            "away_logo": src.get("away_logo"),
            "kickoff": src.get("kickoff"),
            "status": src.get("status"),
            "market": src.get("market") or "match_winner",
            "market_name": src.get("market_name") or "Match Result",
            "selection": src.get("selection"),
            "label": src.get("label"),
            "line": src.get("line"),
            "decimal_odds": src.get("decimal_odds"),
            "odds": src.get("decimal_odds"),
            "ticket_kind": "single",
        }

    for i, a in enumerate(pool):
        if len(out) >= n:
            break
        for b in pool[i + 1 :]:
            if a.get("event_id") == b.get("event_id"):
                continue
            if _sport_bucket(a.get("sport_key") or "") == _sport_bucket(b.get("sport_key") or ""):
                continue
            key = "|".join(sorted([str(a.get("event_id")), str(b.get("event_id"))]))
            if key in used:
                continue
            used.add(key)
            price = float(a["decimal_odds"]) * float(b["decimal_odds"])
            if not (2.2 <= price <= 25):
                continue
            score = float(a.get("score") or 0) + float(b.get("score") or 0) + 40
            out.append({
                **{k: a.get(k) for k in (
                    "event_id", "sport_key", "league", "home_team", "away_team",
                    "home_logo", "away_logo", "kickoff", "status",
                )},
                "selection": f"{a.get('label')} + {b.get('label')}",
                "market": "hot_double",
                "market_name": "Hot double",
                "label": f"{a.get('label')} + {b.get('label')}",
                "market_prob": None,
                "decimal_odds": round(price, 2),
                "books": max(int(a.get("books") or 0), int(b.get("books") or 0)),
                "bettors": (a.get("bettors") or 0) + (b.get("bettors") or 0) or None,
                "handle_usd": ((a.get("handle_usd") or 0) + (b.get("handle_usd") or 0)) or None,
                "source": "hot_double",
                "score": round(score, 2),
                "credible": True,
                "ticket_kind": "combo",
                "legs": [_leg_payload(a), _leg_payload(b)],
            })
            break
    return out


def _price_band_boost(price: float) -> float:
    if 1.75 <= price <= 4.2:
        return 40
    if 1.50 <= price < 1.75:
        return 10
    if price < 1.40:
        return -35
    if price > 8:
        return -20
    return 0


def _bet_row(
    *,
    event,
    selection: str,
    market: str,
    label: str,
    price: float,
    market_prob: float | None,
    score: float,
    source: str,
    books: int = 0,
    bettors: int | None = None,
    handle_usd: float | None = None,
    market_name: str | None = None,
    ticket_kind: str = "single",
    legs: list[dict] | None = None,
) -> dict:
    return {
        "event_id": event.id,
        "sport_key": event.sport_key,
        "league": event.league,
        "home_team": event.home_team,
        "away_team": event.away_team,
        "home_logo": event.home_logo,
        "away_logo": event.away_logo,
        "kickoff": event.kickoff,
        "status": event.status,
        "selection": selection,
        "market": market,
        "market_name": market_name or market.replace("_", " ").title(),
        "label": label,
        "market_prob": round(market_prob, 4) if market_prob is not None else None,
        "decimal_odds": round(float(price), 2),
        "books": books,
        "bettors": bettors,
        "handle_usd": round(float(handle_usd), 0) if handle_usd else None,
        "source": source,
        "score": round(score, 2),
        "credible": True,
        "ticket_kind": ticket_kind,
        "legs": legs,
    }


def _stake_market_bets(event, fx: dict, base_score: float) -> list[dict]:
    """Pull popular core markets + 1x2&total combo slips from Stake overlay."""
    out: list[dict] = []
    users = int(fx.get("total_user_count") or 0)
    vol = float(fx.get("total_bet_value") or 0)
    home, away = event.home_team, event.away_team
    for m in fx.get("markets") or []:
        mname = str(m.get("name") or "")
        mkey = _map_market(mname)
        if not mkey:
            continue
        outcomes = [o for o in (m.get("outcomes") or []) if o.get("active") is not False and float(o.get("odds") or 0) > 1.05]
        if not outcomes:
            continue
        if mkey == "combo_1x2_total":
            # Hot combo slips — expand into SGM legs on Add (not one fused single)
            for o in sorted(outcomes, key=lambda x: float(x.get("odds") or 99))[:2]:
                price = float(o.get("odds") or 0)
                if not (1.6 <= price <= 12):
                    continue
                label = str(o.get("name") or "Combo")
                parts = [p.strip() for p in label.replace("+", "&").split("&") if p.strip()]
                if len(parts) < 2:
                    parts = [label]
                # Geometric share so each SGM leg has a usable decimal
                per_odds = (
                    round(price ** (1 / len(parts)), 3) if len(parts) > 1 and price > 1 else price
                )
                score = base_score + 55 + _price_band_boost(price)
                out.append(_bet_row(
                    event=event,
                    selection=label,
                    market="stake_combo",
                    label=label,
                    price=price,
                    market_prob=None,
                    score=score,
                    source="stake_combo",
                    bettors=users or None,
                    handle_usd=vol or None,
                    market_name=mname.split("(")[0].strip() or "Combo",
                    ticket_kind="combo",
                    legs=[
                        {
                            "event_id": getattr(event, "id", None),
                            "sport_key": getattr(event, "sport_key", None),
                            "league": getattr(event, "league", None),
                            "home_team": home,
                            "away_team": away,
                            "home_logo": getattr(event, "home_logo", None),
                            "away_logo": getattr(event, "away_logo", None),
                            "market": "stake_combo_leg",
                            "market_name": "Combo leg",
                            "selection": part,
                            "label": part,
                            "decimal_odds": per_odds,
                            "odds": per_odds,
                            "ticket_kind": "single",
                        }
                        for part in parts
                    ],
                ))
            continue

        # Single core market — pick the shortest priced active outcome in the value band
        ranked = sorted(outcomes, key=lambda x: float(x.get("odds") or 99))
        pick = None
        for o in ranked:
            price = float(o.get("odds") or 0)
            if 1.35 <= price <= 5.5:
                pick = o
                break
        if not pick:
            pick = ranked[0]
        price = float(pick.get("odds") or 0)
        if price <= 1.05:
            continue
        oname = str(pick.get("name") or "")
        label = oname
        if mkey == "match_winner":
            if _norm(oname) == _norm(home):
                label = f"{home} to win"
            elif _norm(oname) == _norm(away):
                label = f"{away} to win"
            elif "draw" in oname.lower():
                label = "Draw"
        elif mkey == "btts":
            label = f"BTTS — {oname}"
        elif mkey == "over_under_goals":
            label = oname if "over" in oname.lower() or "under" in oname.lower() else f"Total {oname}"
        score = base_score + 25 + _price_band_boost(price)
        if mkey != "match_winner":
            score += 18  # diversify away from pure ML
        out.append(_bet_row(
            event=event,
            selection=oname,
            market=mkey,
            label=label,
            price=price,
            market_prob=None,
            score=score,
            source="stake_market",
            bettors=users or None,
            handle_usd=vol or None,
            market_name=mname.split("(")[0].strip() or mkey,
            ticket_kind="single",
        ))
    return out


def market_top_bets(limit: int = 8) -> dict:
    """Top bets on open matches — all sports, popularity-first, singles + combos."""
    now = time.time()
    if _CACHE["payload"] and now - _CACHE["ts"] < _TTL:
        return _CACHE["payload"]

    provider = UnifiedOddsProvider()
    # Always pull all three desks — never soccer-only.
    # Summaries only: building Match+Elo for soccer_all/bb/cricket_all wedged top bets.
    events = []
    for key in ("soccer_all", "basketball_all", "cricket_all"):
        try:
            events.extend(list(provider.fetch_events(key, with_matches=False).events))
        except Exception:
            continue
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
        st = str(f.get("status") or "").lower()
        if st in ("completed", "final", "closed", "settled"):
            continue
        key = (_norm(f.get("home_team", "")), _norm(f.get("away_team", "")))
        skip_by_pair[key] = so

    bets: list[dict] = []

    for fx in _stake_fixtures():
        key = (_norm(fx.get("home_team") or ""), _norm(fx.get("away_team") or ""))
        e = by_pair.get(key)
        if not e:
            continue  # No ESPN join — don't surface Stake-only (stale risk)
        vol = float(fx.get("total_bet_value") or 0)
        users = int(fx.get("total_user_count") or 0)
        bets_n = int(fx.get("total_bet_count") or 0)
        # Handle dominates ranking — real popular desks beat "next kickoff"
        base = vol / 500.0 + users * 0.08 + bets_n * 0.003
        if getattr(e, "status", None) == "live":
            base += 50
        # Popular ML from volume + SkipOdds/devig
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
            probs = _devig(getattr(e, "home_odds", None), getattr(e, "draw_odds", None), getattr(e, "away_odds", None))
            if probs:
                ph, pd, pa = probs
                side, label, p, price = "home", f"{e.home_team} to win", ph, e.home_odds
                if pd >= p and pd >= pa:
                    side, label, p, price = "draw", "Draw", pd, e.draw_odds
                if pa >= p and pa >= pd:
                    side, label, p, price = "away", f"{e.away_team} to win", pa, e.away_odds
        if price:
            score = base + _price_band_boost(float(price))
            bets.append(_bet_row(
                event=e,
                selection=side,
                market="match_winner",
                label=label if side != "draw" else "Draw",
                price=float(price),
                market_prob=p,
                score=score,
                source="stake_handle",
                books=int((so or {}).get("books_surveyed") or getattr(e, "bookmaker_count", 0) or 0),
                bettors=users or None,
                handle_usd=vol or None,
                market_name="Match Result",
            ))
        bets.extend(_stake_market_bets(e, fx, base))

    seen_ml = {(_norm(b["home_team"]), _norm(b["away_team"]), b.get("market"), b.get("selection")) for b in bets}
    for key, e in by_pair.items():
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
        sig = (_norm(e.home_team), _norm(e.away_team), "match_winner", side)
        if sig in seen_ml:
            continue
        score = max(books, 1) * 12.0 + (50 if e.status == "live" else 0) + (25 if so else 0)
        score += _price_band_boost(float(price))
        sk = _sport_bucket(e.sport_key or "")
        if sk in ("basketball", "cricket"):
            score += 12
        bets.append(_bet_row(
            event=e,
            selection=side,
            market="match_winner",
            label=label if side != "draw" else "Draw",
            price=float(price),
            market_prob=p,
            score=score,
            source=source,
            books=books,
            market_name="Match Result",
        ))

    bets = [
        b for b in bets
        if b.get("decimal_odds") and _kickoff_open(b.get("kickoff"), b.get("status"))
    ]
    # Ensure hot slips aren't singles-only when Stake combos are sparse
    bets.extend(_hot_doubles(bets, n=max(2, limit // 4)))

    # Diversify: sport buckets × ticket kind
    by_sport: dict[str, list] = {"soccer": [], "basketball": [], "cricket": [], "other": []}
    for b in sorted(bets, key=lambda x: -float(x.get("score") or 0)):
        by_sport[_sport_bucket(b.get("sport_key") or "")].append(b)

    ordered: list[dict] = []
    seen_keys: set[str] = set()

    def _take(rows: list[dict], n: int, *, combos_first: bool = False) -> None:
        rows = list(rows)
        if combos_first:
            rows.sort(key=lambda x: (0 if x.get("ticket_kind") == "combo" else 1, -float(x.get("score") or 0)))
        for b in rows:
            if len([x for x in ordered if _sport_bucket(x.get("sport_key") or "") == _sport_bucket(b.get("sport_key") or "")]) >= n:
                return
            key = f"{b.get('event_id')}|{b.get('market')}|{b.get('selection')}|{b.get('ticket_kind')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            ordered.append(b)

    # Reserve combo slots so slips aren't buried by ML volume
    combos = [b for b in bets if b.get("ticket_kind") == "combo"]
    _take(sorted(combos, key=lambda x: -float(x.get("score") or 0)), max(2, limit // 3), combos_first=True)

    per = max(2, (limit + 2) // 3)
    for sport in ("soccer", "basketball", "cricket"):
        _take(by_sport[sport], per, combos_first=True)
    # Fill remaining with global best (still de-duped)
    for b in sorted(bets, key=lambda x: -float(x.get("score") or 0)):
        if len(ordered) >= limit:
            break
        key = f"{b.get('event_id')}|{b.get('market')}|{b.get('selection')}|{b.get('ticket_kind')}"
        if key in seen_keys:
            continue
        # Avoid stacking 4 ML favorites from same sport at the bottom
        sport_n = sum(1 for x in ordered if _sport_bucket(x.get("sport_key") or "") == _sport_bucket(b.get("sport_key") or ""))
        if sport_n >= max(3, limit // 2) and b.get("ticket_kind") == "single" and b.get("market") == "match_winner":
            continue
        seen_keys.add(key)
        ordered.append(b)

    # Surebets from Odds API disk cache ONLY
    surebets: list[dict] = []
    try:
        from bet_placer.engine.surebets import scan_event_surebet
        from bet_placer.data.odds_api import OddsAPIClient
        client = OddsAPIClient()
        if client.is_configured:
            for key in ("soccer_epl", "basketball_nba", "cricket_international_t20"):
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

    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": ["stake_handle", "stake_combo", "skipodds", "espn", "surebets_cached"],
        "rank_by": "popularity_handle_and_sport_mix",
        "open_only": True,
        "bets": ordered[:limit],
        "surebets": surebets[:8],
        "count": len(ordered[:limit]),
        "scanned": len(by_pair),
    }
    _CACHE.update({"ts": now, "payload": payload})
    return payload
