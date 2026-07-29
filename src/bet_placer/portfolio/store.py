from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from bet_placer.config import get_settings
from bet_placer.data.stake_browser import browser_status, warmup_visible
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
                f"You usually spread {avg_bets_per_fixture:.0f} separate bets per match — "
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
    # Warmup can take minutes while the user clears Cloudflare — don't hold the
    # portfolio lock for the whole wait or other API calls appear hung.
    ok = warmup_visible(timeout=timeout)
    browser = browser_status()
    with _LOCK:
        state = _load_state()
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
                "status": "connected",
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
