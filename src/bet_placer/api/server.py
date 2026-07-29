"""Expanded FastAPI for sellable product."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from bet_placer.api.serializers import serialize_match_result, serialize_pipeline_results, serialize_value_bet
from bet_placer.config import get_settings, stake_network_enabled
from bet_placer.consensus.bettors import analyze_bettor_consensus
from bet_placer.consensus.web import WebConsensusFetcher
from bet_placer.data.catalog import CATEGORIES, list_sports
from bet_placer.data.providers import UnifiedOddsProvider
from bet_placer.data.stake_cache import fetch_or_cache
from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.engine.bankroll import allocate_match_budget, recommend_match_stake, recommend_stake
from bet_placer.engine.probability import ProbabilityEngine, rank_all_bets
from bet_placer.engine.verdict import MatchVerdictEngine

logger = logging.getLogger(__name__)


def _bearer_user(request: Request):
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        return None
    from bet_placer.auth.users import user_from_token

    return user_from_token(token)


def _bind_portfolio_user(request: Request):
    from bet_placer.portfolio.store import set_portfolio_user

    user = _bearer_user(request)
    set_portfolio_user((user or {}).get("id"))
    return user


def _warmup_stake_browser() -> None:
    """Optionally pre-launch Playwright Chromium (off by default).

    Non-blocking and failure-tolerant: a warmup failure must never stop the
    server — requests fall back to DraftKings pricing until Stake is opened.
    """
    settings = get_settings()
    from bet_placer.config import remote_stake_browser_enabled, stake_network_enabled

    if not stake_network_enabled():
        logger.info("Stake browser warmup skipped (no local/cloud browser path)")
        return
    # Cloud browser: warm by default so odds loop has a session. Local: only if asked.
    should_warm = bool(settings.stake_browser_warmup_on_startup or remote_stake_browser_enabled())
    if not should_warm:
        logger.info(
            "Stake browser warmup deferred (set STAKE_BROWSER_WARMUP_ON_STARTUP=1 to pre-launch)"
        )
        return

    def _go() -> None:
        try:
            from bet_placer.data.stake_browser import warmup

            if warmup():
                logger.info("Stake browser warmup complete")
            else:
                logger.warning("Stake browser warmup did not complete; will retry on demand")
        except Exception:
            logger.warning("Stake browser warmup failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="stake-warmup").start()


def _stake_odds_keepalive_loop() -> None:
    """Keep Stake odds fresh 24/7 when cloud browser is configured on this host."""
    settings = get_settings()
    interval = int(settings.stake_odds_loop_seconds or 0)
    if interval <= 0:
        return
    from bet_placer.config import remote_stake_browser_enabled, stake_network_enabled

    if not stake_network_enabled():
        logger.info("Stake odds loop skipped (no live Stake path)")
        return
    # Laptop 24/7 path is LaunchAgent / stake_relay.py — avoid a second scraper in the API.
    if not remote_stake_browser_enabled():
        logger.info(
            "Stake odds loop idle until BROWSERBASE_API_KEY / STAKE_CDP_URL "
            "(local 24/7: ./scripts/install_stake_relay_agent.sh)"
        )
        return

    def _go() -> None:
        import time

        # First pass after a short settle so warmup can finish.
        time.sleep(20)
        while True:
            try:
                from bet_placer.engine.stake_odds import refresh_stake_overlay

                out = refresh_stake_overlay()
                logger.info(
                    "Stake odds loop: fixtures=%s have_data=%s",
                    (out.get("status") or {}).get("fixtures") if isinstance(out, dict) else None,
                    (out.get("status") or {}).get("have_data") if isinstance(out, dict) else out,
                )
            except Exception:
                logger.warning("Stake odds loop tick failed", exc_info=True)
            time.sleep(max(60, interval))

    threading.Thread(target=_go, daemon=True, name="stake-odds-loop").start()
    logger.info("Stake odds keepalive every %ss (cloud browser)", interval)


def _prefetch_stake_overlay() -> None:
    """Load persisted Stake overlay from disk; skip live GraphQL on cloud (403)."""
    def _go() -> None:
        from bet_placer.config import stake_network_enabled
        try:
            from bet_placer.engine.stake_odds import warm_stake_cache_from_disk
            n = warm_stake_cache_from_disk()
            if n:
                logger.info("Stake disk cache warmed: %d fixtures", n)
        except Exception:
            logger.warning("Stake disk cache warmup failed", exc_info=True)
        if not stake_network_enabled():
            logger.info("Stake live fetch skipped (browser off — use ESPN/model prices on cloud)")
            return
        try:
            from bet_placer.data.stake_scraper import StakeScraper
            from bet_placer.engine.stake_odds import fetch_fast_stake_overlay
            m = fetch_fast_stake_overlay(StakeScraper(timeout=45, allow_browser_launch=False))
            logger.info("Stake trending overlay preloaded: %d fixtures", len(m or {}))
        except Exception:
            logger.warning("Stake trending preload failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="stake-cache-warm").start()


def _warmup_data() -> None:
    """Pre-fetch ESPN boards so sport/league switches hit cache. No Odds API credits."""
    def _go() -> None:
        try:
            from bet_placer.data.espn_leagues import fetch_espn_events
            from bet_placer.data.worldcup2026 import get_all_group_matches
            for key in ("soccer_epl", "soccer_all", "basketball_all", "cricket_all", "basketball_nba"):
                try:
                    n = len(fetch_espn_events(key))
                    logger.info("Board warmup %s: %d events (ESPN only)", key, n)
                except Exception:
                    logger.warning("Board warmup failed for %s", key, exc_info=True)
            get_all_group_matches(force_refresh=True)
            logger.info("World Cup data warmup complete")
        except Exception:
            logger.warning("World Cup data warmup failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="data-warmup").start()


def _warmup_model() -> None:
    """ponytail: do NOT auto-retrain on boot — full train takes minutes and can
    overwrite in-flight params. Boards still warm via _warmup_data; user hits
    Retrain on the Model page when they want a fresh scorecard.
    """
    def _go() -> None:
        try:
            from bet_placer.ml.params import load_params
            p = load_params(force=True)
            n_elo = len(p.get("elo") or {})
            n_sport = sum(int(v or 0) for v in (p.get("trained_on_sport_history") or {}).values())
            logger.info(
                "Model warmup skipped (elo=%d sport_history=%d). Use Model → Retrain to refresh.",
                n_elo, n_sport,
            )
        except Exception:
            logger.debug("Model warmup status check failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="model-warmup").start()


_craft_boot_lock = threading.Lock()
_craft_boot_started = False


def _ensure_craft_training() -> None:
    """Keep craft running inside the API process until ROI gates clear.

    Set CRAFT_DISABLE=1 on deploy hosts — run scripts/run_craft_worker.py on
    GitHub Actions (or another worker) instead of baking training into the API.
    """
    import os
    if os.getenv("CRAFT_DISABLE", "").strip().lower() in ("1", "true", "yes", "on"):
        logger.info("CRAFT_DISABLE set — local craft thread skipped (use cloud worker)")
        return
    global _craft_boot_started
    with _craft_boot_lock:
        if _craft_boot_started:
            return
        _craft_boot_started = True

    def _go() -> None:
        import time
        from bet_placer.ml.craft_store import get_meta, set_meta
        from bet_placer.ml.craft_train import TARGET_ACC, TARGET_ROI, train_until_roi

        while True:
            status = get_meta("train_status") or {}
            if status.get("state") == "hit_target" or (status.get("gates") or {}).get("all_ok"):
                logger.info("Craft gates already cleared — not restarting")
                return
            set_meta("train_status", {
                **status,
                "state": "running",
                "epoch": int(status.get("epoch") or 0),
                "target_roi": TARGET_ROI,
                "target_accuracy": TARGET_ACC,
                "unlimited": True,
                "owner": "api",
                "note": "holdout gates: overall≥25% · sport ROI>0 · hit≥60%",
            })
            try:
                result = train_until_roi(
                    target_roi=TARGET_ROI,
                    target_acc=TARGET_ACC,
                    max_epochs=None,
                    verbose=True,
                )
                if result.get("hit_target"):
                    logger.info("Craft hit targets — stopping auto-train loop")
                    return
            except Exception:
                logger.exception("Craft train crashed — restarting in 5s")
                set_meta("train_status", {
                    "state": "error",
                    "error": "craft crashed — restarting",
                    "owner": "api",
                })
                time.sleep(5)

    threading.Thread(target=_go, daemon=True, name="craft-until-targets").start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warmup_data()
    _prefetch_stake_overlay()
    _warmup_stake_browser()
    _stake_odds_keepalive_loop()
    _warmup_model()
    _ensure_craft_training()
    _warmup_insights()
    yield
    # Tear the browser down cleanly so we don't orphan Chrome (which would lock
    # the profile and break Stake on the next launch).
    try:
        from bet_placer.data.stake_browser import shutdown
        shutdown()
    except Exception:
        logger.debug("Stake browser shutdown skipped", exc_info=True)


app = FastAPI(title="Bet Placer API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_provider = UnifiedOddsProvider()
_engine = ProbabilityEngine()
_verdict_engine = MatchVerdictEngine()
_web = WebConsensusFetcher()


class AuthBody(BaseModel):
    email: str
    password: str
    name: str | None = None


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = _bearer_user(request)
    return {"user": user}


@app.post("/api/auth/signup")
def auth_signup(body: AuthBody):
    from bet_placer.auth.users import signup

    try:
        return signup(email=body.email, password=body.password, name=body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/login")
def auth_login(body: AuthBody):
    from bet_placer.auth.users import login

    try:
        return login(email=body.email, password=body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    from bet_placer.auth.users import logout

    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    logout(token)
    return {"ok": True}


class PortfolioPrivacyUpdate(BaseModel):
    portfolio_enabled: bool
    risk_acknowledged: bool
    learning_opt_in: bool = False


class StakeRelayPayload(BaseModel):
    secret: str
    fixtures: dict[str, dict]


class PortfolioRelayPayload(BaseModel):
    secret: str
    portfolio: dict | None = None
    privacy: dict | None = None
    connection: dict | None = None


class StakeTokenConnect(BaseModel):
    token: str


class StakeSyncJobsComplete(BaseModel):
    secret: str
    job_id: str
    bets: list[dict] | None = None
    error: str | None = None
    stake_user: dict | None = None


@app.get("/api/health")
def health():
    settings = get_settings()
    from bet_placer.config import remote_stake_browser_enabled
    from bet_placer.engine.stake_odds import stake_overlay_status
    overlay = stake_overlay_status()
    stake_status = {}
    if stake_network_enabled():
        try:
            from bet_placer.data.stake_browser import browser_status
            stake_status = {**browser_status(), "overlay": overlay}
        except Exception:
            stake_status = {"overlay": overlay}
    elif settings.stake_relay_secret or overlay.get("have_data"):
        stake_status = {"relay": bool(settings.stake_relay_secret), "overlay": overlay}
    return {
        "status": "ok",
        "odds_api_configured": bool(settings.odds_api_key),
        "stake_token_configured": bool(settings.stake_api_token),
        "stake_use_browser": settings.stake_use_browser,
        "stake_remote": remote_stake_browser_enabled(),
        "stake_relay": bool(settings.stake_relay_secret),
        "stake_live": stake_network_enabled(),
        "stake_browser": stake_status,
    }


@app.get("/api/categories")
def categories():
    return {"categories": CATEGORIES}


@app.get("/api/sports")
def sports(category: str | None = None, featured: bool = False):
    items = list_sports(category=category, featured_only=featured)
    return {
        "sports": [
            {
                "key": s.key,
                "name": s.name,
                "category": s.category,
                "featured": s.featured,
                "description": s.description,
                "model": getattr(s, "model", "generic"),
            }
            for s in items
        ]
    }


@app.get("/api/bettor-style")
def bettor_style_catalog():
    """Goals / risk / structure options for the style-aware recommender."""
    from bet_placer.engine.bettor_style import BettorStyle, style_meta
    return style_meta(BettorStyle())


@app.get("/api/market/top")
def market_top(limit: int = Query(default=8, ge=1, le=20)):
    """Market-backed selections from SkipOdds + ESPN book odds (free sources)."""
    from bet_placer.engine.market_top import market_top_bets
    return market_top_bets(limit=limit)


@app.get("/api/market/surebets")
def market_surebets(limit: int = Query(default=12, ge=1, le=40), min_roi: float = Query(default=0.01, ge=0.0, le=0.2)):
    """Cross-book locks from Odds API disk cache (no credit spend unless cache cold)."""
    from bet_placer.data.odds_api import OddsAPIClient
    from bet_placer.engine.surebets import scan_event_surebet

    client = OddsAPIClient()
    found: list[dict] = []
    if client.is_configured:
        for key in ("soccer_epl", "soccer_spain_la_liga", "basketball_nba"):
            try:
                # force=False → disk only when warm; one network fill per sport per 6h
                for ev in client.fetch_odds(key, markets="h2h", force=False) or []:
                    hit = scan_event_surebet(ev, min_roi=min_roi)
                    if hit:
                        found.append({**hit, "sport_key": key})
            except Exception:
                continue
    found.sort(key=lambda s: -float(s.get("roi") or 0))
    return {
        "surebets": found[:limit],
        "count": len(found[:limit]),
        "odds_api_configured": client.is_configured,
        "remaining": client.last_remaining,
        "note": (
            None if client.is_configured
            else "Set ODDS_API_KEY for live multi-book surebets"
        ),
    }


# Serialized board payloads — avoid re-scraping on every Home/Sport paint.
_EVENTS_RESP: dict[str, tuple[float, dict]] = {}
_EVENTS_TTL = 120.0
_EVENTS_STALE = 900.0  # serve stale boards while refresh runs (Stake-style)


@app.get("/api/events")
def events(sport: str = Query(default="soccer_epl"), match: str | None = None):
    import time as _time
    from bet_placer.data.catalog import get_sport

    cache_key = f"{sport}|{match or ''}"
    now = _time.time()
    hit = _EVENTS_RESP.get(cache_key)
    if hit and now - hit[0] < _EVENTS_TTL:
        return hit[1]

    def _build() -> dict:
        result = _provider.fetch_events(sport, match_filter=match)
        info = get_sport(sport)
        # *_all boards mix in finished games — drop them so Render/FE stay under memory
        open_only = sport.endswith("_all")
        events = []
        for e in result.events:
            if open_only and e.status not in ("live", "upcoming"):
                continue
            events.append({
                "id": e.id,
                "home_team": e.home_team,
                "away_team": e.away_team,
                "league": e.league,
                "kickoff": e.kickoff,
                "source": e.source,
                "bookmaker_count": e.bookmaker_count,
                "label": f"{e.home_team} vs {e.away_team}",
                "home_logo": e.home_logo,
                "away_logo": e.away_logo,
                "status": e.status,
                "home_score": e.home_score,
                "away_score": e.away_score,
                "home_score_display": e.home_score_display,
                "away_score_display": e.away_score_display,
                "score": e.score,
                "status_detail": e.status_detail,
                "odds": {
                    "home": e.home_odds,
                    "draw": e.draw_odds,
                    "away": e.away_odds,
                },
                "odds_source": (e.extra or {}).get("odds_source") or e.source,
                "sport_key": e.sport_key,
            })
        return {
            "sport": sport,
            "sport_name": info.name if info else sport,
            "model": info.model if info else "generic",
            "source": result.source,
            "live": result.live,
            "message": result.message,
            "events": events,
        }

    # Stale-while-revalidate: serve last good board while refresh runs
    if hit and now - hit[0] < _EVENTS_STALE:
        def _refresh() -> None:
            try:
                payload = _build()
                _EVENTS_RESP[cache_key] = (_time.time(), payload)
            except Exception:
                logger.debug("events refresh failed for %s", cache_key, exc_info=True)
        threading.Thread(target=_refresh, daemon=True, name=f"events-refresh-{sport}").start()
        return hit[1]

    payload = _build()
    _EVENTS_RESP[cache_key] = (now, payload)
    return payload


@app.post("/api/stake/relay")
def stake_relay(body: StakeRelayPayload):
    """Ingest Stake odds from scripts/stake_relay.py on your laptop (bypasses cloud 403)."""
    settings = get_settings()
    if not settings.stake_relay_secret or body.secret != settings.stake_relay_secret:
        raise HTTPException(status_code=401, detail="Invalid relay secret")
    from bet_placer.engine.stake_odds import ingest_stake_relay
    return ingest_stake_relay({"fixtures": body.fixtures})


@app.get("/api/stake/snapshot")
def stake_snapshot(secret: str = Query(...)):
    """Download current Stake overlay (relay secret). Used to backup / restore after deploys."""
    settings = get_settings()
    if not settings.stake_relay_secret or secret != settings.stake_relay_secret:
        raise HTTPException(status_code=401, detail="Invalid relay secret")
    from bet_placer.engine.stake_odds import export_stake_overlay_payload, stake_overlay_status, warm_stake_cache_from_disk
    warm_stake_cache_from_disk()
    payload = export_stake_overlay_payload()
    return {
        **payload,
        "status": stake_overlay_status(),
        "count": len(payload.get("fixtures") or {}),
    }


@app.post("/api/stake/refresh")
def stake_refresh():
    """Pull latest Stake trending locally, or return relay/disk cache on cloud."""
    from bet_placer.engine.stake_odds import refresh_stake_overlay
    result = refresh_stake_overlay()
    if result.get("skipped"):
        # Cloud: keep working on relay/disk cache + ESPN/model prices
        result["message"] = (
            "Live Stake scrape is off on this host. "
            "Using relay/cache when present, otherwise ESPN or model prices."
        )
    return result


@app.post("/api/stake/connect")
def stake_connect():
    """Warm Stake browser (local or cloud) and refresh odds overlay."""
    from bet_placer.config import stake_network_enabled
    if not stake_network_enabled():
        from bet_placer.engine.stake_odds import stake_overlay_status, warm_stake_cache_from_disk
        warm_stake_cache_from_disk()
        overlay = stake_overlay_status()
        n = overlay.get("fixtures", 0)
        return {
            "connected": False,
            "browser": {"ready": False, "cloud": True},
            "overlay": overlay,
            "fixtures": n,
            "message": (
                f"Showing {n} cached Stake prices (odds link). "
                "Account login is not available on this host — use Portfolio Confirm or scripts/stake_login.py on your Mac."
                if overlay.get("have_data")
                else "Stake prices appear once the odds feed is connected. Account login needs your Mac script or Browserbase."
            ),
        }
    from bet_placer.data.stake_browser import browser_status, warmup_visible
    from bet_placer.engine.stake_odds import refresh_stake_overlay, stake_overlay_status

    ok = warmup_visible(timeout=300)
    browser = browser_status()
    overlay_status = stake_overlay_status()
    refresh_result = None
    if ok or browser.get("ready"):
        try:
            refresh_result = refresh_stake_overlay()
            overlay_status = refresh_result.get("status") or overlay_status
        except Exception as exc:
            overlay_status = {**overlay_status, "refresh_error": str(exc)[:200]}
    return {
        "connected": bool(ok or browser.get("ready")),
        "browser": browser,
        "overlay": overlay_status,
        "fixtures": refresh_result.get("fixtures") if refresh_result else overlay_status.get("fixtures", 0),
        "message": (
            f"Stake connected — {overlay_status.get('fixtures', 0)} matches priced"
            if overlay_status.get("have_data")
            else (
                "Stake window is open — finish sign-in if asked, then Connect again."
                if not browser.get("ready")
                else "Browser ready — pulling odds failed; try Connect again in a moment."
            )
        ),
    }


@app.get("/api/portfolio")
def portfolio_state(request: Request):
    from bet_placer.portfolio.store import get_portfolio_state

    _bind_portfolio_user(request)
    return get_portfolio_state()


@app.post("/api/portfolio/stake-token")
def portfolio_stake_token(request: Request, body: StakeTokenConnect):
    """Common-user Stake connect: paste API token from Stake settings."""
    from bet_placer.portfolio.store import connect_with_stake_token

    user = _bind_portfolio_user(request)
    try:
        return connect_with_stake_token(body.token, user_id=(user or {}).get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/portfolio/sync-jobs")
def portfolio_sync_jobs(secret: str = Query(...)):
    from bet_placer.portfolio.store import list_pending_sync_jobs

    try:
        return {"jobs": list_pending_sync_jobs(secret)}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/portfolio/sync-jobs/complete")
def portfolio_sync_jobs_complete(body: StakeSyncJobsComplete):
    from bet_placer.portfolio.store import complete_sync_job

    try:
        return complete_sync_job(
            secret=body.secret,
            job_id=body.job_id,
            bets=body.bets,
            error=body.error,
            stake_user=body.stake_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/slip/record")
def slip_record(payload: dict):
    """Park bet-slip legs into the paper book so craft can learn when they settle."""
    from bet_placer.ml.slip_learn import record_slip_tickets

    legs = payload.get("legs") if isinstance(payload, dict) else None
    return record_slip_tickets(legs or [])


@app.post("/api/slip/settle")
def slip_settle(payload: dict):
    """Mark a slip ticket won/lost and blend into craft / strategy weights."""
    from bet_placer.ml.slip_learn import settle_slip_ticket

    tid = (payload or {}).get("id") or (payload or {}).get("ticket_id")
    won = bool((payload or {}).get("won"))
    sport = (payload or {}).get("sport")
    out = settle_slip_ticket(str(tid or ""), won=won, sport=sport)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("error") or "ticket_not_found")
    return out


@app.post("/api/portfolio/privacy")
def portfolio_privacy(request: Request, payload: PortfolioPrivacyUpdate):
    from bet_placer.portfolio.store import update_privacy_settings

    _bind_portfolio_user(request)
    return update_privacy_settings(
        portfolio_enabled=payload.portfolio_enabled,
        risk_acknowledged=payload.risk_acknowledged,
        learning_opt_in=payload.learning_opt_in,
    )


@app.post("/api/portfolio/connect")
def portfolio_connect(request: Request):
    from bet_placer.portfolio.store import connect_browser_session

    _bind_portfolio_user(request)
    return connect_browser_session()


@app.post("/api/portfolio/disconnect")
def portfolio_disconnect(request: Request):
    from bet_placer.portfolio.store import disconnect_browser_session

    _bind_portfolio_user(request)
    return disconnect_browser_session()


@app.post("/api/portfolio/refresh")
def portfolio_refresh(request: Request):
    from bet_placer.portfolio.store import refresh_portfolio_snapshot

    _bind_portfolio_user(request)
    try:
        return refresh_portfolio_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/portfolio/relay")
def portfolio_relay(body: PortfolioRelayPayload):
    """Ingest portfolio snapshot from scripts/stake_login.py (cloud has no Chrome)."""
    settings = get_settings()
    if not settings.stake_relay_secret or body.secret != settings.stake_relay_secret:
        raise HTTPException(status_code=401, detail="Invalid relay secret")
    from bet_placer.portfolio.store import ingest_portfolio_relay

    return ingest_portfolio_relay(
        {
            "portfolio": body.portfolio,
            "privacy": body.privacy,
            "connection": body.connection,
        }
    )


class PortfolioConfirmSlip(BaseModel):
    legs: list[dict] = []
    multi_stake: float | None = None
    multi_odds: float | None = None


class PortfolioManualBet(BaseModel):
    home: str | None = None
    away: str | None = None
    fixture_name: str | None = None
    selection: str
    market: str | None = "manual"
    odds: float | None = None
    stake: float
    result: str = "open"
    payout: float | None = None
    created_at: str | None = None
    notes: str | None = None
    id: str | None = None


class PortfolioBetResultUpdate(BaseModel):
    result: str
    payout: float | None = None


@app.post("/api/portfolio/confirm-slip")
def portfolio_confirm_slip(request: Request, body: PortfolioConfirmSlip):
    from threading import Thread

    from bet_placer.portfolio.store import confirm_slip_bets, settle_open_portfolio_bets

    _bind_portfolio_user(request)
    try:
        out = confirm_slip_bets(
            legs=body.legs,
            multi_stake=body.multi_stake,
            multi_odds=body.multi_odds,
        )
        Thread(target=settle_open_portfolio_bets, daemon=True).start()
        return out
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/portfolio/bets")
def portfolio_add_bet(request: Request, body: PortfolioManualBet):
    from bet_placer.portfolio.store import add_manual_portfolio_bet

    _bind_portfolio_user(request)
    try:
        return add_manual_portfolio_bet(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/portfolio/bets/{bet_id}/result")
def portfolio_bet_result(request: Request, bet_id: str, body: PortfolioBetResultUpdate):
    from bet_placer.portfolio.store import update_portfolio_bet_result

    _bind_portfolio_user(request)
    try:
        return update_portfolio_bet_result(bet_id, body.result, body.payout)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/worldcup")
def worldcup(
    matchday: int | None = Query(default=None, ge=0, le=9),
    event_id: str | None = None,
    budget_inr: float = Query(default=2000.0, ge=100, le=50000),
    budget_per_match_inr: float | None = Query(default=None, ge=50, le=5000),
    include_completed: bool = Query(default=False),
    force_refresh: bool = Query(default=False),
    target_cashout_inr: float | None = Query(default=None, ge=100, le=100000),
):
    from bet_placer.data.wc_stages import (
        FILTER_ALL,
        STAGE_GROUP_MD1,
        STAGE_GROUP_MD2,
        STAGE_GROUP_MD3,
        STAGE_THIRD,
    )
    from bet_placer.engine.worldcup_pipeline import analyze_worldcup
    show_all_stages = matchday in (
        None, FILTER_ALL,
        STAGE_GROUP_MD1, STAGE_GROUP_MD2, STAGE_GROUP_MD3,
        4, 5, 6, 7, 8, STAGE_THIRD,
    )
    from bet_placer.api.serializers import to_json

    return to_json(analyze_worldcup(
        matchday=matchday,
        event_id=event_id,
        budget_inr=budget_inr,
        budget_per_match_inr=budget_per_match_inr,
        target_cashout_inr=target_cashout_inr,
        include_completed=include_completed or show_all_stages,
        force_refresh=force_refresh,
    ))


@app.get("/api/worldcup/stake-odds")
def worldcup_stake_odds(
    home: str = Query(..., min_length=1, max_length=80),
    away: str = Query(..., min_length=1, max_length=80),
    budget_inr: float = Query(default=200.0, ge=50, le=5000),
):
    """On-demand exact Stake payouts for one clicked match (best-effort)."""
    from bet_placer.engine.stake_odds import get_stake_match_odds

    home, away = home.strip(), away.strip()
    if not home or not away:
        raise HTTPException(status_code=422, detail="home and away must be non-empty team names")
    return get_stake_match_odds(home, away, budget_inr)


@app.get("/api/worldcup/bet-builder")
def worldcup_bet_builder(
    home: str = Query(..., min_length=1, max_length=80),
    away: str = Query(..., min_length=1, max_length=80),
    budget_inr: float = Query(default=200.0, ge=50, le=5000),
    sport: str | None = Query(default=None),
):
    """Full annotated bet menu for one match — every field + our verdict."""
    from bet_placer.engine.bet_builder import build_bet_menu

    home, away = home.strip(), away.strip()
    if not home or not away:
        raise HTTPException(status_code=422, detail="home and away must be non-empty team names")
    return build_bet_menu(home, away, budget_inr, sport=sport)


@app.get("/api/worldcup/match-slip")
def worldcup_match_slip(
    home: str = Query(..., min_length=1, max_length=80),
    away: str = Query(..., min_length=1, max_length=80),
    budget_inr: float = Query(default=200.0, ge=50, le=5000),
    target_cashout_inr: float = Query(default=1000.0, ge=100, le=100000),
    refresh_stake: bool = Query(default=True),
    sport: str | None = Query(default=None),
    goal: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    structure: str | None = Query(default=None),
):
    """Rebuild match slip with live Stake lines and SGMs for one fixture."""
    from bet_placer.api.serializers import to_json
    from bet_placer.config import stake_network_enabled
    from bet_placer.engine.worldcup_pipeline import rebuild_match_slip_for_teams

    home, away = home.strip(), away.strip()
    # Cloud: never try Playwright — ESPN/model prices still build recs
    launch = bool(refresh_stake) and stake_network_enabled()
    try:
        slip = rebuild_match_slip_for_teams(
            home, away, budget_inr, target_cashout_inr, launch_stake=launch, sport=sport,
            goal=goal, risk=risk, structure=structure,
        )
    except Exception as exc:
        logger.warning("match-slip failed for %s vs %s: %s", home, away, exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Match slip temporarily unavailable ({type(exc).__name__}). Retry in a moment.",
        ) from exc
    if not slip:
        raise HTTPException(status_code=404, detail=f"No active fixture for {home} vs {away}")
    return to_json(slip)


@app.get("/api/worldcup/hit-target")
def worldcup_hit_target(
    home: str = Query(..., min_length=1, max_length=80),
    away: str = Query(..., min_length=1, max_length=80),
    budget_inr: float = Query(default=200.0, ge=50, le=5000),
    target_cashout_inr: float = Query(default=1000.0, ge=100, le=100000),
    goal: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    structure: str | None = Query(default=None),
    sport: str | None = Query(default=None),
):
    """Target-cashout planner — WC or league boards."""
    from bet_placer.engine.target_planner import plan_hit_target_for_match

    home, away = home.strip(), away.strip()
    if not home or not away:
        raise HTTPException(status_code=422, detail="home and away must be non-empty team names")
    return plan_hit_target_for_match(
        home, away, budget_inr, target_cashout_inr,
        goal=goal, risk=risk, structure=structure, sport=sport,
    )


@app.get("/api/model/activity")
def model_activity(limit: int = Query(default=40, ge=1, le=120)):
    """Recent model training, grading, and weight-update events."""
    from bet_placer.ml.activity_log import get_activity_log
    from bet_placer.ml.params import load_params

    params = load_params()
    rec = params.get("rec_learning") or {}
    craft = params.get("craft_learning") or {}
    return {
        "events": get_activity_log(limit),
        "learning": {
            "strategy_weights": rec.get("strategy_weights") or {},
            "leg_accuracy": rec.get("leg_accuracy"),
            "legs_graded": rec.get("legs_graded"),
            "n_games": rec.get("n_games"),
            "version": rec.get("version"),
            "updated_at": params.get("report", {}).get("updated_at"),
            "craft": craft.get("summary") or {},
            "craft_weights": craft.get("weights") or {},
        },
    }


@app.get("/api/model/paper")
def model_paper():
    """Craft progress + paper book summary (aggregates — not ticket dumps)."""
    from bet_placer.ml.craft_store import progress_snapshot
    from bet_placer.ml.paper_book import load_book, summarize
    from bet_placer.ml.params import load_params

    book = load_book()
    summary = summarize(book)
    progress = progress_snapshot()
    return {
        "summary": summary,
        "progress": progress,
        "craft_learning": (load_params().get("craft_learning") or {}),
    }


@app.post("/api/model/paper/cycle")
def model_paper_cycle(
    train_walkforward: bool = Query(default=True),
    place_live: bool = Query(default=True),
    bankroll: float = Query(default=10_000, ge=500, le=1_000_000),
    match_budget: float = Query(default=200, ge=50, le=50_000),
    max_games: int = Query(default=60, ge=5, le=300),
    full_slip: bool = Query(default=False),
    until_roi: bool = Query(default=False),
    target_roi: float = Query(default=0.25, ge=0.05, le=1.0),
    target_acc: float = Query(default=0.60, ge=0.45, le=0.95),
    max_epochs: int = Query(default=0, ge=0, le=10000),
):
    """Run paper craft. until_roi=true starts unlimited craft in background until gates clear.

    max_epochs=0 means unlimited (does not stop until targets hit).
    """
    if until_roi:
        import threading
        from bet_placer.ml.craft_store import get_meta, set_meta
        from bet_placer.ml.craft_train import train_until_roi

        status = get_meta("train_status") or {}
        gates = status.get("gates") or {}
        stale_gates = status.get("state") == "running" and "monthly" not in gates
        if status.get("state") == "running" and not stale_gates:
            return {
                "started": False,
                "already_running": True,
                "train_status": status,
                "message": "Craft already running — watch Model insights / craft status",
            }
        if stale_gates:
            set_meta("train_status", {
                **status,
                "state": "superseded",
                "note": "restarting with monthly+positive-sport gates",
            })

        set_meta("train_status", {
            "state": "running",
            "epoch": 0,
            "target_roi": target_roi,
            "target_accuracy": target_acc,
            "unlimited": max_epochs <= 0,
            "owner": "api",
        })

        def _bg() -> None:
            try:
                train_until_roi(
                    target_roi=target_roi,
                    target_acc=target_acc,
                    max_epochs=None if max_epochs <= 0 else max_epochs,
                    bankroll=bankroll,
                    match_budget=match_budget,
                    verbose=True,
                )
            except Exception as exc:
                set_meta("train_status", {
                    "state": "error",
                    "error": str(exc),
                    "target_roi": target_roi,
                    "target_accuracy": target_acc,
                    "owner": "api",
                })

        threading.Thread(target=_bg, daemon=True, name="craft-until-targets").start()
        return {
            "started": True,
            "already_running": False,
            "train_status": get_meta("train_status"),
            "message": "Craft training started in background — does not stop until ROI+accuracy gates clear",
        }
    from bet_placer.ml.paper_book import run_cycle

    return run_cycle(
        train_walkforward=train_walkforward,
        bankroll=bankroll,
        match_budget=match_budget,
        max_games=max_games,
        place_live=place_live,
        full_slip=full_slip,
        verbose=False,
    )


@app.get("/api/model/craft")
def model_craft():
    """Overall craft training progress for the Model page visuals."""
    from bet_placer.ml.craft_store import progress_snapshot
    return progress_snapshot()


@app.get("/api/model/craft-progress")
def model_craft_progress_alias():
    """Alias for older frontend builds that hit /craft-progress."""
    return model_craft()


_INSIGHTS_CACHE: tuple[float, dict] | None = None
_INSIGHTS_TTL = 120.0


@app.get("/api/model/insights")
def model_insights():
    """Dashboard payload: corpus, 3-sport accuracy, learning/craft curves — no match dumps."""
    import time as _time
    from bet_placer.ml.model_insights import (
        build_model_insights,
        craft_fallback_desk,
        load_insights_cache,
        save_insights_cache,
    )

    global _INSIGHTS_CACHE
    now = _time.time()
    if _INSIGHTS_CACHE and now - _INSIGHTS_CACHE[0] < _INSIGHTS_TTL:
        return _INSIGHTS_CACHE[1]

    # Disk cache — instant paint on Render (avoids 502 while full build runs)
    disk = load_insights_cache(max_age_s=6 * 3600)
    if disk and (disk.get("containers") or disk.get("curves")):
        _INSIGHTS_CACHE = (now, disk)
        _schedule_insights_refresh()
        return disk

    # Fast craft+evolution desk so graphs never stay blank
    try:
        fallback = craft_fallback_desk()
        if fallback.get("containers"):
            _INSIGHTS_CACHE = (now, fallback)
            try:
                save_insights_cache(fallback)
            except Exception:
                pass
            _schedule_insights_refresh()
            return fallback
    except Exception as exc:
        logger.warning("craft fallback desk failed: %s", exc)

    try:
        payload = build_model_insights()
        _INSIGHTS_CACHE = (now, payload)
        return payload
    except Exception as exc:
        logger.warning("model insights failed: %s", exc)
        return craft_fallback_desk("Model desk warming — craft charts only.")


_INSIGHTS_REFRESHING = False


def _schedule_insights_refresh() -> None:
    """Background full rebuild — never blocks HTTP."""
    global _INSIGHTS_REFRESHING, _INSIGHTS_CACHE
    if _INSIGHTS_REFRESHING:
        return
    _INSIGHTS_REFRESHING = True

    def _go() -> None:
        global _INSIGHTS_REFRESHING, _INSIGHTS_CACHE
        import time as _time
        try:
            from bet_placer.ml.model_insights import build_model_insights
            payload = build_model_insights()
            _INSIGHTS_CACHE = (_time.time(), payload)
            logger.info("model insights refreshed (%d containers)", len(payload.get("containers") or []))
        except Exception:
            logger.warning("background insights refresh failed", exc_info=True)
        finally:
            _INSIGHTS_REFRESHING = False

    threading.Thread(target=_go, daemon=True, name="insights-refresh").start()


def _warmup_insights() -> None:
    def _go() -> None:
        try:
            from bet_placer.ml.model_insights import (
                build_model_insights,
                craft_fallback_desk,
                load_insights_cache,
                save_insights_cache,
            )
            import time as _time
            global _INSIGHTS_CACHE
            hit = load_insights_cache(max_age_s=6 * 3600)
            if hit:
                _INSIGHTS_CACHE = (_time.time(), hit)
            else:
                fb = craft_fallback_desk()
                save_insights_cache(fb)
                _INSIGHTS_CACHE = (_time.time(), fb)
            _schedule_insights_refresh()
        except Exception:
            logger.warning("insights warmup failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="insights-warmup").start()


@app.get("/api/model/report")
def model_report(retrain: bool = Query(default=False)):
    """The model's self-graded report card: accuracy, calibration, what it got
    wrong, and the corrections it has learned from real results."""
    from bet_placer.ml.tracker import get_report
    return get_report(retrain=retrain)


@app.get("/api/model/scorecard")
def model_scorecard(refresh: bool = Query(default=False)):
    """Live scorecard: how the model has called every finished World Cup game,
    its accuracy trend by matchday, confidence-tier hit rates, and how it stacks
    up against simply backing the bookmaker's favourite."""
    from bet_placer.ml.tracker import worldcup_scorecard
    return worldcup_scorecard(refresh_recommendations=refresh)


