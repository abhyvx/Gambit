from __future__ import annotations

import json
import re
import secrets
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from bet_placer.config import data_path, get_settings
from bet_placer.data.stake_browser import browser_status, wait_until_logged_in
from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.security.secrets import reveal as _reveal_token
from bet_placer.security.secrets import seal as _seal_token

_LOCK = Lock()
_CONSENT_VERSION = "2026-07-02"
_CURRENT_USER_ID: ContextVar[str | None] = ContextVar("portfolio_user_id", default=None)
_SYNC_JOBS = data_path("stake_sync_jobs.json")
_RELAY_HEARTBEAT = data_path("relay_heartbeat.json")


def set_portfolio_user(user_id: str | None) -> None:
    _CURRENT_USER_ID.set((user_id or "").strip() or None)


def touch_relay_heartbeat() -> None:
    """Odds-link machine pings this when draining jobs / pushing odds."""
    try:
        _RELAY_HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        _RELAY_HEARTBEAT.write_text(
            json.dumps({"at": _utc_now()}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def relay_heartbeat() -> dict[str, Any]:
    if not _RELAY_HEARTBEAT.is_file():
        return {"seen": False, "at": None, "age_s": None}
    try:
        raw = json.loads(_RELAY_HEARTBEAT.read_text(encoding="utf-8"))
        at = raw.get("at")
        age = None
        if at:
            try:
                age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds()))
            except Exception:
                age = None
        return {"seen": True, "at": at, "age_s": age, "online": age is not None and age < 900}
    except Exception:
        return {"seen": False, "at": None, "age_s": None}


def _store_path() -> Path:
    settings = get_settings()
    if settings.portfolio_store_path:
        return Path(settings.portfolio_store_path).expanduser()
    uid = _CURRENT_USER_ID.get()
    if uid:
        return data_path("portfolios", f"{uid}.json")
    return data_path("portfolio_state.json")


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
    if isinstance(data.get("secrets"), dict):
        state["secrets"] = dict(data["secrets"])
    bets = state.get("portfolio", {}).get("bets") or []
    if bets:
        migrated = [_migrate_legacy_bet(b) for b in bets]
        summary = _summarize_bets(migrated)
        # Keep prior audit if present. Re-scoring every GET against the model hangs big journals.
        prior = (data.get("portfolio") or {}).get("model_audit") if isinstance(data.get("portfolio"), dict) else None
        if isinstance(prior, dict):
            summary["model_audit"] = prior
        state["portfolio"] = summary
    return state


def _save_state(state: dict[str, Any]) -> dict[str, Any]:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    try:
        _persist_portfolio_learning_signal(state)
    except Exception:
        pass
    try:
        from bet_placer.auth.persist import schedule_users_persist
        schedule_users_persist()
    except Exception:
        pass
    return state


