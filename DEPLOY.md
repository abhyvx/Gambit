# Deploy Gambit on Render

## 1. Deploy the app

1. https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply**
3. Wait until **Live** → copy URL e.g. `https://gambit-xxxx.onrender.com`

If Blueprint fails: **New +** → **Web Service** → Docker → branch `main` → health `/api/health` → Free.

Auto-deploy: if Render Auto-Deploy is on for `main`, every push rebuilds. You do not need a dashboard "commit". Manual Deploy only when you want to force a rebuild without a new push.

## 2. Stake odds on cloud — Browserbase first, no laptop popups

Render and GitHub Actions get Cloudflare-blocked by stake.com. The preferred fix is now a
**remote browser** so the web app can keep a persistent cloud Chrome session without opening
Stake on your laptop.

Set these env vars on Render:

- `BROWSERBASE_API_KEY=<your real key>`

Optional alternative:

- `STAKE_CDP_URL=wss://...` if you already have another remote Chrome/CDP provider

With Browserbase/CDP configured:

- `/api/stake/connect` uses the remote browser path
- portfolio connect opens a Browserbase live-view URL instead of a local popup
- the background odds loop can keep Stake fresh server-side

Production persistence:

- `DATABASE_URL=<your production database url>`
- `TURSO_AUTH_TOKEN=<your Turso auth token>` (for Turso/libSQL URLs)

Today the app still stores auth/session/portfolio state in files unless `DATABASE_URL` is wired into the runtime persistence layer.

If Browserbase is **not** configured, the app now stays token-only / cache-only rather than
falling back to a local laptop popup.

Legacy fallback (only if you explicitly still want laptop relay):

```bash
cd "/path/to/Gambit"
source .venv/bin/activate
PYTHONPATH=src python3 scripts/connect_stake_and_push.py
./scripts/install_stake_relay_agent.sh
```

That POSTs to `/api/stake/relay` and uploads `stake_overlay_cache.json` to GitHub `model-latest`
so redeploys still boot with Stake. Odds still work from ESPN/model when Stake is cold.

| Service | Runs on | Role |
|---------|---------|------|
| Web app | Render | Always |
| Stake remote browser | Browserbase / remote CDP | Preferred live Stake → cloud |
| Stake relay | Your Mac (`connect_stake_and_push` / LaunchAgent) | Legacy fallback only |
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
| Stake 403 on Render logs | Expected without Browserbase/CDP. Set remote browser env vars. |
| No Stake prices | App uses ESPN/model or cached overlay. Configure Browserbase, or use the legacy relay. |
| Empty Stake after scrape fail | Fixed: bad scrapes no longer wipe priced cache. |

## Local

```bash
./scripts/run.sh
# live Stake + push to cloud:
./scripts/start_stake_relay.sh
```