def _in_analyze_window(match, *, days: int = 3) -> bool:
    """Live + kickoff within today..+days. Unknown kickoff kept only if live."""
    from datetime import datetime, timedelta, timezone

    status = str(getattr(match, "status", "") or "").lower()
    if status == "live":
        return True
    ko = getattr(match, "kickoff", None)
    if ko is None:
        return False
    if ko.tzinfo is None:
        ko = ko.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    end = (now + timedelta(days=days)).replace(hour=23, minute=59, second=59, microsecond=999999)
    return (now - timedelta(hours=4)) <= ko <= end


def _pad_analyze_window(matches: list, *, days: int = 3, min_upcoming: int = 10) -> list:
    """Prefer live + next N days; if thin, pad with soonest upcoming to min_upcoming."""
    from datetime import datetime, timezone

    live = [m for m in matches if str(getattr(m, "status", "") or "").lower() == "live"]
    upcoming = sorted(
        [m for m in matches if str(getattr(m, "status", "") or "").lower() != "live"],
        key=lambda m: getattr(m, "kickoff", None) or datetime.max.replace(tzinfo=timezone.utc),
    )
    in_win = [m for m in upcoming if _in_analyze_window(m, days=days)]
    if len(in_win) < min_upcoming:
        in_win = upcoming[: max(min_upcoming, len(in_win))]
    return live + in_win


