"""Version / debugging patch notes for the Admin page.

Append a new entry at the top for each desk revision or debugging cycle so
we can track what was broken and what fixed it. Keep notes short and concrete.
"""

from __future__ import annotations

from typing import Any

# Newest first. version ≈ desk / product revision; cycle = debugging pass.
PATCH_NOTES: list[dict[str, Any]] = [
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
