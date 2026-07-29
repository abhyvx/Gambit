# GAMBIT

Sports betting analysis: calibrated probabilities → style-filtered picks → book prices.

Not a market dump. Not a chatty "AI buddy." Skip when there is no edge.

## Architecture (target)

1. **Factor graph** (`ml/factor_graph.py`) - teams, players, managers, refs, venues, weather, schedule, playstyle ideology. Hierarchical Bayesian borrow-strength for lower leagues.
2. **Sport adapters** - soccer (Poisson/Elo today), basketball (possessions/spreads), cricket (next).
3. **Pricing** - Odds API for discovery; Stake browser for placeable lines.
4. **Decision policy** - user utility (goal/risk/structure) × calibrated probs × Kelly → few bets.
5. **Learning objective** - closing-line value (CLV) + settled P&L, not raw accuracy theater.

Training corpora (planned): top flight, lower leagues, internationals, club world, friendlies.

## Run

```bash
./scripts/run.sh
# App http://127.0.0.1:5173  ·  API http://127.0.0.1:8000
```

Production (one port):

```bash
./scripts/run_production.sh
# http://0.0.0.0:8080
```

Set `ODDS_API_KEY` in `.env` for live leagues.

## Deploy (Render, free)

1. https://dashboard.render.com/ → **New +** → **Blueprint** → connect **abhyvx/Gambit** → **Apply**
2. Wait until **Live** → open `https://YOUR-SERVICE.onrender.com/app`
3. Optional: add `ODDS_API_KEY` in Render env vars

`render.yaml` already sets `CRAFT_DISABLE=1`, `STAKE_USE_BROWSER=false`, and a **built-in relay secret** (no manual key setup).

Full steps: [DEPLOY.md](DEPLOY.md)

## Stake on cloud (relay, no secret setup)

Stake blocks datacenter IPs (403). The cloud app uses ESPN + model prices until you run the relay.

**Relay secret is preconfigured** in `render.yaml` and `.env.example` (`gambit-relay-v1`). You do not generate your own.

On your laptop, add only your Render URL to `.env`:

```bash
GAMBIT_CLOUD_URL=https://YOUR-SERVICE.onrender.com
STAKE_USE_BROWSER=true
```

Then run (keep open):

```bash
playwright install chromium   # once
./scripts/start_stake_relay.sh
```

Chrome opens locally; live Stake odds push to cloud every 5 minutes.

## Training (GitHub Actions, daily)

Local laptop should **not** run craft epochs (`CRAFT_DISABLE=1` on Render).

Training runs on **GitHub Actions** (free tier ~2000 min/month):

1. Workflow `.github/workflows/craft-train.yml` runs daily midnight UTC
2. Manual run: https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
3. Model release: https://github.com/abhyvx/Gambit/releases/tag/model-latest
4. Sync locally: `./scripts/sync_model_from_github.sh`
5. After a green run: Render → **Manual Deploy**

**Retrain** on Model page runs the **full** pipeline (`tracker.train()`: history, boards, market replay), not per-team patches. Holdout craft eval uses the same frozen match IDs every epoch.

## App

| Route | What |
|-------|------|
| `/app` | Matches - one UI for all leagues including World Cup |
| `/app/settings` | Style + bankroll |
| `/app/model` | Calibration / train report |
| `/app/portfolio` | Private Stake portfolio |
| `/app/guide` | Method notes |

## Disclaimer

Analytical software. 18+. Not financial advice.
