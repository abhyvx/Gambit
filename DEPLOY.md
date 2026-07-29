# Deploy Gambit on Render

## 1. Deploy the app

1. https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply**
3. Wait until **Live** → copy URL e.g. `https://gambit-xxxx.onrender.com`

If Blueprint fails: **New +** → **Web Service** → Docker → branch `main` → health `/api/health` → Free.

## 2. Stake odds on cloud

Render cannot scrape stake.com. Odds still work from ESPN and model prices.

For live Stake lines:

1. Edit `deploy/cloud_url.txt` to your Render URL (one https line, no placeholder)
2. Or set GitHub repo variable `GAMBIT_CLOUD_URL` to the same URL
3. GitHub Actions **Stake relay** runs every 15 minutes and POSTs to `/api/stake/relay`

| Service | Runs on | Schedule |
|---------|---------|----------|
| Web app | Render | Always |
| Stake relay | GitHub Actions | Every 15 min |
| Craft training | GitHub Actions | Daily |

## 3. After craft training

1. https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
2. Green run → Render → **Manual Deploy**

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Could not connect | Free Render sleeps. Open the URL once to wake it (30-60s). |
| Docker build failed | Pull latest `main`. Clear Render build cache and redeploy. |
| Stake 403 on Render logs | Expected. Stake comes via Actions relay. |
| Stake relay skips | Set `deploy/cloud_url.txt` or `GAMBIT_CLOUD_URL`. |
| No Stake prices | App uses ESPN/model prices. Relay fills Stake when CF allows. |

## Local

```bash
./scripts/run.sh
# optional live Stake:
# STAKE_USE_BROWSER=true in .env
# ./scripts/start_stake_relay.sh  (pushes to GAMBIT_CLOUD_URL)
```
