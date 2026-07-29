# GAMBIT

Sports boards, prices, and model grades for soccer, basketball, and cricket.

## Run

```bash
cp .env.example .env
./scripts/run.sh
```

App: http://127.0.0.1:5173  
API: http://127.0.0.1:8000

Production:

```bash
./scripts/run_production.sh
```

## Routes

| Route | Page |
|-------|------|
| `/` | Landing |
| `/app` | Home |
| `/app/sport/:id` | Sport board |
| `/app/model` | Model |
| `/app/portfolio` | Portfolio |
| `/app/guide` | Guide |

## Notes

- Optional: `ODDS_API_KEY` in `.env`
- Optional: `STAKE_USE_BROWSER=true` for live Stake
- Deploy: [DEPLOY.md](DEPLOY.md)
