from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from bet_placer.config import get_settings
from bet_placer.data.stake_browser import browser_status, warmup_visible
from bet_placer.data.stake_scraper import StakeScraper

_LOCK = Lock()
_CONSENT_VERSION = "2026-07-02"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path() -> Path:
    settings = get_settings()
    if settings.portfolio_store_path:
        return Path(settings.portfolio_store_path).expanduser()
    return Path.home() / ".bet_placer" / "portfolio_state.json"


def _default_state() -> dict[str, Any]:
    return {
        "privacy": {
            "portfolio_enabled": False,
            "visibility": "private",
            "risk_acknowledged": False,
            "learning_opt_in": False,
            "consent_version": _CONSENT_VERSION,
            "consent_accepted_at": None,
        },
        "connection": {
            "mode": "browser_session",
            "status": "disconnected",
            "connected": False,
            "last_connected_at": None,
            "last_sync_at": None,
            "last_sync_status": "never",
            "last_sync_message": "Portfolio sync is off until you enable it.",
        },
        "portfolio": {
            "bet_count": 0,
            "settled_count": 0,
            "open_count": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "total_staked": 0.0,
            "total_return": 0.0,
            "roi_pct": 0.0,
            "last_imported_at": None,
            "bets": [],
        },
    }


def _load_state() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()
    state = _default_state()
    for key in ("privacy", "connection", "portfolio"):
        if isinstance(data.get(key), dict):
            state[key].update(data[key])
    return state


def _save_state(state: dict[str, Any]) -> dict[str, Any]:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state


def _merged_status(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state)
    browser = browser_status()
    out["connection"]["browser"] = browser
    if browser.get("ready"):
        out["connection"]["status"] = "connected"
        out["connection"]["connected"] = True
    elif browser.get("warming"):
        out["connection"]["status"] = "connecting"
        out["connection"]["connected"] = False
    return out


