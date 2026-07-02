"""Expanded FastAPI for sellable product."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from bet_placer.api.serializers import serialize_match_result, serialize_pipeline_results, serialize_value_bet
from bet_placer.config import get_settings
from bet_placer.consensus.bettors import analyze_bettor_consensus
from bet_placer.consensus.web import WebConsensusFetcher
from bet_placer.data.catalog import CATEGORIES, list_sports
from bet_placer.data.providers import UnifiedOddsProvider
from bet_placer.data.stake_cache import fetch_or_cache
from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.engine.bankroll import recommend_stake
from bet_placer.engine.probability import ProbabilityEngine, rank_all_bets
from bet_placer.engine.verdict import MatchVerdictEngine

logger = logging.getLogger(__name__)


def _warmup_stake_browser() -> None:
    """Optionally pre-launch Playwright Chromium (off by default).

    Non-blocking and failure-tolerant: a warmup failure must never stop the
    server — requests fall back to DraftKings pricing until Stake is opened.
    """
    settings = get_settings()
    if not settings.stake_use_browser:
        logger.info("Stake browser warmup skipped (stake_use_browser=False)")
        return
    if not settings.stake_browser_warmup_on_startup:
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


def _prefetch_stake_overlay() -> None:
    """One background fetch of Stake WC odds — does not block page loads."""
    settings = get_settings()
    if not settings.stake_use_browser:
        return

    def _go() -> None:
        try:
            from bet_placer.engine.stake_odds import refresh_stake_overlay

            result = refresh_stake_overlay()
            logger.info("Stake overlay prefetch: %d fixtures", result.get("fixtures", 0))
        except Exception:
            logger.warning("Stake overlay prefetch failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="stake-overlay-prefetch").start()


def _warmup_data() -> None:
    """Pre-fetch the ESPN fixtures/odds so the first page load is instant."""
    def _go() -> None:
        try:
            from bet_placer.data.worldcup2026 import get_all_group_matches
            get_all_group_matches(force_refresh=True)
            logger.info("World Cup data warmup complete")
        except Exception:
            logger.warning("World Cup data warmup failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="data-warmup").start()


def _warmup_model() -> None:
    """Train the model from history + finished matches in the background.

    Retrains when there's no report, when the saved report predates the Elo
    learner, or when it's older than 12h (so fresh results get folded in).
    """
    def _go() -> None:
        try:
            from datetime import datetime, timezone
            from bet_placer.ml.params import load_params
            from bet_placer.ml.tracker import train
            rep = load_params().get("report") or {}
            stale = True
            if rep and "trained_on_history" in rep:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(rep["updated_at"])
                    stale = age.total_seconds() > 12 * 3600
                except Exception:
                    stale = True
            if stale:
                train()
                logger.info("Model training complete (history + World Cup)")
        except Exception:
            logger.warning("Model training failed", exc_info=True)

    threading.Thread(target=_go, daemon=True, name="model-train").start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warmup_data()
    _prefetch_stake_overlay()
    _warmup_stake_browser()
    _warmup_model()
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


class PortfolioPrivacyUpdate(BaseModel):
    portfolio_enabled: bool
    risk_acknowledged: bool
    learning_opt_in: bool = False


@app.get("/api/health")
def health():
    settings = get_settings()
    stake_status = {}
    if settings.stake_use_browser:
        from bet_placer.data.stake_browser import browser_status
        from bet_placer.engine.stake_odds import stake_overlay_status
        stake_status = {**browser_status(), "overlay": stake_overlay_status()}
    return {
        "status": "ok",
        "odds_api_configured": bool(settings.odds_api_key),
        "stake_token_configured": bool(settings.stake_api_token),
        "stake_use_browser": settings.stake_use_browser,
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
            {"key": s.key, "name": s.name, "category": s.category, "icon": s.icon,
             "featured": s.featured, "description": s.description}
            for s in items
        ]
    }


@app.get("/api/events")
def events(sport: str = Query(default="soccer_fifa_world_cup"), match: str | None = None):
    result = _provider.fetch_events(sport, match_filter=match)
    return {
        "sport": sport,
        "source": result.source,
        "live": result.live,
        "message": result.message,
        "events": [
            {
                "id": e.id,
                "home_team": e.home_team,
                "away_team": e.away_team,
                "league": e.league,
                "kickoff": e.kickoff,
                "source": e.source,
                "bookmaker_count": e.bookmaker_count,
                "label": f"{e.home_team} vs {e.away_team}",
            }
            for e in result.events
        ],
    }


@app.post("/api/stake/refresh")
def stake_refresh():
    """Pull latest WC fixtures from Stake trending (fast, non-blocking)."""
    from bet_placer.engine.stake_odds import refresh_stake_overlay
    return refresh_stake_overlay()


@app.get("/api/portfolio")
def portfolio_state():
    from bet_placer.portfolio.store import get_portfolio_state

    return get_portfolio_state()


@app.post("/api/portfolio/privacy")
def portfolio_privacy(payload: PortfolioPrivacyUpdate):
    from bet_placer.portfolio.store import update_privacy_settings

    return update_privacy_settings(
        portfolio_enabled=payload.portfolio_enabled,
        risk_acknowledged=payload.risk_acknowledged,
        learning_opt_in=payload.learning_opt_in,
    )


@app.post("/api/portfolio/connect")
def portfolio_connect():
    from bet_placer.portfolio.store import connect_browser_session

    return connect_browser_session()


@app.post("/api/portfolio/disconnect")
def portfolio_disconnect():
    from bet_placer.portfolio.store import disconnect_browser_session

    return disconnect_browser_session()


@app.post("/api/portfolio/refresh")
def portfolio_refresh():
    from bet_placer.portfolio.store import refresh_portfolio_snapshot

    try:
        return refresh_portfolio_snapshot()
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
    return analyze_worldcup(
        matchday=matchday,
        event_id=event_id,
        budget_inr=budget_inr,
        budget_per_match_inr=budget_per_match_inr,
        include_completed=include_completed or show_all_stages,
        force_refresh=force_refresh,
    )


@app.get("/api/worldcup/stake-odds")
def worldcup_stake_odds(
    home: str = Query(..., min_length=1, max_length=80),
    away: str = Query(..., min_length=1, max_length=80),
    budget_inr: float = Query(default=300.0, ge=50, le=5000),
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
    budget_inr: float = Query(default=300.0, ge=50, le=5000),
):
    """Full annotated bet menu for one match — every field + our verdict."""
    from bet_placer.engine.bet_builder import build_bet_menu

    home, away = home.strip(), away.strip()
    if not home or not away:
        raise HTTPException(status_code=422, detail="home and away must be non-empty team names")
    return build_bet_menu(home, away, budget_inr)


@app.get("/api/model/report")
def model_report(retrain: bool = Query(default=False)):
    """The model's self-graded report card: accuracy, calibration, what it got
    wrong, and the corrections it has learned from real results."""
    from bet_placer.ml.tracker import get_report
    return get_report(retrain=retrain)


@app.get("/api/model/scorecard")
def model_scorecard():
    """Live scorecard: how the model has called every finished World Cup game,
    its accuracy trend by matchday, confidence-tier hit rates, and how it stacks
    up against simply backing the bookmaker's favourite."""
    from bet_placer.ml.tracker import worldcup_scorecard
    return worldcup_scorecard()