def _merged_status(state: dict[str, Any]) -> dict[str, Any]:
    """Attach live browser flags without rewriting login status from CF-ready alone."""
    out = deepcopy(state)
    out.pop("secrets", None)
    browser = browser_status()
    out["connection"]["browser"] = browser
    out["odds_link"] = relay_heartbeat()
    if browser.get("warming") and out["connection"].get("status") not in ("cloud", "authenticated", "relay", "syncing"):
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
    sport_breakdown: dict[str, dict[str, Any]] = {}
    monthly_breakdown: dict[str, dict[str, Any]] = {}
    for b in bets:
        sport = str(b.get("sport") or "other")
        month = str(b.get("created_at") or "")[:7] or "unknown"
        sb = sport_breakdown.setdefault(
            sport,
            {"sport": sport, "count": 0, "wins": 0, "losses": 0, "profit_value": 0.0, "staked": 0.0},
        )
        sb["count"] += 1
        sb["profit_value"] = round(sb["profit_value"] + float(b.get("profit_value") or 0), 2)
        sb["staked"] = round(sb["staked"] + float(b.get("stake_value") or 0), 2)
        if b.get("result") == "won":
            sb["wins"] += 1
        elif b.get("result") == "lost":
            sb["losses"] += 1
        mb = monthly_breakdown.setdefault(month, {"month": month, "count": 0, "profit_value": 0.0})
        mb["count"] += 1
        mb["profit_value"] = round(mb["profit_value"] + float(b.get("profit_value") or 0), 2)
    by_sport = []
    for row in sport_breakdown.values():
        staked = float(row.get("staked") or 0)
        row["roi_pct"] = round((float(row.get("profit_value") or 0) / staked) * 100, 2) if staked else 0.0
        row["hit_rate_pct"] = round((int(row.get("wins") or 0) / max(1, int(row.get("wins") or 0) + int(row.get("losses") or 0))) * 100, 1)
        by_sport.append(row)
    by_sport.sort(key=lambda row: row.get("profit_value", 0), reverse=True)
    monthly_form = sorted(monthly_breakdown.values(), key=lambda row: row["month"])[-6:]
    learning_feedback = _portfolio_learning_summary(bets)

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
    if learning_feedback.get("available") and learning_feedback.get("follow_model_roi_pct") is not None:
        follow_roi = float(learning_feedback.get("follow_model_roi_pct") or 0)
        fade_roi = float(learning_feedback.get("fade_model_roi_pct") or 0)
        if follow_roi > fade_roi:
            next_actions.append(
                f"Your model-aligned bets are outperforming the fades ({follow_roi:.1f}% ROI vs {fade_roi:.1f}%). Let the model veto more of the loose action."
            )
        else:
            next_actions.append(
                f"Your model fades are not materially worse than aligned bets ({follow_roi:.1f}% vs {fade_roi:.1f}% ROI). Re-check stake sizing before trusting every edge blindly."
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
        "by_sport": by_sport,
        "monthly_form": monthly_form,
        "cumulative_profit": cumulative,
        "insights": insights,
        "overview": overview,
        "learning_feedback": learning_feedback,
        "profile": profile,
        "bets": bets,
        "last_imported_at": _utc_now(),
        "cashouts": cashouts,
    }