def _summarize_bets(bets: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [b for b in bets if b.get("status") not in {"open", "pending", "unknown"}]
    wins = sum(1 for b in bets if b.get("status") == "won")
    losses = sum(1 for b in bets if b.get("status") == "lost")
    pushes = sum(1 for b in bets if b.get("status") in {"void", "cancelled", "canceled"})
    total_staked = round(sum(float(b.get("stake_usd") or 0) for b in bets), 2)
    total_return = round(sum(float(b.get("payout_usd") or 0) for b in settled), 2)
    profit = round(total_return - total_staked, 2)
    roi_pct = round((profit / total_staked) * 100, 2) if total_staked else 0.0
    singles = sum(1 for b in bets if (b.get("selection_count") or 0) <= 1)
    parlays = sum(1 for b in bets if (b.get("selection_count") or 0) > 1)
    avg_odds_values = [float(b.get("combined_odds") or 0) for b in bets if float(b.get("combined_odds") or 0) > 1]
    avg_odds = round(sum(avg_odds_values) / len(avg_odds_values), 2) if avg_odds_values else None
    market_breakdown: dict[str, dict[str, Any]] = {}
    for bet in bets:
        family = str(bet.get("market_family") or "other")
        bucket = market_breakdown.setdefault(family, {"count": 0, "profit_usd": 0.0, "wins": 0, "losses": 0})
        bucket["count"] += 1
        bucket["profit_usd"] = round(bucket["profit_usd"] + float(bet.get("profit_usd") or 0), 2)
        if bet.get("status") == "won":
            bucket["wins"] += 1
        elif bet.get("status") == "lost":
            bucket["losses"] += 1

    cumulative = []
    running = 0.0
    for idx, bet in enumerate(sorted(bets, key=lambda b: b.get("created_at") or "")):
        running = round(running + float(bet.get("profit_usd") or 0), 2)
        cumulative.append(
            {
                "i": idx + 1,
                "label": bet.get("fixture_name") or f"Bet {idx + 1}",
                "profit_usd": round(float(bet.get("profit_usd") or 0), 2),
                "running_profit_usd": running,
                "status": bet.get("status"),
            }
        )

    ranked_markets = sorted(
        (
            {
                "market": family,
                **stats,
                "roi_pct": round((stats["profit_usd"] / sum(float(b.get("stake_usd") or 0) for b in bets if b.get("market_family") == family)) * 100, 2)
                if any(b.get("market_family") == family and float(b.get("stake_usd") or 0) > 0 for b in bets)
                else 0.0,
            }
            for family, stats in market_breakdown.items()
        ),
        key=lambda item: item["profit_usd"],
        reverse=True,
    )
    top_market = ranked_markets[0] if ranked_markets else None
    leak_market = ranked_markets[-1] if len(ranked_markets) > 1 else None
    recent = bets[:10]
    recent_profit = round(sum(float(b.get("profit_usd") or 0) for b in recent), 2)
    recent_hit_rate = round(
        (sum(1 for b in recent if b.get("status") == "won") / max(1, sum(1 for b in recent if b.get("status") in {"won", "lost"}))) * 100,
        1,
    ) if recent else None

    recommended_focus = [m["market"] for m in ranked_markets[:2] if m["profit_usd"] > 0]
    caution_markets = [m["market"] for m in ranked_markets[-2:] if m["profit_usd"] < 0]
    avoid_parlays = parlays >= singles and (sum(float(b.get("profit_usd") or 0) for b in bets if b.get("bet_type") == "parlay") < 0)
    max_odds = 2.2 if longshot_losses >= 3 else 3.0

    insights: list[str] = []
    if parlays >= max(3, singles):
        insights.append("You are leaning heavily into parlays. That usually adds variance faster than it adds edge.")
    longshot_losses = sum(1 for b in bets if float(b.get("combined_odds") or 0) >= 3 and b.get("status") == "lost")
    if longshot_losses >= 3:
        insights.append("A lot of the damage is coming from long-odds bets. Trim stake size on 3.0+ prices unless the edge is clear.")
    if losses > wins and total_staked >= 100:
        insights.append("Your recent sample is losing overall. Focus on fewer bets and tighter price discipline before scaling volume.")
    if sum(1 for b in bets if b.get("status") == "open") >= 5:
        insights.append("You have a large number of open bets. Watch for correlated exposure across the same teams or match narratives.")

    profile = {
        "confidence": "high" if len(bets) >= 25 else "medium" if len(bets) >= 10 else "low",
        "focus_markets": recommended_focus,
        "caution_markets": caution_markets,
        "avoid_parlays": avoid_parlays,
        "max_preferred_odds": max_odds,
        "top_market": top_market,
        "leak_market": leak_market,
        "recent_profit_usd": recent_profit,
        "recent_hit_rate_pct": recent_hit_rate,
        "summary": (
            f"Lean into {', '.join(recommended_focus) if recommended_focus else 'disciplined singles'}; "
            f"be careful with {', '.join(caution_markets) if caution_markets else 'overextended longshots'}."
        ),
    }

    return {
        "bet_count": len(bets),
        "settled_count": len(settled),
        "open_count": sum(1 for b in bets if b.get("status") == "open"),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "total_staked": total_staked,
        "total_return": total_return,
        "profit_usd": profit,
        "roi_pct": roi_pct,
        "singles_count": singles,
        "parlays_count": parlays,
        "avg_odds": avg_odds,
        "market_breakdown": market_breakdown,
        "ranked_markets": ranked_markets,
        "cumulative_profit": cumulative,
        "insights": insights,
        "profile": profile,
        "model_audit": {
            "available": False,
            "message": (
                "Historical model-vs-bet grading needs saved prediction snapshots from the moment each bet was placed. "
                "The import layer is now ready; the next layer is journaling model picks alongside future bets."
            ),
        },
        "bets": bets,
        "last_imported_at": _utc_now(),
    }


def get_portfolio_state() -> dict[str, Any]:
    with _LOCK:
        return _merged_status(_load_state())


def get_portfolio_profile() -> dict[str, Any] | None:
    with _LOCK:
        state = _load_state()
        portfolio = state.get("portfolio") or {}
        profile = portfolio.get("profile")
        if not profile:
            return None
        return deepcopy(profile)


def update_privacy_settings(*, portfolio_enabled: bool, risk_acknowledged: bool, learning_opt_in: bool) -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        state["privacy"].update(
            {
                "portfolio_enabled": bool(portfolio_enabled),
                "risk_acknowledged": bool(risk_acknowledged),
                "learning_opt_in": bool(learning_opt_in),
                "consent_version": _CONSENT_VERSION,
                "consent_accepted_at": _utc_now() if risk_acknowledged else state["privacy"].get("consent_accepted_at"),
            }
        )
        if not portfolio_enabled:
            state["connection"]["last_sync_message"] = "Portfolio sync is disabled. Existing imported data stays private until you delete it."
        return _merged_status(_save_state(state))


def connect_browser_session(timeout: int = 180) -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        ok = warmup_visible(timeout=timeout)
        browser = browser_status()
        if ok or browser.get("ready"):
            state["connection"].update(
                {
                    "status": "connected",
                    "connected": True,
                    "last_connected_at": _utc_now(),
                    "last_sync_message": "Visible Stake browser session is ready. Sign into Stake in that window if needed, then return here and refresh.",
                }
            )
        else:
            state["connection"].update(
                {
                    "status": "connecting",
                    "connected": False,
                    "last_sync_message": (
                        "Stake login window opened, but the session is not ready yet. "
                        "Complete Cloudflare/login in the browser window, then retry."
                    ),
                }
            )
        return _merged_status(_save_state(state))


def disconnect_browser_session() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        state["connection"].update(
            {
                "status": "disconnected",
                "connected": False,
                "last_sync_message": "Disconnected from Stake. Imported portfolio data remains saved privately until you delete it.",
            }
        )
        return _merged_status(_save_state(state))


def refresh_portfolio_snapshot() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        if not state["privacy"].get("portfolio_enabled"):
            raise ValueError("Enable private portfolio sync before refreshing.")
        if not state["privacy"].get("risk_acknowledged"):
            raise ValueError("Accept the privacy warning before refreshing.")

        browser = browser_status()
        if not browser.get("ready"):
            state["connection"].update(
                {
                    "status": "disconnected",
                    "connected": False,
                    "last_sync_at": _utc_now(),
                    "last_sync_status": "needs_reconnect",
                    "last_sync_message": "Stake session is not active. Reconnect the browser session, then refresh again.",
                }
            )
            return _merged_status(_save_state(state))

        try:
            scraper = StakeScraper(use_browser=True, allow_browser_launch=False, timeout=45)
            bets = []
            page_size = 50
            for offset in range(0, 150, page_size):
                batch = scraper.fetch_user_bet_history(limit=page_size, offset=offset)
                if not batch:
                    break
                bets.extend(batch)
                if len(batch) < page_size:
                    break
        except Exception as exc:
            msg = str(exc)
            state["connection"].update(
                {
                    "status": "connected",
                    "connected": True,
                    "last_sync_at": _utc_now(),
                    "last_sync_status": "auth_required",
                    "last_sync_message": (
                        "Stake browser is open, but your account history could not be read yet. "
                        "Make sure you are fully logged into Stake in that browser window, then refresh again. "
                        f"Detail: {msg[:180]}"
                    ),
                }
            )
            return _merged_status(_save_state(state))

        state["portfolio"] = _summarize_bets(bets)
        state["connection"].update(
            {
                "status": "connected",
                "connected": True,
                "last_sync_at": _utc_now(),
                "last_sync_status": "imported",
                "last_sync_message": f"Imported {len(bets)} bets from your Stake account history.",
            }
        )
        return _merged_status(_save_state(state))
