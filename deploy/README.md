# Gambit deploy (free)

## One-command production (laptop or VM)

```bash
./scripts/run_production.sh
# → http://0.0.0.0:8080  (app + API same origin)
```

Set `CRAFT_DISABLE=1` — training runs on GitHub Actions only.

## GitHub Actions (daily cloud training)

Workflow: `.github/workflows/craft-train.yml`  
Repo: https://github.com/abhyvx/gambit/actions

Manual run: Actions → **Craft training** → Run workflow.

Sync artifact to this machine:

```bash
./scripts/sync_model_from_github.sh
```

## VM + nginx

1. Clone to `/opt/gambit`, `pip install -e .`, build frontend.
2. Copy `deploy/gambit-api.service` → `/etc/systemd/system/`
3. Copy `deploy/nginx.conf` → `/etc/nginx/sites-available/gambit`
4. Daily cron: `0 2 * * * /opt/gambit/scripts/sync_model_from_github.sh && systemctl restart gambit-api`
