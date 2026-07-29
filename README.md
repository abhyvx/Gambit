# GAMBIT

Sports betting analysis: calibrated probabilities, style-filtered picks, book prices.

Not a market dump. Not a chatty "AI buddy." Skip when there is no edge.

---

## What it does

Gambit reads live and historical match data, builds per-sport strength models (Elo, Poisson, player nodes), maps that to **every market type** (1X2, Asian handicap, DNB, double chance, corners, cards, totals, moneyline, spreads), compares model probability to book price, and surfaces **few, sized tickets** matched to your style (protect bankroll / hit target / value / fun).

The Model desk grades itself on **real finished results** and paired closing lines, not vibes. Craft training runs on a **frozen holdout** (same matches every epoch) so improvements are comparable.

---

## Architecture

| Layer | Module | Role |
|-------|--------|------|
| Data | `data/espn_leagues.py`, `ml/sport_history.py` | ESPN boards (soccer, NBA, NCAA, WNBA, FIBA, cricket), football-data CSVs, Cricsheet, FiveThirtyEight Elo |
| Strength | `ml/elo.py`, `ml/poisson.py`, `ml/factor_graph.py` | Team + player Elo, Poisson score grid (soccer), sport adapters (BB/CK) |
| Markets | `engine/all_markets.py`, `ml/market_replay.py` | Popular + niche markets graded on history |
| Pricing | `engine/stake_odds.py`, Odds API cache | Stake lines (relay), DraftKings/ESPN fallback |
| Policy | `engine/match_card.py`, `engine/target_planner.py` | Style-aware slips, Kelly sizing, target paths |
| Learning | `ml/craft_train.py`, `ml/betting_evolution.py` | Paper craft ROI, holdout gates, champion restore |

**Learning objective:** closing-line value + settled P&L. **Gates:** overall ROI ≥ 25%, each sport ROI > 0, hit rate ≥ 60%, monthly not red.

---

## App routes

| Route | What |
|-------|------|
| `/` | Landing |
| `/app` | Home board (all sports) |
| `/app/sport/:id` | League board + match slip |
| `/app/worldcup` | World Cup hub |
| `/app/model` | Training report, ROI curves, 20+ insight containers |
| `/app/portfolio` | Stake portfolio sync (local browser) |
| `/app/guide` | Full pipeline documentation |

---

## Run locally

```bash
cp .env.example .env
./scripts/run.sh
# http://127.0.0.1:5173  ·  API http://127.0.0.1:8000
```

Production (single port):

```bash
./scripts/run_production.sh
# http://0.0.0.0:8080
```

Optional: `ODDS_API_KEY` in `.env` for live multi-league odds. `STAKE_USE_BROWSER=true` for local Stake Connect.

---

## Deploy on Render (free)

1. https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply**
3. Wait until **Live** → copy your URL

Blueprint sets `CRAFT_DISABLE=1`, `STAKE_USE_BROWSER=false`, relay secret automatically.

Details: [DEPLOY.md](DEPLOY.md)

### After deploy: point cloud services at your URL

Edit **one line** in the repo:

```
deploy/cloud_url.txt   →  https://YOUR-SERVICE.onrender.com
```

Commit and push. This enables:

- **Stake relay** (GitHub Actions, every 15 min, 24/7, no laptop)
- Optional: set GitHub repo variable `GAMBIT_CLOUD_URL` to the same URL

---

## Cloud training (24/7, GitHub Actions)

| Workflow | Schedule | What |
|----------|----------|------|
| [Craft training](https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml) | Daily midnight UTC | Holdout craft epochs, publishes `model-latest` release |
| [Stake relay](https://github.com/abhyvx/Gambit/actions/workflows/stake-relay.yml) | Every 15 min | Playwright fetch → POST to Render `/api/stake/relay` |

Model artifact: https://github.com/abhyvx/Gambit/releases/tag/model-latest

After a green craft run: Render → **Manual Deploy** (boot pulls fresh model).

Manual craft run: Actions → Craft training → Run workflow.

---

## Stake on cloud

Render cannot call stake.com directly (403 from datacenter IPs).

**Default (no laptop):** GitHub Actions `stake-relay.yml` runs every 15 minutes once `deploy/cloud_url.txt` has your Render URL.

**Fallback (local):** `./scripts/start_stake_relay.sh` if Actions runners are blocked by Cloudflare.

---

## Model page metrics

- **Holdout ROI / hit rate:** same frozen matches every craft epoch (not per-team patches)
- **Sport ROI:** gated; bleeding sports excluded from holdout eval display
- **Charts:** 10-epoch block means (archived), not live zigzags
- **Retrain button:** full `tracker.train()` pipeline (history + boards + market replay)

---

## Disclaimer

Analytical software. 18+. Not financial advice. Past paper ROI ≠ live bankroll.
