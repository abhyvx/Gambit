import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Built-in relay token (Render + laptop share this; no manual secret setup)
DEFAULT_STAKE_RELAY_SECRET = "gambit-relay-v1-abhyvx"


def bet_placer_home() -> Path:
    """Durable data dir. Render sets BET_PLACER_HOME=/var/lib/bet_placer; local uses ~/.bet_placer."""
    raw = (os.environ.get("BET_PLACER_HOME") or "").strip()
    p = Path(raw).expanduser() if raw else (Path.home() / ".bet_placer")
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_path(*parts: str) -> Path:
    return bet_placer_home().joinpath(*parts)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_football_key: str = ""
    odds_api_key: str = ""
    openweather_api_key: str = ""
    news_api_key: str = ""

    # Stake.com GraphQL (optional token for authenticated endpoints)
    stake_api_token: str = ""
    stake_graphql_endpoint: str = "https://stake.com/_api/graphql"
    # Fetch Stake through a real browser (Playwright) to pass Cloudflare.
    # Default off — cloud/datacenter IPs get 403 from stake.com/_api/graphql.
    # Local dev: STAKE_USE_BROWSER=true in .env
    stake_use_browser: bool = False
    # Run Chromium without a visible window (STAKE_BROWSER_HEADLESS=0 for headful).
    # Once the persistent profile has solved Cloudflare once, headless reuse works.
    stake_browser_headless: bool = True
    # Open Chromium on API startup. Default off — browser launches on first
    # explicit Stake odds / bet-builder request instead (avoids popup spam).
    stake_browser_warmup_on_startup: bool = False
    stake_relay_secret: str = DEFAULT_STAKE_RELAY_SECRET
    # Cloud Chrome (Browserbase) — 24/7 odds + portfolio login without a laptop.
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""
    # Raw CDP websocket (any remote Chrome). Overrides Browserbase when set.
    stake_cdp_url: str = ""
    # Background odds scrape interval when a live browser path is available (0=off).
    stake_odds_loop_seconds: int = 600

    consensus_weight_bettors: float = 0.12
    consensus_weight_web: float = 0.08

    # Active ensemble weights
    ensemble_weight_poisson: float = 0.45
    ensemble_weight_elo: float = 0.35
    ensemble_weight_gbm: float = 0.20  # heuristic GBM until factor-graph trainer ships

    # Intuition layer cap: max probability adjustment (+/-)
    intuition_max_adjustment: float = 0.08

    # Kelly fraction (fractional Kelly for risk management)
    kelly_fraction: float = 0.25

    # Minimum EV threshold to surface a bet
    min_ev_threshold: float = 0.02

    # Minimum confidence to rank (slightly soft — blank SKIP boards were the worse bug)
    min_confidence: float = 0.50

    # Maximum stake as % of bankroll (hard cap to protect users)
    max_stake_pct: float = 3.0

    # Per-match budget: max % on one single within that match's allocation
    match_max_stake_pct: float = 50.0

    # Default bankroll for stake recommendations (INR for students)
    default_bankroll: float = 2000.0

    # Optional local JSON store for private Stake portfolio consent/cache.
    portfolio_store_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def stake_network_enabled() -> bool:
    """True when we can reach Stake GraphQL (local Chrome, API token, or cloud browser)."""
    s = get_settings()
    if s.stake_use_browser or s.stake_api_token:
        return True
    if (s.stake_cdp_url or "").strip() or (s.browserbase_api_key or "").strip():
        return True
    return False


def remote_stake_browser_enabled() -> bool:
    s = get_settings()
    return bool((s.stake_cdp_url or "").strip() or (s.browserbase_api_key or "").strip())
