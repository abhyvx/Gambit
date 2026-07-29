# Deploy Gambit on Render

## 1. Deploy the app

1. https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply**
3. Wait until **Live** → copy URL e.g. `https://gambit-xxxx.onrender.com`

If Blueprint fails: **New +** → **Web Service** → Docker → branch `main` → health `/api/health` → Free.

Auto-deploy: if Render Auto-Deploy is on for `main`, every push rebuilds. You do not need a dashboard "commit". Manual Deploy only when you want to force a rebuild without a new push.

## 2. Stake odds on cloud

Render and GitHub Actions get Cloudflare-blocked by stake.com. They cannot scrape live Stake.

Odds still work from ESPN and model prices without Stake.

For live Stake lines on Render, run the laptop relay (this machine clears Cloudflare once):

```bash
# First time: Chrome may open — finish "Just a moment…", leave the profile alone
./scripts/start_stake_relay.sh

# Optional: push every 10 min in the background
./scripts/install_stake_relay_agent.sh
```

That POSTs priced fixtures to `/api/stake/relay`. A good push can also upload `stake_overlay_cache.json` to the `model-latest` release (`STAKE_UPLOAD_RELEASE=1`) so redeploys bootstrap Stake from disk.

| Service | Runs on | Role |
|---------|---------|------|
| Web app | Render | Always |
| Stake relay | Your Mac (`start_stake_relay` / LaunchAgent) | Live Stake → cloud |
| Craft training | GitHub Actions | Daily model |

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
