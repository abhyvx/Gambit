#!/usr/bin/env python3
"""Self-check: Stake login helpers (no live Chrome required)."""
from __future__ import annotations

from bet_placer.data.stake_browser import STAKE_LOGIN_URL, USER_PROBE_QUERY
from bet_placer.portfolio.store import ingest_portfolio_relay, portfolio_relay_export


def main() -> None:
    assert "modal=auth" in STAKE_LOGIN_URL and "tab=login" in STAKE_LOGIN_URL
    assert "user" in USER_PROBE_QUERY
    export = portfolio_relay_export()
    assert "portfolio" in export and "privacy" in export
    out = ingest_portfolio_relay(
        {
            "portfolio": {
                "bets": [],
                "roi_pct": 0,
                "profit_value": 0,
                "total_staked": 0,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "singles_count": 0,
                "parlays_count": 0,
                "display_currency": "USD",
            },
            "privacy": {"portfolio_enabled": True, "risk_acknowledged": True},
            "connection": {"stake_user": {"id": "check", "name": "check"}},
        }
    )
    assert out["connection"]["status"] == "relay"
    assert out["connection"]["connected"] is True
    print("stake_login_check ok")


if __name__ == "__main__":
    main()