def _human_pick(match, market, selection, line=None) -> tuple[str, str]:
    """Stake-style labels — never expose raw enums like match_winner:home."""
    from bet_placer.markets.labels import format_market_label, market_category

    label = format_market_label(market, selection, line, match.home_team, match.away_team)
    cat = market_category(market)
    return label, cat


def _user_reasons(reasoning: list[str] | None, limit: int = 3) -> list[str]:
    """Need-to-know copy only — strip threshold / style jargon."""
    skip = (
        "style=", "+EV floor", "win% ≥", "confidence ≥", "Scanned ",
        "min_ev", "true_prob", "filtered ", "Stake markets",
    )
    out = []
    seen = set()
    for line in reasoning or []:
        if any(s in line for s in skip):
            continue
        key = line.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out[:limit]


def _annotate_pick(b: dict) -> dict:
    """Add model vs book % for UI — denser, not longer."""
    odds = float(b.get("decimal_odds") or b.get("odds") or 0)
    prob = b.get("true_probability")
    if prob is None:
        return b
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return b
    model_pct = round(p * 100)
    book_pct = round((1 / odds) * 100) if odds > 1 else None
    b["model_pct"] = model_pct
    if book_pct is not None:
        b["book_pct"] = book_pct
        edge = model_pct - book_pct
        b["edge_pct"] = edge
        if not b.get("explanation"):
            tag = "lean" if b.get("is_lean") else "edge"
            b["explanation"] = f"Model {model_pct}% vs book ~{book_pct}% ({edge:+d}pt {tag})"
    return b