def _portfolio_learning_summary(bets: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [b for b in bets if b.get("result") in {"won", "lost"}]
    audited = [b for b in settled if isinstance((b.get("model_view") or {}).get("overall"), str)]
    if not audited:
        return {
            "available": False,
            "audited_bets": 0,
            "message": "Learning appears after settled bets can be matched back to the model board.",
            "recommendations": [],
        }

    buckets: dict[str, dict[str, Any]] = {}
    by_market: dict[str, dict[str, Any]] = {}
    recent_delta = 0.0
    for bet in audited:
        tone = str((bet.get("model_view") or {}).get("overall") or "neutral")
        bucket = buckets.setdefault(tone, {"bets": 0, "wins": 0, "profit_value": 0.0, "staked": 0.0})
        bucket["bets"] += 1
        bucket["profit_value"] = round(bucket["profit_value"] + float(bet.get("profit_value") or 0), 2)
        bucket["staked"] = round(bucket["staked"] + float(bet.get("stake_value") or 0), 2)
        if bet.get("result") == "won":
            bucket["wins"] += 1
        market = str(bet.get("market_family") or "other")
        mk = by_market.setdefault(market, {"market": market, "bets": 0, "profit_value": 0.0})
        mk["bets"] += 1
        mk["profit_value"] = round(mk["profit_value"] + float(bet.get("profit_value") or 0), 2)
    for idx, bet in enumerate(sorted(audited, key=lambda row: row.get("created_at") or "")[-8:]):
        recent_delta += float(bet.get("profit_value") or 0)

    def _row(name: str) -> dict[str, Any]:
        row = buckets.get(name) or {}
        staked = float(row.get("staked") or 0)
        wins = int(row.get("wins") or 0)
        bets_n = int(row.get("bets") or 0)
        return {
            "bets": bets_n,
            "wins": wins,
            "profit_value": round(float(row.get("profit_value") or 0), 2),
            "roi_pct": round((float(row.get("profit_value") or 0) / staked) * 100, 2) if staked else None,
            "hit_rate_pct": round((wins / bets_n) * 100, 1) if bets_n else None,
        }

    good = _row("good")
    bad = _row("bad")
    neutral = _row("neutral")
    recs: list[str] = []
    if good["bets"]:
        recs.append(
            f"Model-backed bets: {good['bets']} settled · {good['hit_rate_pct'] or 0:.1f}% hit · {good['roi_pct'] or 0:.1f}% ROI."
        )
    if bad["bets"]:
        recs.append(
            f"Model-disliked bets: {bad['bets']} settled · {bad['hit_rate_pct'] or 0:.1f}% hit · {bad['roi_pct'] or 0:.1f}% ROI."
        )
    if good["roi_pct"] is not None and bad["roi_pct"] is not None:
        if good["roi_pct"] > bad["roi_pct"]:
            recs.append("Your results improve when you stay closer to the model's approved prices.")
        else:
            recs.append("Your fades are not underperforming enough yet to trust raw model agreement on its own; sizing and market choice need more weight.")
    if recent_delta < 0:
        recs.append("Recent audited bets are negative. Tighten stake size until the model-aligned sample turns back up.")

    return {
        "available": True,
        "audited_bets": len(audited),
        "follow_model_bets": good["bets"],
        "fade_model_bets": bad["bets"],
        "neutral_bets": neutral["bets"],
        "follow_model_roi_pct": good["roi_pct"],
        "fade_model_roi_pct": bad["roi_pct"],
        "follow_model_hit_rate_pct": good["hit_rate_pct"],
        "fade_model_hit_rate_pct": bad["hit_rate_pct"],
        "recent_profit_value": round(recent_delta, 2),
        "by_market": sorted(by_market.values(), key=lambda row: row["profit_value"], reverse=True)[:8],
        "recommendations": recs[:5],
        "message": f"Learning signal built from {len(audited)} settled, model-mapped bets.",
    }


def _persist_portfolio_learning_signal(state: dict[str, Any]) -> None:
    privacy = (state.get("privacy") or {})
    if not privacy.get("learning_opt_in"):
        return
    portfolio = state.get("portfolio") or {}
    feedback = portfolio.get("learning_feedback") or {}
    if not feedback.get("available"):
        return
    from bet_placer.ml.activity_log import log_activity
    from bet_placer.ml.params import load_params, save_params

    params = load_params(force=True)
    payload = {
        **feedback,
        "updated_at": _utc_now(),
        "bet_count": int(portfolio.get("bet_count") or 0),
        "settled_count": int(portfolio.get("settled_count") or 0),
    }
    params["portfolio_learning"] = payload
    report = dict(params.get("report") or {})
    report["portfolio_learning"] = payload
    params["report"] = report
    save_params(params)
    try:
        log_activity(
            "portfolio_learning",
            f"Portfolio learning updated from {payload['audited_bets']} settled model-mapped bets.",
            detail={
                "follow_roi": payload.get("follow_model_roi_pct"),
                "fade_roi": payload.get("fade_model_roi_pct"),
            },
        )
    except Exception:
        pass


def _parse_fixture_sides(fixture_name: str | None) -> tuple[str, str]:
    text = (fixture_name or "").strip()
    for sep in (" vs ", " v ", " @ "):
        if sep in text.lower():
            # case-insensitive split
            idx = text.lower().index(sep)
            return text[:idx].strip(), text[idx + len(sep) :].strip()
    return "", ""


def _grade_portfolio_leg(sel: dict[str, Any], row: dict[str, Any]) -> bool | None:
    from bet_placer.ml.rec_grading import grade_leg

    market = str(sel.get("market") or sel.get("market_family") or "match_winner").lower()
    if market in {"board", "manual", "multi", "other", ""}:
        market = "match_winner"
    return grade_leg(
        {
            "market": market,
            "selection": sel.get("raw_selection") or sel.get("selection"),
            "label": sel.get("label") or sel.get("selection") or sel.get("pick_label"),
            "line": sel.get("line"),
            "combo_parts": sel.get("combo_parts"),
            "verified_stake": sel.get("verified_stake"),
        },
        home=row["home"],
        away=row["away"],
        hs=int(row["hs"]),
        aws=int(row["aws"]),
    )


def settle_open_portfolio_bets() -> dict[str, Any]:
    """Mark open journal bets won/lost once ESPN boards show a final score.

    Also settles paper-book slip tickets so craft learns from every tracked rec.
    """
    from bet_placer.ml.paper_book import (
        apply_paper_learning,
        lookup_finished_score,
        settle_open,
        _board_score_index,
    )

    paper: dict[str, Any] = {}
    try:
        paper = settle_open()
        if int(paper.get("settled") or 0) > 0:
            try:
                apply_paper_learning()
            except Exception:
                pass
    except Exception as exc:
        paper = {"error": str(exc)[:160]}

    try:
        by_id, by_pair = _board_score_index()
    except Exception as exc:
        return {"settled": 0, "paper": paper, "error": str(exc)[:160]}

    settled = 0
    with _LOCK:
        state, _ = _ensure_privacy_defaults(_load_state())
        bets = list((state.get("portfolio") or {}).get("bets") or [])
        changed = False
        for bet in bets:
            if bet.get("result") != "open":
                continue
            selections = list(bet.get("selections") or [])
            hits: list[bool | None] = []
            if len(selections) > 1:
                for sel in selections:
                    home, away = _parse_fixture_sides(sel.get("fixture_name") or bet.get("fixture_name"))
                    row = lookup_finished_score(
                        match_id=sel.get("match_id") or bet.get("match_id"),
                        home=home or bet.get("home_team"),
                        away=away or bet.get("away_team"),
                        by_id=by_id,
                        by_pair=by_pair,
                    )
                    if not row:
                        hits.append(None)
                        continue
                    hit = _grade_portfolio_leg(sel, row)
                    hits.append(hit)
                    if hit is True:
                        sel["status"] = "won"
                    elif hit is False:
                        sel["status"] = "lost"
            else:
                home = bet.get("home_team") or ""
                away = bet.get("away_team") or ""
                if not home or not away:
                    home, away = _parse_fixture_sides(bet.get("fixture_name"))
                row = lookup_finished_score(
                    match_id=bet.get("match_id") or bet.get("event_id"),
                    home=home,
                    away=away,
                    by_id=by_id,
                    by_pair=by_pair,
                )
                if not row:
                    continue
                sel0 = selections[0] if selections else {}
                leg = {
                    **sel0,
                    "market": bet.get("market_family") or sel0.get("market") or "match_winner",
                    "raw_selection": bet.get("raw_selection") or sel0.get("raw_selection") or sel0.get("selection"),
                    "selection": bet.get("raw_selection") or sel0.get("raw_selection") or sel0.get("selection"),
                    "line": bet.get("line") if bet.get("line") is not None else sel0.get("line"),
                    "label": bet.get("pick_label") or sel0.get("selection") or sel0.get("label"),
                    "pick_label": bet.get("pick_label"),
                }
                hit = _grade_portfolio_leg(leg, row)
                hits = [hit]
                if selections and hit is True:
                    selections[0]["status"] = "won"
                elif selections and hit is False:
                    selections[0]["status"] = "lost"

            if not hits or any(h is None for h in hits):
                continue
            won = all(bool(h) for h in hits)
            stake = float(bet.get("stake_value") or bet.get("stake") or 0)
            odds = float(bet.get("combined_odds") or 0)
            result = "won" if won else "lost"
            payout = round(stake * odds, 2) if won and odds > 1 else (stake if result == "push" else 0.0)
            bet["result"] = result
            bet["status"] = result
            bet["active"] = False
            bet["payout"] = payout
            bet["payout_value"] = payout
            bet["profit_value"] = round(payout - stake, 2)
            bet["settled_at"] = _utc_now()
            bet["settle_source"] = "espn_board"
            settled += 1
            changed = True

        if changed:
            summary = _summarize_bets(bets)
            summary["model_audit"] = (state.get("portfolio") or {}).get("model_audit") or {
                "available": False,
                "message": "Auto-settled from finished matches.",
            }
            state["portfolio"] = summary
            state["connection"]["last_sync_at"] = _utc_now()
            state["connection"]["last_sync_status"] = "settled"
            state["connection"]["last_sync_message"] = (
                f"Auto-settled {settled} bet(s) from finished match scores."
            )
            _save_state(state)

    return {"settled": settled, "paper": paper}


def get_portfolio_state() -> dict[str, Any]:
    with _LOCK:
        state, changed = _ensure_privacy_defaults(_load_state())
        if changed:
            _save_state(state)
        open_n = sum(
            1
            for b in ((state.get("portfolio") or {}).get("bets") or [])
            if b.get("result") == "open"
        )
        out = _merged_status(state)
    # Never block the portfolio HTTP path on ESPN scrapes.
    if open_n:
        Thread(target=_safe_full_settle, daemon=True).start()
    else:
        Thread(target=_safe_settle_paper_only, daemon=True).start()
    return out


def _safe_full_settle() -> None:
    try:
        settle_open_portfolio_bets()
    except Exception:
        pass


def _safe_settle_paper_only() -> None:
    try:
        from bet_placer.ml.paper_book import apply_paper_learning, settle_open

        out = settle_open()
        if int(out.get("settled") or 0) > 0:
            apply_paper_learning()
    except Exception:
        pass


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
    from bet_placer.config import remote_stake_browser_enabled

    # Cloud Chrome path (Browserbase) — open live-view login for the user.
    if remote_stake_browser_enabled():
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
            else:
                state["connection"].update(
                    {
                        "status": "awaiting_login",
                        "connected": False,
                        "last_sync_status": "auth_required",
                        "last_sync_message": (
                            login.get("message")
                            or "Open the Stake window, sign in, then tap Connect again."
                        ),
                        "login_url": login_url,
                    }
                )
            return _merged_status(_save_state(state))

    with _LOCK:
        state = _load_state()
        state["connection"].update(
            {
                "status": "setup",
                "connected": False,
                "last_sync_status": "needs_token",
                "last_sync_message": (
                    "Remote Stake browser is not configured on this host yet. "
                    "To avoid laptop popups, this app now stays token-only until Browserbase/CDP is set. "
                    "Paste your Stake API token below or configure Browserbase on Render."
                ),
                "login_url": "https://stake.com/settings/security",
            }
        )
        return _merged_status(_save_state(state))


def connect_with_stake_token(token: str, *, user_id: str | None = None) -> dict[str, Any]:
    """Common-user Stake connect: paste API token (no laptop scripts)."""
    token = (token or "").strip()
    if len(token) < 12:
        raise ValueError("Paste the full Stake API token from Settings → Security → API Tokens.")
    uid = (user_id or _CURRENT_USER_ID.get() or "").strip() or None
    if not uid:
        raise ValueError("Sign in first so your Stake token is stored only on your account.")

    token_reset = _CURRENT_USER_ID.set(uid)
    try:
        return _connect_with_stake_token_locked(token, user_id=uid)
    finally:
        _CURRENT_USER_ID.reset(token_reset)


def _connect_with_stake_token_locked(token: str, *, user_id: str) -> dict[str, Any]:
    # Try immediate token-only sync (no shared browser cookies — those expire / mix users).
    try:
        scraper = StakeScraper(api_token=token, use_browser=False, timeout=45)
        bets = []
        for offset in range(0, 150, 50):
            batch = scraper.fetch_user_bet_history(limit=50, offset=offset)
            if not batch:
                break
            bets.extend(batch)
            if len(batch) < 50:
                break
        with _LOCK:
            state, _ = _ensure_privacy_defaults(_load_state())
            summary = _summarize_bets(bets)
            state["portfolio"] = summary
            state["connection"].update(
                {
                    "status": "authenticated",
                    "connected": True,
                    "last_connected_at": _utc_now(),
                    "last_sync_at": _utc_now(),
                    "last_sync_status": "imported",
                    "last_sync_message": f"Imported {len(bets)} bets from your Stake API token.",
                    "has_stake_token": True,
                }
            )
            state["secrets"] = {"stake_api_token": _seal_token(token)}
            return _merged_status(_save_state(state))
    except Exception:
        pass

    # Queue for the odds-link machine (token-only scrape there — not the owner's login cookies).
    job_id = secrets.token_hex(8)
    with _LOCK:
        state, _ = _ensure_privacy_defaults(_load_state())
        state["secrets"] = {"stake_api_token": _seal_token(token)}
        hb = relay_heartbeat()
        link_note = (
            "Odds link is online — import usually finishes within a couple of minutes."
            if hb.get("online")
            else "Waiting for the live odds link to pick up your import (usually within a few minutes)."
        )
        state["connection"].update(
            {
                "status": "syncing",
                "connected": False,
                "last_sync_at": _utc_now(),
                "last_sync_status": "queued",
                "last_sync_message": f"Token saved on your account. {link_note}",
                "has_stake_token": True,
                "login_url": "https://stake.com/settings/security",
            }
        )
        out = _merged_status(_save_state(state))
        _enqueue_sync_job(
            {
                "id": job_id,
                "user_id": user_id,
                "token": _seal_token(token),
                "status": "pending",
                "created_at": _utc_now(),
            }
        )
        return out


def retry_stake_token_sync(*, user_id: str | None = None) -> dict[str, Any]:
    """Re-queue import from the sealed token already on this account."""
    uid = (user_id or _CURRENT_USER_ID.get() or "").strip() or None
    if not uid:
        raise ValueError("Sign in first.")
    token_reset = _CURRENT_USER_ID.set(uid)
    try:
        with _LOCK:
            state, _ = _ensure_privacy_defaults(_load_state())
            sealed = (state.get("secrets") or {}).get("stake_api_token")
            raw = _reveal_token(sealed) if sealed else ""
            if not raw or len(raw) < 12:
                raise ValueError("No Stake token on this account. Paste a new one.")
        return _connect_with_stake_token_locked(raw, user_id=uid)
    finally:
        _CURRENT_USER_ID.reset(token_reset)


def _enqueue_sync_job(job: dict[str, Any]) -> None:
    jobs = []
    if _SYNC_JOBS.is_file():
        try:
            jobs = json.loads(_SYNC_JOBS.read_text(encoding="utf-8"))
        except Exception:
            jobs = []
    if not isinstance(jobs, list):
        jobs = []
    # Replace pending job for same user
    uid = job.get("user_id")
    jobs = [j for j in jobs if not (j.get("status") == "pending" and j.get("user_id") == uid)]
    jobs.append(job)
    _SYNC_JOBS.parent.mkdir(parents=True, exist_ok=True)
    _SYNC_JOBS.write_text(json.dumps(jobs[-40:], indent=2), encoding="utf-8")


def list_pending_sync_jobs(secret: str) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.stake_relay_secret or secret != settings.stake_relay_secret:
        raise ValueError("Invalid relay secret")
    touch_relay_heartbeat()
    if not _SYNC_JOBS.is_file():
        return []
    try:
        jobs = json.loads(_SYNC_JOBS.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [
        {
            **j,
            "token": _reveal_token(j.get("token")),
        }
        for j in (jobs or [])
        if j.get("status") == "pending" and j.get("token")
    ]


def sync_jobs_snapshot(limit: int = 12) -> dict[str, Any]:
    """Admin-safe queue summary: never reveals stored Stake tokens."""
    if not _SYNC_JOBS.is_file():
        return {"pending": 0, "recent": []}
    try:
        jobs = json.loads(_SYNC_JOBS.read_text(encoding="utf-8"))
    except Exception:
        return {"pending": 0, "recent": []}
    if not isinstance(jobs, list):
        return {"pending": 0, "recent": []}
    recent = []
    pending = 0
    for row in jobs:
        if not isinstance(row, dict):
            continue
        if row.get("status") == "pending":
            pending += 1
        recent.append(
            {
                "id": row.get("id"),
                "user_id": row.get("user_id"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "completed_at": row.get("completed_at"),
                "error": (str(row.get("error") or "")[:180] or None),
            }
        )
    return {"pending": pending, "recent": recent[-limit:][::-1]}


def complete_sync_job(
    *,
    secret: str,
    job_id: str,
    bets: list[dict[str, Any]] | None = None,
    error: str | None = None,
    stake_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.stake_relay_secret or secret != settings.stake_relay_secret:
        raise ValueError("Invalid relay secret")

    jobs = []
    if _SYNC_JOBS.is_file():
        try:
            jobs = json.loads(_SYNC_JOBS.read_text(encoding="utf-8"))
        except Exception:
            jobs = []
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        raise ValueError("Job not found")

    uid = job.get("user_id")
    token = _CURRENT_USER_ID.set(uid)
    try:
        with _LOCK:
            state, _ = _ensure_privacy_defaults(_load_state())
            if error:
                job["status"] = "error"
                job["error"] = str(error)[:240]
                state["connection"].update(
                    {
                        "status": "setup",
                        "connected": False,
                        "last_sync_at": _utc_now(),
                        "last_sync_status": "error",
                        "last_sync_message": f"Stake sync failed: {str(error)[:180]}",
                    }
                )
            else:
                summary = _summarize_bets(bets or [])
                if stake_user:
                    summary["profile"] = {**(summary.get("profile") or {}), **stake_user}
                state["portfolio"] = summary
                state["connection"].update(
                    {
                        "status": "authenticated",
                        "connected": True,
                        "last_connected_at": _utc_now(),
                        "last_sync_at": _utc_now(),
                        "last_sync_status": "imported",
                        "last_sync_message": f"Imported {len(bets or [])} bets from your Stake account.",
                        "stake_user": stake_user,
                        "has_stake_token": True,
                    }
                )
                job["status"] = "done"
                job["bet_count"] = len(bets or [])
            _save_state(state)
            for j in jobs:
                if j.get("id") == job_id:
                    j.update(job)
            _SYNC_JOBS.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
            try:
                from bet_placer.auth.persist import write_users_bundle
                write_users_bundle()
            except Exception:
                pass
            return _merged_status(state)
    finally:
        _CURRENT_USER_ID.reset(token)


def disconnect_browser_session() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        state.pop("secrets", None)
        state["connection"].update(
            {
                "status": "disconnected",
                "connected": False,
                "has_stake_token": False,
                "login_url": None,
                "last_sync_message": "Disconnected Stake. Token removed. Journal rows stay until you delete them.",
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
            "match_id": raw.get("match_id") or raw.get("event_id") or raw.get("eventId"),
            "raw_selection": raw.get("raw_selection") or raw.get("selection"),
            "pick_label": raw.get("pick_label") or selection,
            "line": raw.get("line"),
            "sport": raw.get("sport") or raw.get("sportKey"),
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
                    "match_id": leg.get("eventId") or leg.get("match_id"),
                    "market": leg.get("marketName") or leg.get("market"),
                    "raw_selection": leg.get("selection"),
                    "line": leg.get("line"),
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
                        "match_id": leg.get("eventId") or leg.get("match_id"),
                        "raw_selection": leg.get("selection"),
                        "pick_label": leg.get("label") or leg.get("selection"),
                        "line": leg.get("line"),
                        "sport": leg.get("sport") or leg.get("sportKey"),
                    }
                )
            )
    if not incoming:
        raise ValueError("Set an amount on at least one single (or a multi stake) before confirming.")

    # Track the same legs in the paper book so craft auto-settles with ESPN scores.
    try:
        from bet_placer.ml.slip_learn import record_slip_tickets

        record_slip_tickets(
            [
                {
                    **leg,
                    "stake": float(leg.get("stake") or multi_stake or 0) or 1.0,
                    "id": leg.get("id") or f"slip-{leg.get('label')}",
                    "gem_kind": "slip_confirm",
                }
                for leg in legs
                if float(leg.get("odds") or 0) > 1
            ]
        )
    except Exception:
        pass

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
