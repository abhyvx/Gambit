"""Version / debugging patch notes for the Admin page.

Append a new entry at the top for each desk revision or debugging cycle so
we can track what was broken and what fixed it. Keep notes short and concrete.
"""

from __future__ import annotations

from typing import Any

# Newest first. version ≈ desk / product revision; cycle = debugging pass.
PATCH_NOTES: list[dict[str, Any]] = [
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
