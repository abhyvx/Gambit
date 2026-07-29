# GAMBIT

Sports betting analysis: calibrated probabilities, style-filtered picks, book prices.

Not a market dump. Not a chatty AI buddy. Skip when there is no edge.

## Deploy (Render, free)

1. Open https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply**
3. Add env vars in Render:
   - `STAKE_RELAY_SECRET` = long random string (for Stake relay, below)
   - `ODDS_API_KEY` = optional
4. Wait until **Live** → open `https://YOUR-APP.onrender.com/app`

Full steps: [DEPLOY.md](DEPLOY.md)

## Stake on cloud (relay workaround)

Stake blocks datacenter IPs (403). Cloud app uses **ESPN + model prices** by default.

For **live Stake lines** on the deployed app:

1. Set the same `STAKE_RELAY_SECRET` on Render and in local `.env`
2. Local `.env`:
   ```
   STAKE_USE_BROWSER=true
   STAKE_RELAY_SECRET=your-secret
   GAMBIT_CLOUD_URL=https://YOUR-APP.onrender.com
   ```
3. On your laptop (keep running):
   ```bash
   PYTHONPATH=src python3 scripts/stake_relay.py
   ```
   Opens Chrome locally, pushes odds to cloud every 5 minutes.

## Training (GitHub Actions, daily)

- Workflow: `.github/workflows/craft-train.yml`
- Manual run: https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
- Model artifact: https://github.com/abhyvx/Gambit/releases/tag/model-latest
- After a green run: Render → **Manual Deploy** (pulls fresh model on boot)

Local laptop: `CRAFT_DISABLE=1` (training stays in the cloud).

## Run locally (dev)

```bash
./scripts/run.sh
# http://127.0.0.1:5173  ·  API http://127.0.0.1:8000
```

Stake locally: `STAKE_USE_BROWSER=true` in `.env`, then use **Connect Stake** in the app.

## App routes

| Route | What |
|-------|------|
| `/app` | Matches |
| `/app/model` | Calibration / training report |
| `/app/portfolio` | Stake portfolio |
| `/app/guide` | Method notes |

## Disclaimer

Analytical software. 18+. Not financial advice.
