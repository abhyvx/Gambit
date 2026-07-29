# Deploy Gambit on Render (free)

## Exact steps

### Blueprint (recommended)

1. https://dashboard.render.com/ → sign in with GitHub
2. **New +** → **Blueprint**
3. Connect repo **abhyvx/Gambit** → **Apply** (no env vars to type; blueprint fills them)
4. Wait 10-20 min until **Live**
5. Open `https://YOUR-SERVICE.onrender.com/app`

### Manual web service (if Blueprint fails)

1. **New +** → **Web Service** → repo **Gambit**, branch **main**
2. Runtime: **Docker**, Dockerfile `./Dockerfile`, plan **Free**
3. Health check: `/api/health`
4. Env: `CRAFT_DISABLE=1`, `STAKE_USE_BROWSER=false`, `STAKE_RELAY_SECRET=gambit-relay-v1-abhyvx`
5. **Create Web Service**

## Stake live odds (one URL in .env)

Cloud cannot call stake.com (403). Run the relay on your laptop:

**.env** (only your Render URL required):

```
GAMBIT_CLOUD_URL=https://YOUR-SERVICE.onrender.com
STAKE_USE_BROWSER=true
```

```bash
playwright install chromium   # once
./scripts/start_stake_relay.sh
```

Relay secret is built in (`gambit-relay-v1-abhyvx`). Same on Render and laptop automatically.

## Training

- Daily: midnight UTC on `main`
- Manual: https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
- Model: https://github.com/abhyvx/Gambit/releases/tag/model-latest
- After green run: Render → **Manual Deploy**

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Docker build fails | Manual Deploy → Clear build cache & deploy |
| Stake 403 in logs | Normal on cloud; run `./scripts/start_stake_relay.sh` on laptop |
| Model page empty | Wait for green Actions run; redeploy |
