# Cloud deploy (Render — free tier)

## One-click deploy

1. Open **[Render Blueprint deploy](https://dashboard.render.com/select-repo?type=blueprint)** and connect **abhyvx/Gambit**.
2. Render reads `render.yaml` and creates the **gambit** web service.
3. Add optional env var `ODDS_API_KEY` in the Render dashboard.
4. Your live URL will be `https://gambit-xxxx.onrender.com` (shown after deploy).

The container:
- Serves app + API on one port (`CRAFT_DISABLE=1` — no training on the web host).
- On boot, downloads the latest model from GitHub Release **`model-latest`** (published by the craft-train workflow).

## Training (GitHub Actions — daily, free)

- https://github.com/abhyvx/Gambit/actions/workflows/craft-train.yml
- Manual run: Actions → **Craft training** → Run workflow.
- After success, redeploy Render (or restart service) to pull the new `model-latest` release.

## Do not use local terminal for production

Use Render URL only. Local `./scripts/run_production.sh` is for development.
