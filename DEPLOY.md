# Deploy Gambit on Render (free)

## Exact steps

### Blueprint (recommended)

1. https://dashboard.render.com/ → sign in with GitHub
2. **New +** → **Blueprint**
3. Connect repo **abhyvx/Gambit** → **Apply**
4. **Environment** tab, add:
   | Key | Value |
   |-----|--------|
   | `CRAFT_DISABLE` | `1` (auto from blueprint) |
   | `STAKE_USE_BROWSER` | `false` |
   | `STAKE_RELAY_SECRET` | pick a long random string |
   | `GAMBIT_REPO` | `abhyvx/Gambit` |
   | `ODDS_API_KEY` | optional |
5. Wait 10-20 min until **Live**
6. Open `https://YOUR-SERVICE.onrender.com/app`

### Manual web service (if Blueprint fails)

1. **New +** → **Web Service** → repo **Gambit**, branch **main**
2. Runtime: **Docker**, Dockerfile `./Dockerfile`, plan **Free**
3. Health check: `/api/health`
4. Same env vars as above
5. **Create Web Service**

## Stake live odds on cloud

Render cannot call stake.com directly (403). Use the **relay**:

**On Render:** `STAKE_RELAY_SECRET=your-secret`

**On your laptop** (`.env`):
```
STAKE_USE_BROWSER=true
STAKE_RELAY_SECRET=your-secret
GAMBIT_CLOUD_URL=https://YOUR-SERVICE.onrender.com
```

Run (keep open):
```bash
playwright install chromium   # once
PYTHONPATH=src python3 scripts/stake_relay.py
```

Cloud app receives live Stake boards via `/api/stake/relay`.

## Training

- Daily cron: midnight UTC on `main`
- Manual: https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml → **Run workflow**
- Model release: https://github.com/abhyvx/Gambit/releases/tag/model-latest
- After success: Render → **Manual Deploy**

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Docker build fails | **Manual Deploy** → **Clear build cache & deploy** after pulling latest `main` |
| Port / health check | Fixed: app listens on Render `PORT` |
| Model page empty | Wait for green Actions run; redeploy |
| Stake 403 in logs | Expected on cloud; use `stake_relay.py` on laptop |
| No Stake prices | Run relay script with matching secret |