def _market_leans(match, analysis, bankroll: float, limit: int = 2) -> list[dict]:
    """When no +EV clears, surface highest-prob priced sides as leans (honest, not fake edge)."""
    from bet_placer.engine.ev import compute_ev, _find_matching_odds

    leans: list[dict] = []
    ranked = sorted(
        analysis.probabilities or [],
        key=lambda p: (p.probability, p.confidence),
        reverse=True,
    )
    for p in ranked:
        market = p.market.value if hasattr(p.market, "value") else str(p.market)
        # Prefer result / totals / handicap — sport-sensible leans first
        if market not in (
            "match_winner", "draw_no_bet", "double_chance",
            "over_under_goals", "asian_handicap", "btts",
        ):
            continue
        odds = _find_matching_odds(match.market_odds or [], p)
        if not odds or odds.best_odds <= 1.01:
            continue
        if p.probability < 0.40:
            continue
        # Don't lead with huge underdog handicaps as the "best lean"
        if market == "asian_handicap" and p.probability < 0.52:
            continue
        ev = compute_ev(p.probability, odds.best_odds)
        rec = recommend_match_stake(
            p.probability, odds.best_odds, p.confidence, 0.55, bankroll,
        )
        label, market_name = _human_pick(match, market, p.selection, p.line)
        book_pct = round((1 / odds.best_odds) * 100)
        model_pct = round(p.probability * 100)
        leans.append(_annotate_pick({
            "match_id": match.id,
            "match_label": f"{match.home_team} vs {match.away_team}",
            "home_team": match.home_team,
            "away_team": match.away_team,
            "market": market,
            "market_name": market_name,
            "selection": p.selection,
            "line": p.line,
            "label": label,
            "decimal_odds": odds.best_odds,
            "true_probability": p.probability,
            "expected_value": ev,
            "confidence": p.confidence,
            "rank_score": p.probability + (0.08 if market == "match_winner" else 0),
            "is_lean": True,
            "explanation": (
                f"Best lean @ {odds.best_odds:.2f} — model {model_pct}% vs book ~{book_pct}%. "
                "Not a clear edge."
            ),
            "stake_recommendation": {
                "recommended_stake": rec.recommended_stake,
                "recommended_pct": rec.recommended_pct,
                "risk_level": "lean",
                "plain_english": "Lean only — size small.",
                "expected_profit": rec.expected_profit,
                "break_even_probability": rec.break_even_probability,
            },
        }))
        if len(leans) >= limit:
            break
    leans.sort(key=lambda x: float(x.get("rank_score") or 0), reverse=True)
    return leans[:limit]


