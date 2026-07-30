"""Seed demo accounts with positive journals for local/cloud demos.

Passwords are fixed demo credentials (see DEMO_PASSWORDS). Owner admin is not
created here; owners sign up normally and are recognized via is_admin().
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Public demo logins (also listed in Guide). Change only with a coordinated docs update.
DEMO_PASSWORDS = {
    "demo.winner@gambit.test": "DemoWinner12!",
    "demo.builder@gambit.test": "DemoBuilder12!",
    "demo.learner@gambit.test": "DemoLearner12!",
}


def _demo_bet(
    *,
    bid: str,
    home: str,
    away: str,
    selection: str,
    odds: float,
    stake: float,
    result: str,
    sport: str = "soccer",
    market: str = "match_winner",
) -> dict[str, Any]:
    profit = round(stake * (odds - 1), 2) if result == "won" else (-stake if result == "lost" else 0.0)
    payout = round(stake * odds, 2) if result == "won" else (stake if result == "push" else 0.0)
    return {
        "id": bid,
        "fixture_name": f"{home} vs {away}",
        "home": home,
        "away": away,
        "sport": sport,
        "league": "Demo league",
        "market": market,
        "market_family": market,
        "selection": selection,
        "selections": [{"selection": selection, "odds": odds, "fixture_name": f"{home} vs {away}"}],
        "combined_odds": odds,
        "stake": stake,
        "stake_value": stake,
        "currency": "USD",
        "display_currency": "USD",
        "result": result,
        "status": result,
        "profit_value": profit,
        "payout": payout,
        "payout_value": payout,
        "bet_type": "single",
        "selection_count": 1,
        "source": "demo_seed",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400)),
    }


def _winner_portfolio() -> dict[str, Any]:
    bets = [
        _demo_bet(bid="dw1", home="Arsenal", away="Brentford", selection="Arsenal", odds=1.72, stake=100, result="won"),
        _demo_bet(bid="dw2", home="Liverpool", away="Bournemouth", selection="Liverpool", odds=1.55, stake=120, result="won"),
        _demo_bet(bid="dw3", home="Lakers", away="Pistons", selection="Lakers", odds=1.40, stake=80, result="won", sport="basketball"),
        _demo_bet(bid="dw4", home="India", away="Ireland", selection="India", odds=1.35, stake=90, result="won", sport="cricket"),
        _demo_bet(bid="dw5", home="Chelsea", away="Fulham", selection="Draw", odds=3.40, stake=40, result="lost"),
        _demo_bet(bid="dw6", home="Man City", away="Everton", selection="Man City", odds=1.28, stake=150, result="won"),
        _demo_bet(bid="dw7", home="Celtics", away="Wizards", selection="Celtics", odds=1.22, stake=100, result="won", sport="basketball"),
        _demo_bet(bid="dw8", home="Australia", away="Scotland", selection="Australia", odds=1.45, stake=70, result="won", sport="cricket"),
    ]
    return _wrap_portfolio(bets, learning=True)


def _builder_portfolio() -> dict[str, Any]:
    bets = [
        _demo_bet(bid="db1", home="Tottenham", away="Wolves", selection="Tottenham", odds=1.85, stake=60, result="won"),
        _demo_bet(bid="db2", home="Heat", away="Hornets", selection="Heat", odds=1.50, stake=70, result="won", sport="basketball"),
        _demo_bet(bid="db3", home="England", away="Netherlands", selection="England", odds=2.10, stake=50, result="won", sport="cricket"),
        _demo_bet(bid="db4", home="Newcastle", away="Leicester", selection="Over 2.5", odds=1.90, stake=55, result="won", market="totals"),
        _demo_bet(bid="db5", home="Villa", away="Palace", selection="Villa", odds=2.05, stake=45, result="lost"),
        _demo_bet(bid="db6", home="Warriors", away="Kings", selection="Warriors", odds=1.70, stake=65, result="won", sport="basketball"),
    ]
    return _wrap_portfolio(bets, learning=True)


def _learner_portfolio() -> dict[str, Any]:
    bets = [
        _demo_bet(bid="dl1", home="Brighton", away="Southampton", selection="Brighton", odds=1.95, stake=40, result="won"),
        _demo_bet(bid="dl2", home="Nuggets", away="Spurs", selection="Nuggets", odds=1.33, stake=50, result="won", sport="basketball"),
        _demo_bet(bid="dl3", home="Pakistan", away="Zimbabwe", selection="Pakistan", odds=1.40, stake=45, result="won", sport="cricket"),
        _demo_bet(bid="dl4", home="West Ham", away="Ipswich", selection="West Ham", odds=1.80, stake=35, result="won"),
        _demo_bet(bid="dl5", home="Milan", away="Torino", selection="Milan", odds=1.65, stake=40, result="lost"),
    ]
    return _wrap_portfolio(bets, learning=False)


def _wrap_portfolio(bets: list[dict[str, Any]], *, learning: bool) -> dict[str, Any]:
    from bet_placer.portfolio.store import _summarize_bets

    summary = _summarize_bets(bets)
    return {
        "privacy": {
            "portfolio_enabled": True,
            "risk_acknowledged": True,
            "learning_opt_in": learning,
        },
        "connection": {
            "status": "demo",
            "last_sync_status": "confirmed",
            "last_sync_message": "Demo journal with positive sample results.",
            "last_sync_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "portfolio": summary,
    }


def ensure_seed_accounts() -> dict[str, Any]:
    """Create/refresh demo users + positive journals. Safe to call on every boot."""
    import json

    from bet_placer.auth.users import _LOCK, _USERS, _hash_password, _load, _save
    from bet_placer.config import data_path
    from bet_placer.persistence.db import db_enabled, load_portfolio_state, save_portfolio_state

    created = []
    refreshed = []
    with _LOCK:
        users = _load(_USERS)
        specs = [
            ("demo.winner@gambit.test", "Demo Winner", "16a005cbb0d73f39", _winner_portfolio),
            ("demo.builder@gambit.test", "Demo Builder", "0ab2ccb0e9e77030", _builder_portfolio),
            ("demo.learner@gambit.test", "Demo Learner", "f5603721cb1a596f", _learner_portfolio),
        ]
        changed = False
        for email, name, uid, port_fn in specs:
            port = port_fn()
            if email not in users:
                salt, digest = _hash_password(DEMO_PASSWORDS[email])
                users[email] = {
                    "id": uid,
                    "email": email,
                    "name": name,
                    "salt": salt,
                    "password": digest,
                    "created_at": time.time(),
                }
                created.append(email)
                changed = True
            else:
                uid = str(users[email].get("id") or uid)
            # Always rewrite demo journals so P/L stays correct after summarize fixes
            if db_enabled():
                save_portfolio_state(uid, port)
            else:
                path = data_path("portfolios", f"{uid}.json")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(port, indent=2), encoding="utf-8")
            if email not in created:
                refreshed.append(email)
            changed = True
        if changed:
            _save(_USERS, users)
    if created:
        logger.info("Seeded demo accounts: %s", ", ".join(created))
    if refreshed:
        logger.info("Refreshed demo journals: %s", ", ".join(refreshed))
    return {
        "created": created,
        "refreshed": refreshed,
        "passwords": {e: DEMO_PASSWORDS[e] for e in DEMO_PASSWORDS},
    }
