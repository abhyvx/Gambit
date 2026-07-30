# Gambit

Gambit is a three-sport betting desk for soccer, basketball, and cricket: live boards, priced markets, model grades, a slip you control, a private portfolio journal, and a learning loop that grades tickets on frozen holdout data.

It is not a bookmaker. Gambit does not place bets or move money. You read the desk and decide; any real wager is on a third-party book. Paper metrics on the Model page are research, not a promise of live profit.

---

## Table of contents

1. [What it does](#what-it-does)
2. [How recommendations and learning work](#how-recommendations-and-learning-work)
3. [Tech stack (detailed)](#tech-stack-detailed)
4. [Math and calculations](#math-and-calculations)
5. [Configuration variables](#configuration-variables)
6. [Runtime architecture](#runtime-architecture)
7. [Product surfaces](#product-surfaces)
8. [Operational constraints](#operational-constraints)
9. [Repo map](#repo-map)
10. [Run locally](#run-locally)
11. [Security and liability](#security-and-liability)
12. [License](#license)

---

## What it does

1. **Boards** — Fixtures for soccer, basketball, and cricket (ESPN first). Stake prices overlay when a relay or browser path is warm; otherwise cached books or labeled model fair prices so open matches stay priced.

2. **Strength** — Team and player ratings from history and sport-specific fuel. Feeds win probabilities for match result, totals, handicaps, and related lines.

3. **Prices** — Model chance vs decimal price. Edge is calibrated probability minus vig-free book implied chance. Ticket verdicts are plain language (back / caution / skip).

4. **Slips** — Singles or multis you build. Confirm-only journals work without a book. Optional Stake API token import syncs history; it does not auto-bet.

5. **Portfolio** — Private journal: imported Stake history, confirmed slips, manual past bets. Settled matches update results. Optional opt-in learning from graded tickets.

6. **Model desk** — Holdout ROI, hit rate, per-sport gates, equity curves, market depth, factor counts. Craft bar: **25% overall ROI**, every sport above **0%**, hit rate at least **60%**. Until that clears, the desk says **Below target**.

---

## How recommendations and learning work

This section is words and math pointers only. **Before → after run charts live on the Model page** (not here), so the README stays readable and the live desk stays the source of truth.

### What the terms mean

| Term | Meaning |
|------|---------|
| **Model chance (P)** | Calibrated probability that a selection wins, from Elo + market models + craft blend. |
| **Odds (O)** | Decimal price from Stake, a book cache, or a labeled model fair line. |
| **Implied chance** | Vig-free fair chance from the decimal odds (see [Math](#math-and-calculations)). |
| **Edge** | Model chance minus that fair chance. Positive edge means the model likes the price on paper. |
| **Verdict** | Plain language on the ticket: worth considering, fair, or skip — never a guarantee. |
| **Holdout** | A **frozen** set of match IDs. Every craft epoch grades the same games so improvement is comparable. |
| **Holdout ROI** | Total paper profit divided by total stake on that frozen book. Not your live bankroll. |
| **Holdout hit rate** | Wins / settled holdout tickets. Bar is **60%+**. |
| **Craft gates / desk gate** | Clears only when overall ROI is at least **25%**, every sport ROI is above **0%**, and accuracy is at least **60%**. Until then the desk says **Below target**. |
| **Self-improvement / equity** | Running **best-so-far** block mean holdout ROI. Rising = a new graded best. Flat = champion already locked. |
| **Paired closes** | Model-fair vs close-price pairs in `betting_evolution.db` — used when craft holdout for a sport is thin or gated. |

### How we decide what to recommend

1. Build a chance **P** for the selection (sport Elo / Poisson / totals / craft blend).
2. Attach a real or labeled decimal price **O**.
3. Remove vig → fair chance; **edge** = P minus fair.
4. Optional Kelly fraction sizes a paper stake (capped). Low edge, low confidence, or book-offline estimates get softer verdicts or skips.
5. The slip is still yours: Gambit never places the bet.

### Match-discretion Recs (not a global template)

Main **Recs** pick a structure **per fixture**, not from Settings goal/risk/structure:

| Shape | When |
|-------|------|
| **Single** | Clear quality + model lean (high-confidence favourite). Prefer this when suited. |
| **Spread / loss-min** | Draw-live or tight game — capital preservation beats forcing a winner. |
| **SGM** | Same-game multi only when the combined read is better than a single. |
| **Caution / thin** | No real edge — show a small lean or skip rather than invent +EV. |

**Target** owns cashout / insurance / profit-route tickets. Those plans must not dump into main Recs as the default card.

### Strength vs board priors (all sports)

League boards stamp flat priors (soccer ~1.45 / 1.20 home/away xG). That is a **fallback only**. Before analyze:

1. Resolve each side through `canon_team` aliases (e.g. Manchester United = Man United).
2. Pull the strongest matching Elo from global + sport buckets (`elo` / `elo_by_sport`).
3. `apply_strength_stats` overwrites flat attack/defence rates so a mid-table host cannot look like a 51% favourite over a top club.
4. Basketball / cricket use the same identity + Elo path for two-way moneyline.

**Cloud boot:** Elo ships in-repo as `ml/bundled_strength.json` so Render does not wait on `bootstrap_model.sh` before strength works. `load_params` merges that floor and reloads when disk `model_params.json` appears (avoids caching empty Elo forever). `/api/health` → `elo_teams` should be thousands when live.

Regression: `PYTHONPATH=src python3 scripts/check_strength_all_sports.py` (Hull/Man Utd, quality gaps, BB, cricket, human verdict labels, cold-start without disk params). Run related `scripts/check_*.py` before shipping Recs/strength changes — do not treat one fixture as proof.

### How the model learns and improves

1. **Fuel** — finished boards + history corpora for soccer, basketball, and cricket.
2. **Craft epoch** — train `CraftNet` on rotating fuel; evaluate on the **same** holdout IDs.
3. **Champion policy** — if a run regresses, restore the best graded slice so the public desk does not silently get worse.
4. **Sport gates** — a sport under water (e.g. early cricket craft) is gated off live picks; paired ROI may still show for honesty.
5. **Blocks** — every ~10 epochs, mean holdout ROI is recorded. Best-so-far equity only moves up when a block beats the prior champion.
6. **Portfolio opt-in** — graded user journals can feed learning later; opt out anytime.

Early desks sat near a flat ~2% best-so-far with cricket craft deep red and gated. Later desks moved best-so-far into the mid-single digits with all three sports green on the published cells. The desk gate can still honestly say **Below target** until the 25% bar clears. Open **Model** for the version/run comparison chart.

Past paper results do not guarantee live profit.

---

## Tech stack (detailed)

| Layer | Technology | Role in Gambit |
|-------|------------|----------------|
| API | **Python 3.12**, **FastAPI**, **Uvicorn** | HTTP API, auth, portfolio, insights, odds endpoints. Lifespan binds health first; warmups run on a daemon thread so Render free tier does not hang on boot. |
| Frontend | **React 18**, **Vite 6**, **React Router** | Boards, slip, Model desk, Portfolio, Guide, legal pages. Client insights cache rejects desks below the live revision. |
| Ratings | **Elo** (`ml/elo.py`) + sport priors | Match-winner probabilities for soccer (1X2) and two-way sports (BB/cricket). |
| Markets | Poisson / ensemble hooks, market advisor, EV engine | Totals, handicaps, props where fuel exists; edge vs book after vig removal. |
| Craft learner | **sklearn MLP** (`CraftNet`), SQLite `craft.db` | Epoch train on rotating fuel; eval on frozen holdout + paired closes. |
| Pair store | SQLite `betting_evolution.db` | Historical model-fair vs close-price pairs for soccer / BB / cricket. |
| Boards | ESPN scrape/cache, Stake GraphQL/overlay, optional **The Odds API** | Primary fixtures without paid keys; Odds API is optional enricher. |
| Browser | Playwright / Browserbase / CDP (optional) | Live Stake depth when Cloudflare allows; otherwise labeled fallbacks. |
| Auth | PBKDF2-HMAC-SHA256 (120k iters), bearer sessions | Local-first accounts; no “we place bets” surface. |
| Secrets | Fernet (`GAMBIT_SECRETS_KEY`) | Stake API tokens sealed at rest when configured. |
| Persistence | JSON under `BET_PLACER_HOME`, optional Turso/`DATABASE_URL` | Users, portfolios, insights cache, factor catalog. |
| Deploy | Docker, `scripts/start_cloud.sh` | Bind `$PORT` immediately; `bootstrap_model.sh` in background. |
| Charts / desk | Cached `model_insights_cache.json` + `publish_clean_desk` | Serve path never rebuilds the full desk (OOM protection). |

### Frontend packages (high level)

- React + Vite for the SPA
- No heavy chart library required for core boards; Model desk draws SVG series from API curve arrays
- `localStorage` for auth token, age gate, bankroll/slip prefs, insights cache key `gambit_insights_v19`

### Backend packages (high level)

- `fastapi`, `uvicorn`, `pydantic` / settings
- `numpy`, `scikit-learn`, `joblib` for craft NN
- `httpx` / `requests` for ESPN and books
- Optional Playwright for Stake

---

## Math and calculations

Plain English only — no LaTeX. Code lives in `ml/elo.py`, `markets/odds.py`, and the EV / Kelly helpers.

### Elo match probabilities

Each side has a rating (home Rh, away Ra). Home advantage H is added to the home side (soccer default **65** Elo points; basketball **55**; cricket **20**).

1. Home expected score Eh = 1 / (1 + 10^(-(Rh + H - Ra) / 400)).
2. Soccer draw mass shrinks with the rating gap: d = 0.28 * e^(-|Rh + H - Ra| / 200).
3. Then: P(home) = Eh * (1 - d), P(away) = (1 - Eh) * (1 - d), P(draw) = d, then normalize so they sum to 1.

Basketball / cricket use a tiny draw mass (~0.02) and are treated as two-way for fair prices.

### Fair decimal odds from probability

With overround margin m (model fair often uses **1.04**):

odds_i = m / max(P_i, P_min)

### Book implied and de-vig

Decimal odds O imply chance 1/O. Two-way and three-way vig removal lives in `markets/odds.py` (`remove_vig_two_way`, `remove_vig_three_way`) so “fair implied” is the book chance without the juice.

### Expected value and edge

- **EV** = P_true * O - 1
- **Edge** = P_calibrated - P_fair_implied

When model and book disagree modestly, the value finder blends:

P_true = 0.62 * P_model + 0.38 * P_fair

It **drops** the pick if |P_model - P_fair| > 0.25 (treat as model error, not a free lunch). Also skip if EV > 0.25 (unrealistic in liquid markets) or P_true < 0.45 (longshot filter).

### Fractional Kelly stake

With b = O - 1 (net decimal odds):

- full Kelly fraction f* = (P * b - (1 - P)) / b
- stake fraction = max(0, f* * kappa)

kappa is `KELLY_FRACTION` (default **0.25**). Caps: `MAX_STAKE_PCT` of bankroll, per-match `MATCH_MAX_STAKE_PCT`.

### Craft holdout ROI

For a graded book of tickets:

**ROI** = (sum of PnL) / (sum of stake)

Hit rate = wins / settled tickets. Sport ROI uses the same ratio per sport bucket (stake is about n times match budget when stake is not logged).

### Craft gates (desk bar)

All must clear:

| Gate | Default |
|------|---------|
| Overall holdout ROI | at least `TARGET_ROI` = **0.25** |
| Each of soccer, basketball, cricket ROI | above **0** |
| Holdout accuracy | at least `TARGET_ACC` = **0.60** |
| Minimum ticket volume | `MIN_BETS` / `MIN_BETS_PER_SPORT` |

`FLOOR_P` = **0.60**: blend / model_p floor when placing craft tickets. Soccer even-money (~1.91) paired closes use a higher model_p floor (**~0.85**) so the sport actually places bets.

### Self-improvement curve

Desk equity / `craft_roi_best` is the **running maximum** of block mean ROI (best-so-far). It never declines for drama. Rising means a new graded best landed.

---

## Configuration variables

Copy `.env.example` → `.env`. Everything is optional; the app degrades with labels instead of crashing.

### Hosting and CORS

| Variable | Default / notes |
|----------|-----------------|
| `PORT` / `GAMBIT_PORT` | Render injects `PORT`; local often 8000 |
| `GAMBIT_HOST` | `0.0.0.0` on cloud |
| `BET_PLACER_HOME` | Data dir (cloud: `/var/lib/bet_placer`) |
| `GAMBIT_FRONTEND_DIST` | Built SPA path inside Docker |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `GAMBIT_CLOUD_URL` | Public base URL for relays |

### Books and boards

| Variable | Purpose |
|----------|---------|
| `ODDS_API_KEY` | The Odds API enricher (optional) |
| `STAKE_API_TOKEN` | Host-level Stake token (optional; prefer per-user portfolio token) |
| `STAKE_GRAPHQL_ENDPOINT` | Default `https://stake.com/_api/graphql` |
| `STAKE_USE_BROWSER` | Local Playwright Stake path |
| `STAKE_BROWSER_HEADLESS` | Headless Chrome |
| `STAKE_BROWSER_WARMUP_ON_STARTUP` | Pre-launch browser (default off; keep off for fast boot) |
| `BROWSERBASE_API_KEY` | Remote browser for cloud Stake |
| `STAKE_CDP_URL` | Raw CDP alternative |
| `STAKE_RELAY_SECRET` | Laptop relay auth |

### Security and admin

| Variable | Purpose |
|----------|---------|
| `GAMBIT_SECRETS_KEY` | Fernet key for sealing Stake tokens |
| `GAMBIT_ADMIN_EMAILS` | Comma-separated admin roster |
| `GAMBIT_ADMIN_SECRET` | Optional shared admin header |

### Craft and learning

| Variable | Purpose |
|----------|---------|
| `CRAFT_DISABLE` | `1` on tiny hosts: no in-process craft loop (use worker / Update desk) |

### Ensemble and staking (settings)

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENSEMBLE_WEIGHT_POISSON` | 0.45 | Blend weight |
| `ENSEMBLE_WEIGHT_ELO` | 0.35 | Blend weight |
| `ENSEMBLE_WEIGHT_GBM` | 0.20 | Blend weight |
| `INTUITION_MAX_ADJUSTMENT` | 0.08 | Cap on discretionary adjust |
| `CONSENSUS_WEIGHT_BETTORS` | 0.12 | Bettor consensus pull |
| `CONSENSUS_WEIGHT_WEB` | 0.08 | Web consensus pull |
| `KELLY_FRACTION` | 0.25 | Fraction of full Kelly |
| `MIN_EV_THRESHOLD` | 0.02 | Minimum EV to surface a value bet |
| `MIN_CONFIDENCE` | 0.55 | Confidence floor |
| `MAX_STAKE_PCT` | 3.0 | Max % of bankroll |
| `MATCH_MAX_STAKE_PCT` | 50.0 | Max % of per-match budget |
| `DEFAULT_BANKROLL` | 2000 | Paper / UI default |

### Persistence

| Variable | Purpose |
|----------|---------|
| `PORTFOLIO_STORE_PATH` | Override portfolio root |
| `DATABASE_URL` / `TURSO_AUTH_TOKEN` | Optional remote DB |

---

## Runtime architecture

```
Browser (React SPA)
    │  /api/*
    ▼
FastAPI (Uvicorn)
    ├── Auth / sessions
    ├── Events provider (ESPN → Stake overlay → Odds API → demo → model fair)
    ├── Match slip / recs / EV
    ├── Stake odds (overlay → cache → board → demo → model)
    ├── Portfolio (per-user journal, sealed tokens)
    └── Model insights (disk cache + publish_clean + bundled learning merge)
            │
            ├── craft.db (epochs, sport ledger, holdout IDs)
            ├── betting_evolution.db (paired closes)
            ├── model_params.json / craft_nn.joblib
            └── factor_catalog_summary.json (bundled depth)
```

**Boot (cloud):** `start_cloud.sh` starts Uvicorn on `$PORT` immediately. `bootstrap_model.sh` runs in the background. API lifespan starts a single `api-boot` thread: DB init, users bundle, lean board warmup, optional Stake disk cache, insights ensure. Craft auto-loop only if `CRAFT_DISABLE` is unset. Stake browser / odds keepalive only if a live Stake network path is configured.

---

## Product surfaces

| Route | What you get |
|-------|----------------|
| `/` | Landing |
| `/app` | Home boards |
| `/app/sport/:id` | League board, match sheet, Recs / Build / Odds |
| `/app/model` | Desk: glossary, gates, curves, containers |
| `/app/portfolio` | Private journal + Stake token |
| `/app/guide` | Product guide |
| `/app/legal/terms` | Terms (liability, indemnity, as-is) |
| `/app/legal/privacy` | Privacy |
| `/app/account` | Profile / token / privacy toggles |

Odds tab fallback order when Stake is blocked: **Stake overlay → fixture cache → ESPN/board 1X2 → demo books → Elo model fair**. Every response is labeled.

---

## Operational constraints

**Cloudflare / Stake on cloud** — Datacenter IPs often get 403. Fallbacks keep the Odds tab priced and labeled.

**Free-tier memory** — No full `build_model_insights` on the request path. Factors do not rebuild on HTTP. Bundled catalogs and learning fragments ship in the image.

**Cold boards** — Cached priced fixtures when ESPN disk is empty. Demo boards are labeled.

**Soccer craft `n=0`** — Paired soccer closes use synthetic ~1.91 even-money sampling with a high `model_p` floor so the sport can place holdout tickets.

**Client insights cache** — Cache key `gambit_insights_v19` rejects older `cache_version` payloads.

**Honesty** — Below target means below target. Red craft holdout is not painted green without a note.

---

## Repo map

```
src/bet_placer/
  api/server.py          FastAPI routes + lifespan boot
  engine/                EV, advisor, bet builder, stake odds
  ml/                    Elo, craft train/NN/store, insights, desk_quality
  data/                  ESPN, providers, demo events, Stake scraper
  portfolio/             Journal + sealed tokens
  auth/                  Users + sessions
frontend/src/pages/      Model, Portfolio, Guide, Legal, boards
scripts/                 run.sh, start_cloud.sh, bootstrap, checks
DEPLOY.md                Render / Browserbase / secrets
```

Useful checks:

```bash
PYTHONPATH=src python3 scripts/check_stake_odds_fallback.py
```

---

## Run locally

```bash
cp .env.example .env
./scripts/run.sh
```

- App: http://127.0.0.1:5173  
- API: http://127.0.0.1:8000  

Production-style:

```bash
./scripts/run_production.sh
```

Deploy notes: [DEPLOY.md](DEPLOY.md).

---

## Security and liability

- **18+** (or legal age where you live). Age gate on first visit.
- **Not financial advice.** Model outputs can be wrong.
- **You place bets.** Gambit never submits wagers for you.
- **Comply with local law.**
- **Stake tokens:** revocable API token only; never paste your Stake password.
- **No warranty.** See Terms for limitation of liability and indemnity.

I care about this project. I also care that nobody uses it as an excuse to blow a bankroll or ignore the law.

---

## License

Proprietary. See [LICENSE](LICENSE). Copyright (c) 2026 Abhyuday Khanna. All rights reserved. Contact `abhyudayk16@gmail.com` for licensing.