@app.get("/api/analyze")
def analyze(
    sport: str = Query(default="soccer_epl"),
    match: str | None = None,
    event_id: str | None = None,
    bankroll: float = Query(default=200.0, ge=10, le=1_000_000),
    goal: str = Query(default="value"),
    risk: str = Query(default="medium"),
    structure: str = Query(default="spread"),
    target_cashout_inr: float | None = Query(default=None),
):
    """Analyze live + next-3-day fixtures only (pad ≥10 upcoming). Style-curated."""
    from bet_placer.data.catalog import get_sport
    from bet_placer.engine.bettor_style import BettorStyle, curate_bets, style_meta

    settings = get_settings()
    style = BettorStyle.from_dict({
        "goal": goal,
        "risk": risk,
        "structure": structure,
        "budget_inr": bankroll,
        "target_cashout_inr": target_cashout_inr,
    })
    fetch = _provider.fetch_events(sport, match_filter=match)
    matches = fetch.matches
    if event_id:
        matches = [m for m in matches if m.id == event_id]
    else:
        # ponytail: board scrapes hundreds; only price slips for the betting window
        matches = _pad_analyze_window(matches, days=3, min_upcoming=10)

    # Skip Stake browser + Reddit on the hot path (India geo-block / 12s timeouts).
    # Stake connect is a separate user action; overlay disk cache still applies elsewhere.
    info = get_sport(sport)
    results = []
    for m in matches:
        analysis = _engine.analyze_match(m)
        bettor = None
        from bet_placer.models.stake_types import WebConsensus
        web = WebConsensus(
            fixture_name=f"{m.home_team} vs {m.away_team}",
            home_pick_pct=0.0,
            draw_pick_pct=0.0,
            away_pick_pct=0.0,
            over_25_pct=0.0,
            btts_yes_pct=0.0,
            source_count=0,
            confidence=0.0,
            dominant_narrative="",
        )
        markets_scanned = len(m.market_odds)
        verdict = _verdict_engine.evaluate(analysis, bettor, web, markets_scanned)

        enriched_bets = []
        for bet in analysis.value_bets:
            rec = recommend_match_stake(
                bet.true_probability, bet.decimal_odds,
                bet.confidence, bet.risk_score, bankroll,
            )
            b = serialize_value_bet(bet)
            label, market_name = _human_pick(m, b["market"], b["selection"], b.get("line"))
            b["label"] = label
            b["market_name"] = market_name
            b["home_team"] = m.home_team
            b["away_team"] = m.away_team
            b["stake_recommendation"] = {
                "recommended_stake": rec.recommended_stake,
                "recommended_pct": rec.recommended_pct,
                "risk_level": rec.risk_level,
                "plain_english": rec.plain_english,
                "expected_profit": rec.expected_profit,
                "break_even_probability": rec.break_even_probability,
            }
            enriched_bets.append(_annotate_pick(b))

        curated = curate_bets(enriched_bets, style)
        leans: list[dict] = []
        if not curated:
            leans = _market_leans(m, analysis, bankroll, limit=3)
            if leans and verdict.verdict.value in ("skip", "caution"):
                from bet_placer.models.stake_types import Verdict
                top_lean = leans[0]
                if verdict.verdict.value == "skip":
                    verdict.verdict = Verdict.CAUTION
                    verdict.headline = f"CAUTION — {top_lean.get('label') or 'soft lean'}"
                verdict.reasoning = [
                    top_lean.get("explanation") or "Best available lean from the model.",
                    *list(verdict.reasoning or [])[:2],
                ]
                if web and web.dominant_narrative:
                    verdict.reasoning.append(web.dominant_narrative)
                if bettor and bettor.notes:
                    verdict.reasoning.extend(bettor.notes[:1])

        suggested = [_annotate_pick(p) for p in (curated or leans)][:3]
        # Never return an analyzed match with zero picks — always at least model leans.
        if not suggested:
            leans = _market_leans(m, analysis, bankroll, limit=2)
            suggested = [_annotate_pick(p) for p in leans][:2]
            if suggested and verdict.verdict.value == "skip":
                from bet_placer.models.stake_types import Verdict
                verdict.verdict = Verdict.CAUTION
                verdict.headline = f"CAUTION — {suggested[0].get('label') or 'model lean'}"

        bet_slip = None
        if event_id:
            try:
                from bet_placer.engine.match_slip import build_match_slip, serialize_slip

                human_ctx = {
                    "fan_take": (web.dominant_narrative if web else None),
                    "analyst_read": {"summary": (verdict.reasoning or [None])[0]},
                    "stake_priced": False,
                    "target_cashout_inr": target_cashout_inr,
                    "betting_style": style.to_engine_betting_style(),
                    "sport": sport,
                }
                if bettor:
                    human_ctx["bettor_notes"] = list(bettor.notes or [])[:3]
                slip = build_match_slip(
                    m.id,
                    f"{m.home_team} vs {m.away_team}",
                    m.home_team,
                    m.away_team,
                    m,
                    analysis.probabilities,
                    bankroll,
                    human_ctx,
                    {"verdict": verdict.verdict.value},
                )
                bet_slip = serialize_slip(slip)
                if bet_slip.get("recommended_singles") and not curated:
                    slip_picks = []
                    for leg in bet_slip["recommended_singles"][: style.max_picks()]:
                        odds = leg.get("decimal_odds") or leg.get("odds") or 0
                        if odds <= 1:
                            continue
                        market = leg.get("market") or leg.get("market_key") or "match_winner"
                        selection = leg.get("selection") or "home"
                        label, market_name = _human_pick(m, market, selection, leg.get("line"))
                        raw_label = (leg.get("label") or "").strip()
                        if raw_label and ":" not in raw_label and not raw_label.startswith("match_"):
                            label = raw_label
                        slip_picks.append(_annotate_pick({
                            "match_id": m.id,
                            "home_team": m.home_team,
                            "away_team": m.away_team,
                            "label": label,
                            "market": market,
                            "market_name": market_name,
                            "selection": selection,
                            "line": leg.get("line"),
                            "decimal_odds": odds,
                            "true_probability": leg.get("true_probability") or leg.get("prob"),
                            "stake_recommendation": {
                                "recommended_stake": leg.get("stake_inr") or 0,
                            },
                            "from_slip": True,
                        }))
                    if slip_picks:
                        suggested = slip_picks[:3]
            except Exception:
                logger.warning("match_slip build failed for %s", m.id, exc_info=True)

        if suggested:
            total = sum(
                float((p.get("stake_recommendation") or {}).get("recommended_stake") or p.get("stake_inr") or 0)
                for p in suggested
            )
            if total <= 0 or total > bankroll * 1.05:
                suggested = allocate_match_budget(suggested, bankroll, style=style)

        n = len(suggested)
        spent = sum(float((p.get("stake_recommendation") or {}).get("recommended_stake") or 0) for p in suggested)
        style_note = (
            f"{style.summary()} · {n} pick{'s' if n != 1 else ''} from your ₹{bankroll:.0f} match budget"
            + (f" (≈₹{spent:.0f} total)." if n else ".")
            + (" Soft lean — prices look fair." if leans and not curated else "")
        )

        v_payload = _serialize_verdict(verdict)
        v_payload["reasoning"] = _user_reasons(v_payload.get("reasoning"))

        item = {
            "fixture_id": m.id,
            "name": f"{m.home_team} vs {m.away_team}",
            "home_team": m.home_team,
            "away_team": m.away_team,
            "league": m.league,
            "kickoff": m.kickoff.isoformat() if m.kickoff else None,
            "source": fetch.source,
            "model": info.model if info else "generic",
            "stake_volume": 0,
            "stake_users": 0,
            "verdict": v_payload,
            "bettor_consensus": _to_dict(bettor) if bettor else None,
            "web_consensus": _to_dict(web),
            "markets": _serialize_markets(m),
            "probabilities": [_to_dict(p) for p in analysis.probabilities],
            "value_bets": enriched_bets,
            "suggested_bets": suggested,
            "top_bets": suggested,
            "bet_slip": bet_slip,
            "match_budget_inr": bankroll,
            "style_note": style_note,
            "team_stats": {
                "home": _serialize_team_stats(m.home_stats),
                "away": _serialize_team_stats(m.away_stats),
            },
        }
        results.append(item)

    top = []
    for r in results:
        top.extend(r["suggested_bets"])
    top.sort(key=lambda b: b.get("rank_score", 0) or 0, reverse=True)

    return {
        "sport": sport,
        "sport_name": info.name if info else sport,
        "model": info.model if info else "generic",
        "from_live": fetch.live,
        "source": fetch.source,
        "message": fetch.message,
        "match_count": len(results),
        "analyze_window": "live + next 3 days (min 10 upcoming)",
        "matches": results,
        "top_bets": top[:20],
        "bankroll": bankroll,
        "bettor_style": style_meta(style),
        "disclaimer": (
            "This is analytical software, not financial advice. "
            "Never bet more than you can afford to lose. "
            f"We cap recommended stakes at {settings.max_stake_pct}% of bankroll."
        ),
    }



