# Deploy Gambit on Render

## 1. Deploy the app

1. https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply**
3. Wait until **Live** → copy URL e.g. `https://gambit-xxxx.onrender.com`

If Blueprint fails: **New +** → **Web Service** → Docker → branch `main` → health `/api/health` → Free.

Auto-deploy: if Render Auto-Deploy is on for `main`, every push rebuilds. You do not need a dashboard "commit". Manual Deploy only when you want to force a rebuild without a new push.

## 2. Stake odds on cloud

Render and GitHub Actions get Cloudflare-blocked by stake.com. They cannot scrape live Stake.

**The fix:** run Stake on your Mac once, then keep a background agent pushing lines to Render.

```bash
# 1) One-time: opens Chrome — finish "Just a moment…", wait until it prints priced fixtures
cd "/path/to/Gambit"
source .venv/bin/activate
PYTHONPATH=src python3 scripts/connect_stake_and_push.py

# 2) Keep it fresh every 10 minutes
./scripts/install_stake_relay_agent.sh
```

That POSTs to `/api/stake/relay` and uploads `stake_overlay_cache.json` to GitHub `model-latest` so redeploys still boot with Stake.

Odds still work from ESPN/model when Stake is cold.

| Service | Runs on | Role |
|---------|---------|------|
| Web app | Render | Always |
| Stake relay | Your Mac (`connect_stake_and_push` / LaunchAgent) | Live Stake → cloud |
| Craft training | GitHub Actions | Daily model |

GitHub Actions Stake workflow cannot pass Cloudflare — treat it as best-effort only.
## 3. After craft training

1. https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
2. Green run → wait for Auto-Deploy, or Render → **Manual Deploy**

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Could not connect | Free Render sleeps. Open the URL once to wake it (30-60s). |
| Docker build failed | Pull latest `main`. Clear Render build cache and redeploy. |
| Stake 403 on Render logs | Expected. Use the laptop relay. |
| No Stake prices | App uses ESPN/model. Run `./scripts/start_stake_relay.sh` after clearing CF. |
| Empty Stake after scrape fail | Fixed: bad scrapes no longer wipe priced cache. |

## Local

```bash
./scripts/run.sh
# live Stake + push to cloud:
./scripts/start_stake_relay.sh
```
