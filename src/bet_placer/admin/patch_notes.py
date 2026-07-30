"""Version / debugging patch notes for the Admin page.

Append a new entry at the top for each desk revision or debugging cycle so
we can track what was broken and what fixed it. Keep notes short and concrete.
"""

from __future__ import annotations

from typing import Any

# Newest first. version ≈ desk / product revision; cycle = debugging pass.
PATCH_NOTES: list[dict[str, Any]] = [
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