def _serialize_verdict(v):
    return {
        "verdict": v.verdict.value,
        "headline": v.headline,
        "reasoning": v.reasoning,
        "best_bet": v.best_bet,
        "consensus_alignment": v.consensus_alignment,
        "value_bets_found": v.value_bets_found,
        "risk_flags": v.risk_flags,
    }


def _serialize_team_stats(ts) -> dict | None:
    if ts is None:
        return None
    form = "".join(ts.form_last_5 or []) or None
    return {
        "xg": round(float(ts.xg or 0), 2),
        "xga": round(float(ts.xga or 0), 2),
        "goals_for": round(float(ts.goals_scored or 0), 2),
        "goals_against": round(float(ts.goals_conceded or 0), 2),
        "form": form,
        "position": int(ts.league_position) if ts.league_position else None,
        "possession": round(float(ts.possession or 0), 1) or None,
    }


def _serialize_markets(m):
    from bet_placer.markets.odds import decimal_to_implied
    out = []
    for o in m.market_odds:
        fair = o.implied_probability
        out.append({
            "market": o.market.value,
            "selection": o.selection,
            "line": o.line,
            "odds": o.best_odds,
            "implied": fair,
            "bookmakers": o.bookmaker_count,
        })
    return out


def _to_dict(obj):
    if obj is None:
        return None
    from bet_placer.api.serializers import to_json
    return to_json(obj)