@app.get("/api/analyze")
def analyze(
    sport: str = Query(default="soccer_fifa_world_cup"),
    match: str | None = None,
    event_id: str | None = None,
    bankroll: float = Query(default=1000.0, ge=10, le=1_000_000),
):
    settings = get_settings()
    fetch = _provider.fetch_events(sport, match_filter=match)
    matches = fetch.matches
    if event_id:
        matches = [m for m in matches if m.id == event_id]

    # Stake bettor feed when available
    live_bets, hr_bets = [], []
    try:
        scraper = StakeScraper()
        _, live_bets, hr_bets, _ = fetch_or_cache(scraper)
    except Exception:
        # Stake bettor feed is optional context; analysis proceeds without it.
        logger.warning("Stake bettor feed unavailable for /api/analyze", exc_info=True)

    results = []
    for m in matches:
        analysis = _engine.analyze_match(m)
        bettor = None
        if fetch.source == "stake" or live_bets:
            from bet_placer.data.stake_cache import get_cached_fixtures
            fixture = next((f for f in get_cached_fixtures() if m.home_team in f.home_team), None)
            if fixture:
                bettor = analyze_bettor_consensus(fixture, live_bets, hr_bets)
        web = _web.fetch(m.home_team, m.away_team, m.league)
        markets_scanned = len(m.market_odds)
        verdict = _verdict_engine.evaluate(analysis, bettor, web, markets_scanned)

        # Add bankroll recommendations to each value bet
        enriched_bets = []
        for bet in analysis.value_bets:
            rec = recommend_stake(
                bet.true_probability, bet.decimal_odds,
                bet.confidence, bet.risk_score, bankroll,
            )
            b = serialize_value_bet(bet)
            b["stake_recommendation"] = {
                "recommended_stake": rec.recommended_stake,
                "recommended_pct": rec.recommended_pct,
                "risk_level": rec.risk_level,
                "plain_english": rec.plain_english,
                "expected_profit": rec.expected_profit,
                "break_even_probability": rec.break_even_probability,
            }
            enriched_bets.append(b)

        item = {
            "fixture_id": m.id,
            "name": f"{m.home_team} vs {m.away_team}",
            "home_team": m.home_team,
            "away_team": m.away_team,
            "league": m.league,
            "kickoff": m.kickoff.isoformat() if m.kickoff else None,
            "source": fetch.source,
            "stake_volume": 0,
            "stake_users": 0,
            "verdict": _serialize_verdict(verdict),
            "bettor_consensus": _to_dict(bettor) if bettor else None,
            "web_consensus": _to_dict(web),
            "markets": _serialize_markets(m),
            "probabilities": [_to_dict(p) for p in analysis.probabilities],
            "value_bets": enriched_bets,
            "top_bets": enriched_bets[:10],
        }
        results.append(item)

    top = []
    for r in results:
        top.extend(r["top_bets"])
    top.sort(key=lambda b: b.get("rank_score", 0), reverse=True)

    return {
        "sport": sport,
        "from_live": fetch.live,
        "source": fetch.source,
        "message": fetch.message,
        "match_count": len(results),
        "matches": results,
        "top_bets": top[:20],
        "bankroll": bankroll,
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


def run_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run("bet_placer.api.server:app", host=host, port=port, reload=True)
