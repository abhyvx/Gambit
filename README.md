# GAMBIT

Sports betting analysis: calibrated probabilities → style-filtered picks → book prices.

Not a market dump. Not a chatty “AI buddy.” Skip when there is no edge.

## Architecture (target)

1. **Factor graph** (`ml/factor_graph.py`) — teams, players, managers, refs, venues, weather, schedule, playstyle ideology. Hierarchical Bayesian borrow-strength for lower leagues.
2. **Sport adapters** — soccer (Poisson/Elo today), basketball (possessions/spreads), cricket (next).
3. **Pricing** — Odds API for discovery; Stake browser for placeable lines.
4. **Decision policy** — user utility (goal/risk/structure) × calibrated probs × Kelly → few bets.
5. **Learning objective** — closing-line value (CLV) + settled P&L, not raw accuracy theater.

Training corpora (planned): top flight, lower leagues, internationals, club world, friendlies.

## Run

```bash
./scripts/run.sh
# App http://127.0.0.1:5173  ·  API http://127.0.0.1:8000
```

Set `ODDS_API_KEY` in `.env` for live leagues.

## Deploy (API only — craft trains in the cloud)

Local laptop should **not** run craft epochs. Set in `.env`:

```bash
CRAFT_DISABLE=1
```

Training runs on **GitHub Actions** (free tier: ~2000 min/month):

1. Push repo — workflow `.github/workflows/craft-train.yml` runs every 8h (or manually: Actions → Craft training).
2. Download artifact `bet-placer-model-state` after a run.
3. Copy into deploy host data dir (default `~/.bet_placer/`):
   - `craft.db`
   - `model_params.json`
   - `craft_nn.joblib`

**Local processes:** one API (`uvicorn` on 8000) + one Vite (5173). No duplicate craft threads.

**Retrain** on Model page runs the **full** pipeline (`tracker.train()` — history, boards, market replay), not per-team patches. Holdout craft eval uses the same frozen match IDs every epoch.

## App

| Route | What |
|-------|------|
| `/app` | Matches — one UI for all leagues including World Cup |
| `/app/settings` | Style + bankroll |
| `/app/model` | Calibration / train report |
| `/app/portfolio` | Private Stake portfolio |
| `/app/guide` | Method notes |

## Disclaimer

Analytical software. 18+. Not financial advice.
