from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Set STAKE_USE_BROWSER=false to disable Stake scraping entirely (no popup,
    # falls back to ESPN/DraftKings model prices — ideal for cloud hosting).
    stake_use_browser: bool = True
    # Run Chromium without a visible window (STAKE_BROWSER_HEADLESS=0 for headful).
    # Once the persistent profile has solved Cloudflare once, headless reuse works.
    stake_browser_headless: bool = True
    # Open Chromium on API startup. Default off — browser launches on first
    # explicit Stake odds / bet-builder request instead (avoids popup spam).
    stake_browser_warmup_on_startup: bool = False

    # Consensus weighting (how much to consider vs model — never blindly follow)
    consensus_weight_bettors: float = 0.12
    consensus_weight_web: float = 0.08

    # Model weights (updated by continuous learning)
    ensemble_weight_poisson: float = 0.20
    ensemble_weight_elo: float = 0.15
    ensemble_weight_xgboost: float = 0.25
    ensemble_weight_lightgbm: float = 0.20
    ensemble_weight_neural: float = 0.10
    ensemble_weight_monte_carlo: float = 0.10

    # Intuition layer cap: max probability adjustment (+/-)
    intuition_max_adjustment: float = 0.08

    # Kelly fraction (fractional Kelly for risk management)
    kelly_fraction: float = 0.25

    # Minimum EV threshold to surface a bet
    min_ev_threshold: float = 0.02

    # Minimum confidence to rank
    min_confidence: float = 0.55

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
