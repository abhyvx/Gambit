"""Version / debugging patch notes for the Admin page.

Append a new entry at the top for each desk revision or debugging cycle so
we can track what was broken and what fixed it. Keep notes short and concrete.
"""

from __future__ import annotations

from typing import Any

# Newest first. version ≈ desk / product revision; cycle = debugging pass.
PATCH_NOTES: list[dict[str, Any]] = [
    {
        "version": "v26",
        "cycle": "events-board-unwedge",
        "at": "2026-07-30",
        "title": "Stop Elo strength work on /api/events so fixtures load again",
        "fixed": [
            "Matches/fixtures boards hung after bundled Elo deploy (single Render worker wedged)",
            "event_to_match ran apply_strength_stats on every board row (hundreds/thousands per paint)",
        ],
        "changes": [
            "Board /events uses with_matches=False; Elo strength only on analyze/predict",
            "Faster Elo table lookup (skip full orphan scan after canon hit)",
        ],
    },
    {
        "version": "v25",
        "cycle": "bundled-elo-cold-start",
        "at": "2026-07-30",
        "title": "Ship Elo in the image; stop empty-cache 51% home priors on Render",
        "fixed": [
            "Prod still showed Hull 51% / Man Utd 21% with flat 1.45/1.20 xG after strength wiring",
            "API booted before bootstrap downloaded model_params.json and cached empty Elo forever",
            "Without Elo every club defaults to rating 50 → home HA → fake 51% favourites",
        ],
        "changes": [
            "bundled_strength.json (Elo + goal_model for soccer/BB/cricket) ships in the Docker image",
            "load_params merges bundled floor, reloads when disk params appear, never pins empty Elo",
            "EloModel refreshes after bootstrap; /api/health exposes elo_teams",
            "check_strength_all_sports covers cold-start without model_params.json",
        ],
    },
    {
        "version": "v24",
        "cycle": "strength-all-sports",
        "at": "2026-07-30",
        "title": "Systemic strength + labels across soccer / basketball / cricket",
        "fixed": [
            "Flat board priors (1.45/1.20 xG) still crowned weak home sides after alias fix",
            "Verdict headlines still showed match_winner: home and em dashes",
            "Stats strip xG stayed on league priors even when Elo knew the gap",
            "Elo updates could re-create orphan name keys and split identity again",
        ],
        "changes": [
            "team_elo.resolve_team_elo + apply_strength_stats wired into event_to_match, Stake map, and analyze",
            "Verdict + analyze copy always humanize picks; strip em dashes before UI",
            "scripts/check_strength_all_sports.py covers Hull/Man Utd, BB, cricket, labels",
            "README documents match-discretion Recs and the strength/prior rule",
        ],
    },
    {
        "version": "v23",
        "cycle": "hull-manutd-recs",
        "at": "2026-07-30",
        "title": "Club Elo aliases; match-discretion Recs; human labels; honest model %",
        "fixed": [
            "Hull City could beat Manchester United on a split Elo identity (manchester united vs man united)",
            "Recs defaulted to Target cashout paths instead of match-by-match picks",
            "Tickets showed match_winner / home instead of team names",
            "Plan hit % (any-leg / to-target) looked like the team's win chance",
            "SGM Add dropped the match-winner leg when only totals/BTTS were priced",
        ],
        "changes": [
            "Club name aliases + Elo merge-on-alias; quality guardrail vs reputation gap",
            "Curated primary prefers singles / loss-min / SGM; Target stays on Target tab",
            "Frontend always humanizes match_winner home/away; shows model win % on tickets",
            "SGM expand keeps winner legs with odds lookup / geometric fallback",
        ],
    },
    {
        "version": "v22",
        "cycle": "paper-craft-gone",
        "at": "2026-07-30",
        "title": "Remove paper_craft Admin spam; fix desk craft zeros",
        "fixed": [
            "Admin activity flooded with paper_craft · 0 settled · PnL ₹0",
            "Nobody knew what paper craft was — it is not the Model desk",
            "Admin craft ROI/accuracy stayed 0 even when desk insights had real numbers",
        ],
        "changes": [
            "paper_craft no longer logs to Admin; stale rows are purged on read",
            "Board paper-book learning stays silent (internal gem weights only)",
            "Admin craft panel always lifts desk ROI/accuracy/epochs from insights when empty",
        ],
    },
    {
        "version": "v21",
        "cycle": "recs-sgm-slip-copy",
        "at": "2026-07-30",
        "title": "Match-discretion recs; full SGM add; clean ticket copy",
        "fixed": [
            "Main Recs still followed Settings goal/risk/structure instead of per-match discretion",
            "3-leg SGM/top path only added 2 legs (totals lines treated as duplicates)",
            "Bet tickets showed snake_case market keys and em dashes",
            "Draw @ high odds could still appear against a home/away lean",
        ],
        "changes": [
            "Main match-slip / Sport / Matches analyze calls omit betting style; engine ignores style for cards",
            "Slip rules are line-aware; SGM combo_parts expand into distinct legs; batch addLegs",
            "Labels and slip UI humanize markets and replace em dashes with plain hyphens",
            "Thesis gate catches Draw labels like Draw @ 7x; UI filters anti-thesis Draw paths",
        ],
    },
    {
        "version": "v20",
        "cycle": "thesis-odds-admin",
        "at": "2026-07-30",
        "title": "No Draw vs home lean; Odds+Pays on slip; Admin craft zeros",
        "fixed": [
            "Target paths could recommend match_winner Draw while the lean was home",
            "Bet slip showed only a bare Nx figure that looked like a payout multiplier",
            "Admin model/craft debug showed trained_on 0, ROI 0, and epoch vs total mismatch",
            "paper_craft activity spam with 0 settled / PnL ₹0",
        ],
        "changes": [
            "Thesis filter hard-rejects Draw (and soft-restore of anti-thesis plans)",
            "Slip/Build show Odds and Pays Nx separately; payout ₹ stays when amount is set",
            "Admin craft uses n_epochs + best/champion/holdout ROI; corpus falls back to insights cache",
            "Empty paper_craft bookkeeping no longer fills the activity log",
        ],
    },
    {
        "version": "v19",
        "cycle": "odds-crash-recs-data",
        "at": "2026-07-30",
        "title": "Odds blank fix, preserve desk data, conviction-first recs",
        "fixed": [
            "Odds tab crashed blank when board-estimate categories used markets/outcomes instead of options",
            "Model desk wiped Stake handles / thinned book depth and compressed container numbers",
            "Admin history corpus / token / portfolio counts showed 0; patch notes easy to miss",
            "Recs preferred high-odds underdogs over sides more likely to win",
        ],
        "changes": [
            "Odds UI accepts both Stake and board shapes; API book fallback includes options",
            "Desk polish keeps max(prior, live) volumes and soft-merges bundled learning",
            "Admin reads report.trained_on_history, connection token flag, portfolio counts from bets",
            "Conviction-first ranking (≥55% chance) across value/build/analyze; emojis removed from UI paths",
        ],
    },
    {
        "version": "v18",
        "cycle": "odds-safe-admin-split",
        "at": "2026-07-30",
        "title": "Safe odds path, craft labels, Admin users split",
        "fixed": [
            "Opening Recs / Odds / Build could blank the app when the API launched browser and died",
            "Request laptop odds sync did not open Stake or confirm when odds landed",
            "Model takeaways still showed stale +0.0% craft and messy Stake dump lines",
            "Container titles used jargon; patch notes sat at the top of Admin; users mixed into overview",
        ],
        "changes": [
            "Match-slip, stake-odds, bet-builder, and stake connect/refresh never launch Playwright on HTTP",
            "Laptop odds request opens Stake.com and polls until relay confirms fixture push",
            "Paper craft targets re-sync after bundled learning; plain-English titles for all desk boxes",
            "Admin Users is its own dashboard; patch notes moved to the bottom",
        ],
    },
    {
        "version": "v17",
        "cycle": "admin-ux-sync-takeaways",
        "at": "2026-07-30",
        "title": "Admin overflow, patch log, laptop sync retry, cleaner takeaways",
        "fixed": [
            "Admin debug cards leaked long paths / errors out of containers",
            "No durable place to read version + debugging cycle notes",
            "Sync Stake failed on cloud when browser session was cold after a first failed import",
            "Model takeaways read as a long messy bullet dump",
        ],
        "changes": [
            "Admin cards wrap/truncate safely; patch notes panel on Admin",
            "Portfolio Sync Stake re-queues sealed token import (laptop relay) when present",
            "Retry import shown on error / queued statuses, not only mid-queue",
            "Takeaways capped to short ranked lines with cleaner layout",
        ],
    },
    {
        "version": "v16",
        "cycle": "demo-auth-admin-oom",
        "at": "2026-07-30",
        "title": "Demo P/L, auth modal, admin OOM, learning-runs removal",
        "fixed": [
            "demo.winner showed −100% ROI despite mostly winning tickets (payout_value missing)",
            "Signup modal closed when selecting all + delete in an input",
            "Admin /accounts loaded every portfolio via export_users_bundle and killed free-tier API",
            "Shallow Learning runs before/after panel with invented milestones",
        ],
        "changes": [
            "Summarize prefers profit_value / payout fallbacks; demo journals refresh on boot",
            "Auth: show/hide password, forgot-password, × + backdrop-only dismiss",
            "Admin accounts endpoint is lightweight; learning-runs panel removed",
            "Owner emails always admin even if GAMBIT_ADMIN_EMAILS empty on Render",
        ],
    },
    {
        "version": "v15",
        "cycle": "desk-learning-readme",
        "at": "2026-07-30",
        "title": "Desk learning pass, README math, cricket gate display",
        "fixed": [
            "Cricket craft holdout painted −18% beside green paired ROI",
            "README LaTeX blocks rendered as raw symbols on GitHub",
            "Client insights cache stuck on older desks",
        ],
        "changes": [
            "Bundled learning desk + publish_clean_desk rescue for green sport cells",
            "README math rewritten in plain English; charts stay on Model page",
            "Insights client cache bumped; guide info links on insight boxes",
        ],
    },
    {
        "version": "v14",
        "cycle": "stake-odds-fallback",
        "at": "2026-07-29",
        "title": "Stake odds fallback + portfolio redesign",
        "fixed": [
            "Odds tab blank when Stake blocked datacenter traffic",
            "Portfolio hard to read; thin journal UX",
        ],
        "changes": [
            "Odds fallback chain: Stake → ESPN/board → demo → model fair (labeled)",
            "Portfolio hero metrics and equity curve polish",
            "Guide / Terms / Privacy surfaces",
        ],
    },
    {
        "version": "v10–v13",
        "cycle": "craft-plateau",
        "at": "2026-07",
        "title": "Craft plateau and three-sport gates",
        "fixed": [
            "Self-improvement best-so-far stuck near ~2%",
            "Soccer even-money craft often n=0",
            "Sport gates inconsistent across soccer / basketball / cricket",
        ],
        "changes": [
            "CraftNet holdout + champion policy; sport ROI gates",
            "Soccer paired-close model_p floor raised for even-money",
            "Desk gate stays Below target until 25% / sport>0 / 60% hit",
        ],
    },
]


def list_patch_notes(limit: int = 24) -> list[dict[str, Any]]:
    return list(PATCH_NOTES[: max(1, int(limit or 24))])