def _mount_frontend(application: FastAPI) -> None:
    """Serve built Vite app from GAMBIT_FRONTEND_DIST (production / VM deploy)."""
    import os
    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    raw = os.getenv("GAMBIT_FRONTEND_DIST", "").strip()
    if raw:
        dist = Path(raw)
    else:
        dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if not dist.is_dir():
        return
    for sub in ("assets", "banners", "logos"):
        p = dist / sub
        if p.is_dir():
            application.mount(f"/{sub}", StaticFiles(directory=str(p)), name=f"static_{sub}")

    @application.get("/{spa_path:path}")
    def spa_fallback(spa_path: str):
        if spa_path.startswith("api") or spa_path.startswith("docs") or spa_path.startswith("openapi"):
            raise HTTPException(status_code=404, detail="Not found")
        if spa_path:
            candidate = dist / spa_path
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_frontend(app)


def run_server(host: str = "127.0.0.1", port: int = 8000):
    import os
    import uvicorn

    host = os.getenv("GAMBIT_HOST", host)
    port = int(os.getenv("GAMBIT_PORT", str(port)))
    # reload=True restarts the API on file changes and tears down the Stake
    # browser mid-login — set BET_PLACER_RELOAD=1 only when you want hot reload.
    reload = os.environ.get("BET_PLACER_RELOAD", "").strip().lower() in ("1", "true", "yes")
    uvicorn.run("bet_placer.api.server:app", host=host, port=port, reload=reload)
