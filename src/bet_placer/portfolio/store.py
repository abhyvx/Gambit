from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from bet_placer.config import data_path, get_settings
from bet_placer.data.stake_browser import browser_status, wait_until_logged_in
from bet_placer.data.stake_scraper import StakeScraper

_LOCK = Lock()
_CONSENT_VERSION = "2026-07-02"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _flatten_menu(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for category in categories or []:
        for market in category.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                flat.append({**outcome, "market_label": market.get("market_label"), "category": category.get("category")})
    return flat


def _match_model_outcome(selection: dict[str, Any], flat: list[dict[str, Any]]) -> dict[str, Any] | None:
    sel_text = _norm(selection.get("selection"))
    fixture_text = _norm(selection.get("fixture_name"))
    target_odds = float(selection.get("odds") or 0)
    best = None
    best_score = -999.0
    for outcome in flat:
        label = _norm(outcome.get("label"))
        raw_sel = _norm(outcome.get("selection"))
        market_label = _norm(outcome.get("market_label"))
        score = 0.0
        if sel_text and (sel_text == raw_sel or sel_text == label):
            score += 4
        elif sel_text and (sel_text in label or raw_sel in sel_text):
            score += 3
        if fixture_text and fixture_text.split(" ")[0] in label:
            score += 0.5
        odds = float(outcome.get("odds") or 0)
        if target_odds and odds:
            score -= min(abs(odds - target_odds), 5) * 0.2
        if any(word in market_label for word in ("goalscorer", "goalscorers")) and any(word in sel_text for word in ("over", "under", "yes", "no")):
            score -= 2
        if score > best_score:
            best_score = score
            best = outcome
    return best if best_score >= 2 else None


def _audit_bets_against_model(bets: list[dict[str, Any]]) -> dict[str, Any]:
    from bet_placer.engine.bet_builder import build_bet_menu

    by_fixture: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for bet in bets:
        home, away = bet.get("home_team"), bet.get("away_team")
        if home and away:
            by_fixture.setdefault((home, away), []).append(bet)

    audited = 0
    aligned = 0
    against = 0
    strong_edges = 0
    skip_flags = 0
    for (home, away), fixture_bets in by_fixture.items():
        try:
            menu = build_bet_menu(home, away, budget_inr=200)
        except Exception:
            continue
        flat = _flatten_menu(menu.get("categories") or [])
        if not flat:
            continue
        for bet in fixture_bets:
            bet_views = []
            for sel in bet.get("selections") or []:
                matched = _match_model_outcome(sel, flat)
                if not matched:
                    continue
                verdict = matched.get("verdict") or {}
                tone = verdict.get("tone") or "neutral"
                edge = matched.get("edge_pct")
                our_probability = matched.get("our_probability")
                bet_views.append(
                    {
                        "label": matched.get("label"),
                        "market_label": matched.get("market_label"),
                        "tone": tone,
                        "verdict_label": verdict.get("label"),
                        "edge_pct": edge,
                        "our_probability": our_probability,
                    }
                )
                audited += 1
                if tone == "good":
                    aligned += 1
                    if edge is not None and edge >= 5:
                        strong_edges += 1
                elif tone == "bad":
                    against += 1
                    skip_flags += 1
            if bet_views:
                tones = [v["tone"] for v in bet_views]
                overall = "good" if all(t == "good" for t in tones) else "bad" if any(t == "bad" for t in tones) else "neutral"
                bet["model_view"] = {
                    "overall": overall,
                    "legs": bet_views,
                }
    return {
        "available": audited > 0,
        "audited_legs": audited,
        "aligned_legs": aligned,
        "against_legs": against,
        "strong_edges": strong_edges,
        "skip_flags": skip_flags,
        "message": (
            f"Audited {audited} imported bet legs against the app's reconstructed board."
            if audited
            else "No imported bets could be matched back to the model board yet."
        ),
    }


def _store_path() -> Path:
    settings = get_settings()
    if settings.portfolio_store_path:
        return Path(settings.portfolio_store_path).expanduser()
    return data_path("portfolio_state.json")


def _default_state() -> dict[str, Any]:
    return {
        "privacy": {
            "portfolio_enabled": True,
            "visibility": "private",
            "risk_acknowledged": True,
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
            "last_sync_status": "ready",
            "last_sync_message": (
                "Journal is on. Connect Stake to import history, or confirm bets from your slip."
            ),
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


def _ensure_privacy_defaults(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Journal sync stays on unless the user turns it off after first load."""
    priv = state.setdefault("privacy", {})
    changed = False
    if not priv.get("portfolio_enabled"):
        priv["portfolio_enabled"] = True
        changed = True
    if not priv.get("risk_acknowledged"):
        priv["risk_acknowledged"] = True
        changed = True
    if priv.get("risk_acknowledged") and not priv.get("consent_accepted_at"):
        priv["consent_accepted_at"] = _utc_now()
        priv["consent_version"] = _CONSENT_VERSION
        changed = True
    if changed:
        conn = state.setdefault("connection", {})
        if conn.get("last_sync_status") in (None, "never"):
            conn["last_sync_status"] = "ready"
            conn["last_sync_message"] = (
                "Journal is on. Connect Stake to import history, or confirm bets from your slip."
            )
    return state, changed


def _migrate_legacy_bet(bet: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(bet)
    if out.get("stake_value") is not None and out.get("result"):
        return out

    currency = (out.get("currency") or "USD").upper()
    display_currency = out.get("display_currency") or currency
    stake = float(out.get("stake") or out.get("stake_value") or 0)
    payout = float(out.get("payout") or out.get("payout_value") or 0)
    raw_status = str(out.get("status") or "").lower()
    active = bool(out.get("active"))
    selections = out.get("selections") or []
    outcome_statuses = {str(s.get("status") or "").lower() for s in selections}

    if active or raw_status in {"open", "pending"}:
        result = "open"
        status = "open"
    elif raw_status == "cashout":
        result = "cashed_out"
        status = "cashout"
    elif raw_status in {"cancelled", "canceled", "void"} or "voided" in outcome_statuses:
        result = "push"
        status = "void"
    elif "won" in outcome_statuses or payout > stake:
        result = "won"
        status = "won"
    elif "lost" in outcome_statuses or payout == 0:
        result = "lost"
        status = "lost"
    elif payout == stake and stake > 0:
        result = "push"
        status = "void"
    elif payout > 0:
        result = "cashed_out"
        status = "cashout"
    else:
        result = "unknown"
        status = raw_status or "unknown"

    out["display_currency"] = display_currency
    out["stake_value"] = round(stake, 2)
    out["payout_value"] = round(payout, 2)
    out["profit_value"] = round((payout - stake) if result != "open" else 0.0, 2)
    out["result"] = result
    out["status"] = status
    return out


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
    bets = state.get("portfolio", {}).get("bets") or []
    if bets:
        migrated = [_migrate_legacy_bet(b) for b in bets]
        summary = _summarize_bets(migrated)
        summary["model_audit"] = _audit_bets_against_model(summary["bets"])
        state["portfolio"] = summary
    return state


def _save_state(state: dict[str, Any]) -> dict[str, Any]:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state


def _merged_status(state: dict[str, Any]) -> dict[str, Any]:
    """Attach live browser flags without rewriting login status from CF-ready alone."""
    out = deepcopy(state)
    browser = browser_status()
    out["connection"]["browser"] = browser
    if browser.get("warming") and out["connection"].get("status") not in ("cloud", "authenticated", "relay"):
        out["connection"]["status"] = "connecting"
        out["connection"]["connected"] = False
    return out


def _summarize_bets(bets: list[dict[str, Any]]) -> dict[str, Any]:
    display_currency = next((b.get("display_currency") for b in bets if b.get("display_currency")), "USD")
    settled = [b for b in bets if b.get("result") not in {"open", "unknown"}]
    wins = sum(1 for b in bets if b.get("result") == "won")
    losses = sum(1 for b in bets if b.get("result") == "lost")
    pushes = sum(1 for b in bets if b.get("result") == "push")
    cashouts = sum(1 for b in bets if b.get("result") == "cashed_out")
    total_staked = round(sum(float(b.get("stake_value") or 0) for b in bets), 2)
    total_return = round(sum(float(b.get("payout_value") or 0) for b in settled), 2)
    profit = round(total_return - total_staked, 2)
    roi_pct = round((profit / total_staked) * 100, 2) if total_staked else 0.0
    singles = sum(1 for b in bets if (b.get("selection_count") or 0) <= 1)
    parlays = sum(1 for b in bets if (b.get("selection_count") or 0) > 1)
    fixture_bet_counts: dict[str, int] = {}
    for b in bets:
        fixture = b.get("fixture_name") or "Unknown"
        fixture_bet_counts[fixture] = fixture_bet_counts.get(fixture, 0) + 1
    n_fixtures = len(fixture_bet_counts) or 1
    avg_bets_per_fixture = round(len(bets) / n_fixtures, 2)
    multi_bet_fixtures = sum(1 for c in fixture_bet_counts.values() if c >= 2)
    prefers_spread_singles = avg_bets_per_fixture >= 2.0 or multi_bet_fixtures >= max(1, n_fixtures // 2)
    avg_odds_values = [float(b.get("combined_odds") or 0) for b in bets if float(b.get("combined_odds") or 0) > 1]
    avg_odds = round(sum(avg_odds_values) / len(avg_odds_values), 2) if avg_odds_values else None
    market_breakdown: dict[str, dict[str, Any]] = {}
    for bet in bets:
        family = str(bet.get("market_family") or "other")
        bucket = market_breakdown.setdefault(family, {"count": 0, "profit_value": 0.0, "wins": 0, "losses": 0})
        bucket["count"] += 1
        bucket["profit_value"] = round(bucket["profit_value"] + float(bet.get("profit_value") or 0), 2)
        if bet.get("result") == "won":
            bucket["wins"] += 1
        elif bet.get("result") == "lost":
            bucket["losses"] += 1

    cumulative = []
    running = 0.0
    for idx, bet in enumerate(sorted(bets, key=lambda b: b.get("created_at") or "")):
        running = round(running + float(bet.get("profit_value") or 0), 2)
        cumulative.append(
            {
                "i": idx + 1,
                "label": bet.get("fixture_name") or f"Bet {idx + 1}",
                "profit_value": round(float(bet.get("profit_value") or 0), 2),
                "running_profit_value": running,
                "result": bet.get("result"),
            }
        )

    ranked_markets = sorted(
        (
            {
                "market": family,
                **stats,
                "roi_pct": round((stats["profit_value"] / sum(float(b.get("stake_value") or 0) for b in bets if b.get("market_family") == family)) * 100, 2)
                if any(b.get("market_family") == family and float(b.get("stake_value") or 0) > 0 for b in bets)
                else 0.0,
            }
            for family, stats in market_breakdown.items()
        ),
        key=lambda item: item["profit_value"],
        reverse=True,
    )
    top_market = ranked_markets[0] if ranked_markets else None
    leak_market = ranked_markets[-1] if len(ranked_markets) > 1 else None
    recent = bets[:10]
    recent_profit = round(sum(float(b.get("profit_value") or 0) for b in recent), 2)
    recent_hit_rate = round(
        (sum(1 for b in recent if b.get("result") == "won") / max(1, sum(1 for b in recent if b.get("result") in {"won", "lost"}))) * 100,
        1,
    ) if recent else None

    longshot_losses = sum(1 for b in bets if float(b.get("combined_odds") or 0) >= 3 and b.get("result") == "lost")
    recommended_focus = [m["market"] for m in ranked_markets[:2] if m["profit_value"] > 0]
    caution_markets = [m["market"] for m in ranked_markets[-2:] if m["profit_value"] < 0]
    avoid_parlays = parlays >= singles and (sum(float(b.get("profit_value") or 0) for b in bets if b.get("bet_type") == "parlay") < 0)
    max_odds = 2.2 if longshot_losses >= 3 else 3.0
    avg_stake = round(sum(float(b.get("stake_value") or 0) for b in bets) / max(1, len(bets)), 2)
    max_stake = round(max((float(b.get("stake_value") or 0) for b in bets), default=0.0), 2)
    intuitive_bets = sum(
        1
        for b in bets
        if b.get("bet_type") == "parlay"
        or b.get("market_family") in {"scorers", "other"}
        or float(b.get("combined_odds") or 0) >= 3
    )
    intuition_rate = round((intuitive_bets / max(1, len(bets))) * 100, 1)
    fixture_exposure: dict[str, float] = {}
    for b in bets:
        fixture = b.get("fixture_name") or "Unknown"
        fixture_exposure[fixture] = fixture_exposure.get(fixture, 0.0) + float(b.get("stake_value") or 0)
    top_fixture = max(fixture_exposure.items(), key=lambda kv: kv[1], default=(None, 0.0))

    insights: list[str] = []
    if parlays >= max(3, singles):
        insights.append("You are leaning heavily into parlays. That usually adds variance faster than it adds edge.")
    if longshot_losses >= 3:
        insights.append("A lot of the damage is coming from long-odds bets. Trim stake size on 3.0+ prices unless the edge is clear.")
    if losses > wins and total_staked >= 100:
        insights.append("Your recent sample is losing overall. Focus on fewer bets and tighter price discipline before scaling volume.")
    if sum(1 for b in bets if b.get("result") == "open") >= 5:
        insights.append("You have a large number of open bets. Watch for correlated exposure across the same teams or match narratives.")

    next_actions: list[str] = []
    if avg_stake > 0:
        next_actions.append(
            f"Keep standard singles around {display_currency} {round(avg_stake):,} and only scale above that when the model edge is clearly positive."
        )
    if avoid_parlays:
        next_actions.append("Parlays are hurting your sample. Use them as low-stake sidecars, not the core of your card.")
    if recommended_focus:
        next_actions.append(f"Your best recent bet families are {', '.join(recommended_focus)}. Let those lead the next slate.")
    if caution_markets:
        next_actions.append(f"Trim exposure on {', '.join(caution_markets)} until your hit rate improves there.")
    if intuition_rate >= 45:
        next_actions.append("A big part of your action is intuition-driven. Keep those bets smaller unless they also show a real model edge.")
    if top_fixture and top_fixture[1] >= avg_stake * 2:
        next_actions.append(
            f"You tend to concentrate on certain matches. Cap single-game exposure below {display_currency} {round(top_fixture[1]):,} unless you intentionally want a high-conviction spot."
        )

    profile = {
        "confidence": "high" if len(bets) >= 25 else "medium" if len(bets) >= 10 else "low",
        "focus_markets": recommended_focus,
        "caution_markets": caution_markets,
        "avoid_parlays": avoid_parlays,
        "prefers_spread_singles": prefers_spread_singles,
        "avg_bets_per_fixture": avg_bets_per_fixture,
        "multi_bet_fixture_rate": round(multi_bet_fixtures / n_fixtures, 2),
        "singles_count": singles,
        "parlays_count": parlays,
        "max_preferred_odds": max_odds,
        "top_market": top_market,
        "leak_market": leak_market,
        "recent_profit_value": recent_profit,
        "recent_hit_rate_pct": recent_hit_rate,
        "avg_stake_value": avg_stake,
        "max_stake_value": max_stake,
        "intuition_rate_pct": intuition_rate,
        "top_fixture_exposure": {
            "fixture": top_fixture[0],
            "stake_value": round(top_fixture[1], 2),
        } if top_fixture[0] else None,
        "summary": (
            (
                f"You usually spread {avg_bets_per_fixture:.0f} separate bets per match, "
                f"we'll prioritise multi-single routes over one big parlay."
                if prefers_spread_singles else
                f"Lean into {', '.join(recommended_focus) if recommended_focus else 'disciplined singles'}; "
                f"be careful with {', '.join(caution_markets) if caution_markets else 'overextended longshots'}."
            )
        ),
    }

    overview = {
        "win_loss_text": (
            f"{wins} wins, {losses} losses, {pushes} pushes, {cashouts} cashouts."
            if bets
            else "No settled bets imported yet."
        ),
        "roi_text": (
            f"ROI is {roi_pct}% because you staked {display_currency} {round(total_staked):,} and netted {display_currency} {round(profit):,}."
            if total_staked
            else "ROI needs settled stake volume before it means anything."
        ),
        "curve_text": (
            "The performance curve is your running bankroll path bet by bet. Rising means your process is compounding; falling means your sizing or bet selection is dragging."
        ),
        "market_text": (
            "Strengths and leaks ranks the bet families that are helping or hurting most, so your next card can lean into what is actually working."
        ),
        "recommendations": next_actions[:5],
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
        "profit_value": profit,
        "roi_pct": roi_pct,
        "display_currency": display_currency,
        "singles_count": singles,
        "parlays_count": parlays,
        "avg_odds": avg_odds,
        "market_breakdown": market_breakdown,
        "ranked_markets": ranked_markets,
        "cumulative_profit": cumulative,
        "insights": insights,
        "overview": overview,
        "profile": profile,
        "bets": bets,
        "last_imported_at": _utc_now(),
        "cashouts": cashouts,
    }


def get_portfolio_state() -> dict[str, Any]:
    with _LOCK:
        state, changed = _ensure_privacy_defaults(_load_state())
        if changed:
            _save_state(state)
        return _merged_status(state)


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


def connect_browser_session(timeout: int = 300) -> dict[str, Any]:
    from bet_placer.config import stake_network_enabled

    # No live Stake path (no local Chrome, no cloud browser, no token).
    if not stake_network_enabled():
        with _LOCK:
            state = _load_state()
            has_bets = bool((state.get("portfolio") or {}).get("bets"))
            state["connection"].update(
                {
                    "status": "setup",
                    "connected": bool(has_bets),
                    "last_sync_status": "error" if not has_bets else "imported",
                    "last_sync_message": (
                        "Your journal is up to date from the last sync."
                        if has_bets
                        else (
                            "Stake live login is not available on this host yet. "
                            "Confirm bets from your slip, add past bets below, "
                            "or set BROWSERBASE_API_KEY so Connect can open Stake."
                        )
                    ),
                    "login_url": None,
                }
            )
            return _merged_status(_save_state(state))

    # Don't hold portfolio lock while Chrome / user login runs (can take minutes).
    login = wait_until_logged_in(timeout=timeout)
    browser = browser_status()
    with _LOCK:
        state = _load_state()
        login_url = login.get("login_url") or browser.get("login_url")
        if login.get("logged_in"):
            user = login.get("user") or {}
            who = user.get("name") or user.get("id") or "Stake"
            state["connection"].update(
                {
                    "status": "authenticated",
                    "connected": True,
                    "last_connected_at": _utc_now(),
                    "last_sync_status": "authenticated",
                    "last_sync_message": f"Connected as {who}. Tap Sync to refresh your journal.",
                    "stake_user": {"id": user.get("id"), "name": user.get("name")},
                    "login_url": login_url,
                }
            )
        elif login.get("ready") or browser.get("ready"):
            state["connection"].update(
                {
                    "status": "awaiting_login",
                    "connected": False,
                    "last_sync_status": "auth_required",
                    "last_sync_message": login.get("message")
                    or "Sign into Stake in the window we opened, then tap Connect again.",
                    "login_url": login_url,
                }
            )
        else:
            state["connection"].update(
                {
                    "status": "connecting",
                    "connected": False,
                    "last_sync_status": "needs_reconnect",
                    "last_sync_message": login.get("message")
                    or "Still starting the Stake window. Try Connect again in a moment.",
                    "login_url": login_url,
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
                    "last_sync_status": "error",
                    "last_sync_message": "Stake session is not active. Tap Connect Stake first, or confirm bets from your slip.",
                }
            )
            return _merged_status(_save_state(state))
        if not browser.get("have_auth_token") and state["connection"].get("status") != "authenticated":
            state["connection"].update(
                {
                    "status": "awaiting_login",
                    "connected": False,
                    "last_sync_at": _utc_now(),
                    "last_sync_status": "error",
                    "last_sync_message": (
                        "Stake Chrome is open, but no account session yet. "
                        "Sign into Stake (Connect Stake), then sync again. "
                        "Or confirm bets from your slip / add past bets below."
                    ),
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
                    "status": "awaiting_login",
                    "connected": False,
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

        summary = _summarize_bets(bets)
        summary["model_audit"] = {
            "available": False,
            "audited_legs": 0,
            "aligned_legs": 0,
            "against_legs": 0,
            "strong_edges": 0,
            "skip_flags": 0,
            "message": "Model audit running in the background…",
            "pending": True,
        }
        state["portfolio"] = summary
        state["connection"].update(
            {
                "status": "authenticated",
                "connected": True,
                "last_sync_at": _utc_now(),
                "last_sync_status": "imported",
                "last_sync_message": f"Imported {len(bets)} bets from your Stake account history.",
            }
        )
        result = _merged_status(_save_state(state))

    def _audit_in_background() -> None:
        try:
            with _LOCK:
                bg_state = _load_state()
                bg_bets = list(bg_state.get("portfolio", {}).get("bets") or [])
            if not bg_bets:
                return
            audit = _audit_bets_against_model(bg_bets)
            with _LOCK:
                bg_state = _load_state()
                bg_state["portfolio"]["bets"] = bg_bets
                bg_state["portfolio"]["model_audit"] = audit
                _save_state(bg_state)
        except Exception:
            pass

    Thread(target=_audit_in_background, daemon=True, name="portfolio-audit").start()
    return result


def ingest_portfolio_relay(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a laptop-synced portfolio snapshot (cloud has no Stake Chrome)."""
    with _LOCK:
        state = _load_state()
        portfolio = payload.get("portfolio")
        if isinstance(portfolio, dict) and portfolio:
            state["portfolio"] = portfolio
        privacy = payload.get("privacy")
        if isinstance(privacy, dict):
            # Keep cloud privacy toggles opt-in from laptop snapshot only if explicit
            for key in ("portfolio_enabled", "risk_acknowledged", "learning_opt_in"):
                if key in privacy:
                    state["privacy"][key] = bool(privacy[key])
            if privacy.get("risk_acknowledged"):
                state["privacy"]["consent_version"] = _CONSENT_VERSION
                state["privacy"]["consent_accepted_at"] = privacy.get("consent_accepted_at") or _utc_now()
        stake_user = (payload.get("connection") or {}).get("stake_user")
        bet_count = len((state.get("portfolio") or {}).get("bets") or [])
        state["connection"].update(
            {
                "status": "relay",
                "connected": True,
                "last_sync_at": _utc_now(),
                "last_sync_status": "imported",
                "last_sync_message": (
                    f"Imported {bet_count} bets from laptop Stake login."
                    if bet_count
                    else "Received portfolio relay from laptop (empty history)."
                ),
                "stake_user": stake_user if isinstance(stake_user, dict) else state["connection"].get("stake_user"),
            }
        )
        return _merged_status(_save_state(state))


def portfolio_relay_export() -> dict[str, Any]:
    """Slice of local state safe to POST to cloud /api/portfolio/relay."""
    with _LOCK:
        state = _load_state()
    return {
        "portfolio": state.get("portfolio") or {},
        "privacy": {
            "portfolio_enabled": bool((state.get("privacy") or {}).get("portfolio_enabled")),
            "risk_acknowledged": bool((state.get("privacy") or {}).get("risk_acknowledged")),
            "learning_opt_in": bool((state.get("privacy") or {}).get("learning_opt_in")),
            "consent_accepted_at": (state.get("privacy") or {}).get("consent_accepted_at"),
        },
        "connection": {
            "stake_user": (state.get("connection") or {}).get("stake_user"),
        },
    }


def _normalize_manual_bet(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a portfolio bet row from slip/manual fields."""
    import uuid

    stake = float(raw.get("stake") or raw.get("stake_value") or 0)
    odds = float(raw.get("odds") or raw.get("combined_odds") or 0)
    result = str(raw.get("result") or "open").lower()
    if result not in {"open", "won", "lost", "push", "cashed_out", "unknown"}:
        result = "open"
    payout = float(raw.get("payout") or raw.get("payout_value") or 0)
    if result == "won" and payout <= 0 and stake > 0 and odds > 1:
        payout = round(stake * odds, 2)
    elif result == "lost":
        payout = 0.0
    elif result == "push" and payout <= 0:
        payout = stake
    elif result == "open":
        payout = 0.0

    home = (raw.get("home") or raw.get("home_team") or "").strip()
    away = (raw.get("away") or raw.get("away_team") or "").strip()
    fixture = (raw.get("fixture_name") or "").strip() or (
        f"{home} vs {away}" if home and away else (home or away or "Manual bet")
    )
    selection = (raw.get("selection") or raw.get("label") or "").strip() or "Selection"
    market = (raw.get("market") or raw.get("market_name") or raw.get("market_family") or "manual").strip()
    bet_id = str(raw.get("id") or raw.get("bet_id") or f"manual-{uuid.uuid4().hex[:12]}")
    selections = raw.get("selections")
    if not isinstance(selections, list) or not selections:
        selections = [
            {
                "fixture_name": fixture,
                "selection": selection,
                "odds": odds or None,
                "status": result if result != "open" else "pending",
                "payout": payout if result != "open" else None,
            }
        ]
    return _migrate_legacy_bet(
        {
            "id": bet_id,
            "bet_id": bet_id,
            "source": str(raw.get("source") or "manual"),
            "created_at": raw.get("created_at") or _utc_now(),
            "status": "open" if result == "open" else result,
            "result": result,
            "active": result == "open",
            "currency": raw.get("currency") or "INR",
            "display_currency": raw.get("display_currency") or raw.get("currency") or "INR",
            "stake": stake,
            "stake_value": stake,
            "payout": payout,
            "payout_value": payout,
            "combined_odds": odds or None,
            "fixture_name": fixture,
            "home_team": home or None,
            "away_team": away or None,
            "league": raw.get("league"),
            "selection_count": len(selections),
            "bet_type": "parlay" if len(selections) > 1 else "single",
            "market_family": market,
            "selections": selections,
            "notes": raw.get("notes"),
        }
    )


def _merge_portfolio_bets(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(b.get("id") or b.get("bet_id")): b for b in existing if b.get("id") or b.get("bet_id")}
    for bet in incoming:
        key = str(bet.get("id") or bet.get("bet_id"))
        by_id[key] = bet
    return sorted(by_id.values(), key=lambda b: b.get("created_at") or "", reverse=True)


def _leg_fixture_name(leg: dict[str, Any]) -> str:
    home = str(leg.get("home") or "").strip()
    away = str(leg.get("away") or "").strip()
    if home and away:
        return f"{home} vs {away}"
    if home or away:
        return home or away
    return str(leg.get("fixture_name") or leg.get("label") or "Match").strip()


def confirm_slip_bets(
    *,
    legs: list[dict[str, Any]] | None = None,
    multi_stake: float | None = None,
    multi_odds: float | None = None,
) -> dict[str, Any]:
    """Confirm slip legs as real placed bets in the journal (live / upcoming)."""
    legs = [l for l in (legs or []) if isinstance(l, dict)]
    if not legs:
        raise ValueError("Add at least one leg before confirming a placed bet.")

    incoming: list[dict[str, Any]] = []
    multi = float(multi_stake or 0)
    if multi > 0 and len(legs) >= 2:
        selections = []
        for leg in legs:
            selections.append(
                {
                    "fixture_name": _leg_fixture_name(leg),
                    "selection": leg.get("label") or leg.get("selection") or "Pick",
                    "odds": float(leg.get("odds") or 0) or None,
                    "status": "pending",
                }
            )
        odds = float(multi_odds or 0)
        if odds <= 1:
            odds = 1.0
            for leg in legs:
                o = float(leg.get("odds") or 0)
                if o > 1:
                    odds *= o
        incoming.append(
            _normalize_manual_bet(
                {
                    "source": "slip_confirm",
                    "stake": multi,
                    "odds": odds,
                    "result": "open",
                    "fixture_name": " + ".join(_leg_fixture_name(l) for l in legs[:4]),
                    "selection": "Multi",
                    "market": "multi",
                    "selections": selections,
                }
            )
        )
    else:
        for leg in legs:
            stake = float(leg.get("stake") or 0)
            if stake <= 0:
                continue
            incoming.append(
                _normalize_manual_bet(
                    {
                        "id": f"slip-{leg.get('id') or leg.get('label')}",
                        "source": "slip_confirm",
                        "home": leg.get("home"),
                        "away": leg.get("away"),
                        "selection": leg.get("label") or leg.get("selection"),
                        "market": leg.get("marketName") or leg.get("market") or "board",
                        "odds": leg.get("odds"),
                        "stake": stake,
                        "result": leg.get("result") or "open",
                        "payout": leg.get("payout"),
                    }
                )
            )
    if not incoming:
        raise ValueError("Set an amount on at least one single (or a multi stake) before confirming.")

    with _LOCK:
        state, _ = _ensure_privacy_defaults(_load_state())
        existing = list((state.get("portfolio") or {}).get("bets") or [])
        merged = _merge_portfolio_bets(existing, incoming)
        summary = _summarize_bets(merged)
        summary["model_audit"] = {
            "available": False,
            "audited_legs": 0,
            "aligned_legs": 0,
            "against_legs": 0,
            "strong_edges": 0,
            "skip_flags": 0,
            "message": "Manual and confirmed slip bets are in your journal.",
            "pending": False,
        }
        state["portfolio"] = summary
        state["connection"].update(
            {
                "last_sync_at": _utc_now(),
                "last_sync_status": "confirmed",
                "last_sync_message": f"Confirmed {len(incoming)} placed bet(s) into your journal.",
            }
        )
        return _merged_status(_save_state(state))


def add_manual_portfolio_bet(payload: dict[str, Any]) -> dict[str, Any]:
    """Add or update a past / manual journal bet."""
    if not isinstance(payload, dict):
        raise ValueError("Bet payload required.")
    bet = _normalize_manual_bet({**payload, "source": payload.get("source") or "manual_past"})
    if float(bet.get("stake_value") or 0) <= 0:
        raise ValueError("Stake must be greater than 0.")
    if not (bet.get("selections") or []):
        raise ValueError("Selection is required.")

    with _LOCK:
        state, _ = _ensure_privacy_defaults(_load_state())
        existing = list((state.get("portfolio") or {}).get("bets") or [])
        merged = _merge_portfolio_bets(existing, [bet])
        summary = _summarize_bets(merged)
        summary["model_audit"] = (state.get("portfolio") or {}).get("model_audit") or {
            "available": False,
            "message": "Manual bet saved.",
        }
        state["portfolio"] = summary
        state["connection"].update(
            {
                "last_sync_at": _utc_now(),
                "last_sync_status": "confirmed",
                "last_sync_message": f"Saved manual bet: {bet.get('fixture_name')}.",
            }
        )
        return _merged_status(_save_state(state))


def update_portfolio_bet_result(bet_id: str, result: str, payout: float | None = None) -> dict[str, Any]:
    """Mark a journal bet won/lost/push (for open confirmed slips)."""
    result = str(result or "").lower()
    if result not in {"won", "lost", "push", "cashed_out", "open"}:
        raise ValueError("Result must be won, lost, push, cashed_out, or open.")
    with _LOCK:
        state, _ = _ensure_privacy_defaults(_load_state())
        bets = list((state.get("portfolio") or {}).get("bets") or [])
        found = None
        for b in bets:
            if str(b.get("id") or b.get("bet_id")) == str(bet_id):
                found = b
                break
        if not found:
            raise ValueError("Bet not found.")
        stake = float(found.get("stake_value") or 0)
        odds = float(found.get("combined_odds") or 0)
        if payout is None:
            if result == "won" and odds > 1:
                payout = round(stake * odds, 2)
            elif result == "push":
                payout = stake
            elif result == "lost":
                payout = 0.0
            else:
                payout = float(found.get("payout_value") or 0)
        found["result"] = result
        found["status"] = "open" if result == "open" else result
        found["active"] = result == "open"
        found["payout"] = float(payout)
        found["payout_value"] = float(payout)
        found["profit_value"] = round(float(payout) - stake, 2) if result != "open" else 0.0
        for sel in found.get("selections") or []:
            sel["status"] = "pending" if result == "open" else result
        summary = _summarize_bets(bets)
        state["portfolio"] = summary
        state["connection"]["last_sync_message"] = f"Updated bet result to {result}."
        state["connection"]["last_sync_at"] = _utc_now()
        return _merged_status(_save_state(state))
