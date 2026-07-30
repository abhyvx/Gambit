# Gambit

I built Gambit because I got tired of staring at sportsbooks without a clear read on whether a price was actually good. The site is a three-sport desk for soccer, basketball, and cricket: live boards, priced markets, model grades, a slip you control, a private portfolio journal, and a learning loop that grades its own tickets on frozen holdout data.

Gambit is **not a bookmaker**. It does not place bets for you. It does not move money. You read the desk, you decide, and if you bet at all you do it yourself on a third-party book (Stake or anyone else). Paper metrics on the Model page are research, not a promise that live betting will pay.

If that line feels blunt, good. I would rather people understand the product than get sold a fantasy.

## What it actually does

1. **Boards**  
   Pulls fixtures for soccer, basketball, and cricket. Prefer ESPN when it is up. Overlay Stake prices when a relay or browser path is warm. If both are thin, fall back to cached books or labeled model fair prices so open matches are never blank.

2. **Strength**  
   Team and player ratings from history, finished boards, and sport-specific fuel (club soccer, NBA/ABA, cricket formats). That feeds win probabilities across core markets: match result, totals, handicaps, and related lines.

3. **Prices**  
   Compare model chance to a decimal price. Edge is model probability minus the fair chance implied by the book. Verdicts on tickets are plain language (back / caution / skip), not a black box score.

4. **Slips**  
   Build singles or multis yourself. Amounts are yours. Confirm-only journals work without connecting a book. Optional Stake API token import is for history sync, not auto-betting.

5. **Portfolio**  
   Private journal per account: imported Stake history, confirmed slips, manual past bets. Settled matches update results. Optional opt-in for learning from your graded tickets.

6. **Model desk**  
   Insight boxes across corpus, craft holdout ROI, hit rate, per-sport gates, equity / self-improvement curves, market depth, and factor counts. Craft paper aims at a hard bar (25% overall ROI, every sport above 0%, hit rate at least 60%). Until that bar clears, the desk says **Below target**. It does not pretend to be ready.

## How the stack fits together

| Layer | Choice | Why |
|-------|--------|-----|
| API | FastAPI (Python 3.12) | Typed routes, background workers, one process that can serve the SPA |
| Frontend | React + Vite | Fast boards, slip UX, Model/Portfolio/Guide as first-class pages |
| Ratings / markets | Elo + sport models + craft NN | Honest probabilities before talking about edge |
| Craft learning | SQLite epochs, frozen holdout IDs, sport ledgers | Same matches every epoch so improvement is comparable |
| Boards | ESPN primary, Stake overlay, optional The Odds API | Survive without paid keys; label every price source |
| Auth | PBKDF2 passwords, bearer sessions | Simple, local-first, no “we place bets” surface |
| Secrets | Fernet-sealed Stake tokens (`GAMBIT_SECRETS_KEY`) | Tokens at rest are not plain text when the key is set |
| Deploy | Docker on Render (or any container host) | Bind `$PORT` first, warm data in the background so free-tier boots do not hang |

Repo layout that matters:

- `src/bet_placer/` API, engines, ML, portfolio, auth
- `frontend/` SPA
- `scripts/` local run, cloud start, bootstrap, craft worker
- `DEPLOY.md` production env and Stake/Browserbase notes

## How we deal with the ugly parts

**Cloudflare / Stake on cloud**  
Stake often blocks datacenter IPs. The Odds tab does not go blank: it falls through Stake overlay → fixture cache → ESPN/board 1X2 → demo books → Elo model fair prices. Every fallback is labeled. Live Stake still needs Browserbase, a relay, or a local browser when you want exact book depth.

**Free-tier memory**  
No full model rebuild on the HTTP request path. Insights are served from cache and a publish-clean pass. Factor catalogs ship bundled so a thin host does not OOM rebuilding graphs.

**Cold boards**  
If ESPN disk is empty on a fresh box, priced fixtures are kept from cache when possible. Demo boards exist so the UI still teaches the flow; they are labeled demo, not live books.

**Craft gates lying**  
Soccer closes in the paired store are synthetic even-money (~1.91). An old “favorite 1.30–1.50” sampler returned zero soccer tickets and kept sport gates red forever. Sampling now uses the high-`model_p` even-money slice so soccer, basketball, and cricket can all show honest holdout ROI.

**Client cache lying**  
The Model page used to keep a 24h localStorage desk and never revalidate. Browsers painted Desk v10 after the server had moved on. Client cache now rejects desks below the live revision and revalidates when stale.

**Honesty on the desk**  
Holdout ROI is paper profit on one frozen match set. Champion / best-so-far curves do not fake a decline for drama. Cricket does not hide a red craft holdout behind marketing copy; when craft is green it shows craft, when it is gated the note says so.

## Run locally

```bash
cp .env.example .env
./scripts/run.sh
```

- App: http://127.0.0.1:5173  
- API: http://127.0.0.1:8000  

Production-style local:

```bash
./scripts/run_production.sh
```

Useful optional env (see `.env.example` and `DEPLOY.md`):

- `ODDS_API_KEY` multi-book enricher (optional; boards work without it)
- `STAKE_USE_BROWSER` / Browserbase keys for live Stake depth
- `GAMBIT_SECRETS_KEY` encrypt Stake API tokens at rest
- `GAMBIT_ADMIN_EMAILS` admin roster
- `CRAFT_DISABLE=1` on tiny hosts; train with the craft worker or Update desk when you mean it

## Routes

| Route | Page |
|-------|------|
| `/` | Landing |
| `/app` | Home boards |
| `/app/sport/:id` | Sport board + slip |
| `/app/model` | Model desk |
| `/app/portfolio` | Private journal |
| `/app/guide` | Product guide |
| `/app/legal/terms` | Terms |
| `/app/legal/privacy` | Privacy |
| `/app/account` | Account / Stake token |

## Security and liability (read this)

- **18+** (or legal age where you live). Age gate on first visit.
- **Not financial advice.** Model outputs can be wrong. Past paper ROI does not guarantee live profit.
- **You place bets.** Gambit never submits wagers to a book on your behalf.
- **Comply with local law.** Online gambling is illegal or restricted in many places. That is on you.
- **Stake tokens.** Create a revocable API token in Stake settings. Do not paste your Stake password. Disconnect anytime from Portfolio / Account.
- **No warranty.** Software is as-is. See Terms for limitation of liability and acceptable use.

I care about this project. I also care that nobody uses it as an excuse to blow a bankroll or ignore the law. If you are only here to chase a guaranteed edge, this is the wrong tool.

## Deploy

See [DEPLOY.md](DEPLOY.md) for Render, Browserbase, secrets, and what free tier can and cannot do.
