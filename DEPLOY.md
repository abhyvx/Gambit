# Deploy Gambit on Render (free)

## 1. Deploy the app

1. https://dashboard.render.com/ → **New +** → **Blueprint**
2. Connect **abhyvx/Gambit** → **Apply** (env vars pre-filled from `render.yaml`)
3. Wait until **Live** → copy URL e.g. `https://gambit-xxxx.onrender.com`

If Blueprint fails: **New +** → **Web Service** → Docker → branch `main` → health `/api/health` → Free.

## 2. Enable 24/7 Stake + training (one edit, no secrets)

Edit in GitHub (or locally and push):

**`deploy/cloud_url.txt`** - replace placeholder with your Render URL:

```
https://gambit-xxxx.onrender.com
```

That single line enables:

| Service | Runs on | Schedule |
|---------|---------|----------|
| Craft training | GitHub Actions | Daily midnight UTC |
| Stake relay | GitHub Actions | Every 15 minutes |
| Web app | Render | 24/7 |

Optional: GitHub repo **Settings → Variables →** `GAMBIT_CLOUD_URL` = same URL.

## 3. After craft training completes

1. https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
2. Green run → Render → **Manual Deploy**

Model release: https://github.com/abhyvx/Gambit/releases/tag/model-latest

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Docker build failed | Pull latest `main` (regex fix in SportPage). Clear build cache & deploy. |
| Stake 403 on Render logs | Normal. Stake comes via Actions relay, not Render directly. |
| Stake relay skips | `deploy/cloud_url.txt` still has placeholder. Paste real Render URL. |
| Model page empty | Wait for green craft run; Manual Deploy. |

## Local dev only

```bash
./scripts/run.sh
STAKE_USE_BROWSER=true   # optional, in .env
```

Laptop relay fallback: `./scripts/start_stake_relay.sh` (not needed if Actions relay works).
