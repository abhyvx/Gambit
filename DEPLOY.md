# Deploy Gambit on Render (free)

## Exact steps (copy-paste path)

### Option A — Blueprint (recommended)

1. Open **https://dashboard.render.com/**
2. Sign in with **GitHub** (same account as `abhyvx`).
3. Click **New +** (top right) → **Blueprint**.
4. Click **Connect account** if GitHub isn’t linked yet.
5. Find repo **Gambit** (`abhyvx/Gambit`) → **Connect**.
6. Render shows `render.yaml` — click **Apply**.
7. Wait **10–20 minutes** (first Docker build is slow).
8. When status is **Live**, click the service → copy **URL** (e.g. `https://gambit-xxxx.onrender.com`).
9. Open **`https://YOUR-URL/app`** in the browser.

### Option B — Manual web service (if Blueprint errors)

1. **https://dashboard.render.com/** → **New +** → **Web Service**.
2. **Connect repository** → **Gambit** → **Connect**.
3. Settings:
   - **Name:** `gambit`
   - **Region:** Oregon (US West)
   - **Branch:** `main`
   - **Runtime:** **Docker**
   - **Dockerfile path:** `./Dockerfile`
   - **Instance type:** Free
4. **Environment** → Add variables:
   | Key | Value |
   |-----|--------|
   | `CRAFT_DISABLE` | `1` |
   | `STAKE_USE_BROWSER` | `false` |
   | `STAKE_BROWSER_WARMUP_ON_STARTUP` | `false` |
   | `GAMBIT_REPO` | `abhyvx/Gambit` |
   | `ODDS_API_KEY` | (optional — your key) |
5. **Advanced** → Health check path: `/api/health`
6. Click **Create Web Service**.
7. Wait until **Live** → open `https://YOUR-SERVICE.onrender.com/app`.

### If deploy fails on Render

| Error | Fix |
|--------|-----|
| Build failed | Check **Logs** tab — usually npm or pip; push latest `main` and **Manual Deploy → Clear build cache & deploy**. |
| Port scan failed / didn’t bind to port | Fixed in `start_cloud.sh` — uses Render’s `PORT`. Redeploy after pulling latest `main`. |
| Health check failed | Wait 2 min after boot; visit `/api/health` — should return `{"status":"ok"}`. |
| App loads but model empty | Training publishes to https://github.com/abhyvx/Gambit/releases/tag/model-latest — redeploy after a successful Actions run. |

**Do not run** `./scripts/run_production.sh` for production — that’s local dev only.

---

## Cloud training (GitHub Actions — daily, free)

1. **https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml**
2. **Run workflow** → branch `main` → Run.
3. When green, model is in:
   - **Release:** https://github.com/abhyvx/Gambit/releases/tag/model-latest
   - **Artifact:** Actions run → `bet-placer-model-state`
4. On Render: **Manual Deploy** → **Deploy latest commit** (container re-downloads model on boot).

---

## Links

| What | URL |
|------|-----|
| Repo | https://github.com/abhyvx/Gambit |
| Training | https://github.com/abhyvx/Gambit/actions |
| Model release | https://github.com/abhyvx/Gambit/releases/tag/model-latest |
| Render dashboard | https://dashboard.render.com/ |
