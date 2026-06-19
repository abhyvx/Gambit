# GAMBIT - AI Sports Betting Analyst & Value Betting Engine

> **© 2026 Abhyuday Khanna. All Rights Reserved. Proprietary and confidential.**
> This is private, closed-source software. No license to use, copy, modify, or
> distribute is granted. See [`LICENSE`](./LICENSE). Unauthorized use is prohibited.

A hybrid intelligence system for identifying **positive expected value (EV)** bets by combining statistical models, contextual analysis, market inefficiency detection, and analyst-like intuition.

> **Philosophy:** The goal is not maximum prediction accuracy — it is maximum long-term ROI by finding where true probability exceeds bookmaker implied probability.

## Features

- **Multi-source data model** — team stats, form, players, tactics, chemistry, external factors, referees, H2H
- **Ensemble ML** — Poisson, ELO, gradient boosting heuristics, Monte Carlo simulation
- **Analyst Intuition Layer** — adjusts probabilities based on morale, stylistic matchups, injuries, motivation, sentiment
- **Multi-market scanning** — match winner, O/U goals, BTTS, corners (extensible to all prop markets)
- **EV & Kelly engine** — implied vs true probability, expected ROI, fractional Kelly sizing
- **Ranking** — bets ranked by ROI, EV, confidence, risk, and market liquidity
- **Explainability** — every bet includes a human-readable rationale
- **Continuous learning** — feedback loop tracks results and adapts model weights

## Stake.com Live Mode (default)

Scrapes real-time odds and payouts from Stake via their GraphQL API, scans **every available market**, and tells you whether to bet on each match:

```bash
# Live Stake analysis (all trending soccer matches)
bet-placer --stake

# Specific match
bet-placer --stake --match Liverpool

# Specific Stake fixture ID
bet-placer --stake --fixture-id FIXTURE_ID

# Demo mode (no Stake)
bet-placer --demo
```

### Match Verdicts

For each match you'll get one of:

| Verdict | Meaning |
|---------|---------|
| **BET** | Clear positive EV — place selective bets on ranked picks |
| **CAUTION** | Marginal edge — small stake on top pick only |
| **SKIP** | No edge or too risky — do not bet this match |

### Consensus Layers

- **Stake bettor feed** — real-time `allSportBets` + `highrollerSportBets` volume
- **Web consensus** — Reddit r/soccerbetting, r/sportsbook sentiment
- Consensus is **considered but not blindly followed** — extreme public sentiment triggers fade signals

### Stake API Token (optional)

Add `STAKE_API_TOKEN` to `.env` from Stake → Settings → Security → API Tokens for authenticated endpoints.

If Stake.com is unreachable (geo-block), the engine falls back to cached data automatically.

## Web Dashboard (Product UI)

```bash
# Terminal 1 — API
source .venv/bin/activate
uvicorn bet_placer.api.server:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm install && npm run dev
```

Open **http://127.0.0.1:5173**

### Navigation
- **Dashboard** — top value bets across World Cup
- **World Cup** — all FIFA World Cup 2026 matches
- **Browse Sports** — NBA, NFL, EPL, Champions League, and more
- **How It Works** — plain-English guide (EV, Kelly, when to skip)
- **Bankroll** — set your bankroll; stakes capped at 3%

### Live Data Setup

| Key | Get it | Enables |
|-----|--------|---------|
| `ODDS_API_KEY` | [the-odds-api.com](https://the-odds-api.com/) (free tier) | Live World Cup + 40+ sports from real bookmakers |
| `STAKE_API_TOKEN` | Stake → Settings → API Tokens | Stake-specific odds (VPN may be needed) |

Without keys, rich demo data is used so you can test the full product.

### Protecting Your Money
- Models are **independent of bookmaker odds** (no circular math)
- Vig removed from implied probabilities before comparing
- Stakes capped at **3% of bankroll** (configurable)
- **SKIP** verdict when no edge — sitting out is a feature
- Plain-English stake recommendations on every bet

## Quick Start (CLI)

```bash
# Install
cd "Bet Placer"
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run demo analysis (uses sample Premier League matches)
bet-placer

# Filter to a specific match
bet-placer --match Liverpool

# Adjust EV threshold
bet-placer --min-ev 0.03 --top 5
```

## Configuration

Copy `.env.example` to `.env` and add API keys for live data:

| Variable | Source | Purpose |
|----------|--------|---------|
| `API_FOOTBALL_KEY` | [API-Football](https://www.api-football.com/) | Fixtures, stats, injuries |
| `ODDS_API_KEY` | [The Odds API](https://the-odds-api.com/) | Live bookmaker odds |
| `OPENWEATHER_API_KEY` | OpenWeatherMap | Match-day weather |
| `NEWS_API_KEY` | NewsAPI | Sentiment / NLP layer |

## Architecture

```
src/bet_placer/
├── analysis/       # Form, players, tactics, context, feature engineering
├── data/           # Collectors (demo + API extension points)
├── engine/         # Probability orchestration, EV calculation
├── explain/        # Human-readable bet explanations
├── intuition/      # Analyst reasoning layer
├── learning/       # Post-match feedback & weight updates
├── markets/        # Odds math, vig removal, line movement
├── ml/             # Poisson, ELO, Monte Carlo, ensemble
├── nlp/            # Sentiment analysis (extension point)
└── main.py         # CLI
```

## How Value Is Computed

For each market selection:

1. **Ensemble models** produce independent probability estimates
2. **Intuition layer** applies contextual adjustments (capped at ±8%)
3. **True probability** is compared to **implied probability** from best available odds
4. **EV** = `(true_prob × decimal_odds) − 1`
5. Bets above the EV threshold are ranked by composite score

## Continuous Learning

After matches settle, record outcomes:

```python
from bet_placer.learning.feedback import FeedbackLoop

fb = FeedbackLoop()
fb.record_result("demo-001", "over_under_goals", "over", won=True, profit=0.72)
print(fb.get_performance_summary())
```

Model weights are automatically adjusted in `data/model_weights.json` after 20+ settled bets.

## Extending

- **Live data:** Implement `APIFootballCollector.fetch_matches()` in `data/collectors.py`
- **More markets:** Add probability estimates in `ml/ensemble.py` and odds in collectors
- **Train ML models:** Use `ml/ensemble.get_sklearn_ensemble()` with historical feature matrices
- **NLP:** Wire `nlp/sentiment.py` to news/social APIs

## Disclaimer

This software is for educational and analytical purposes. Sports betting involves financial risk. Never bet more than you can afford to lose. Check local laws regarding sports betting.
