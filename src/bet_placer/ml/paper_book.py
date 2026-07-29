"""Paper betting book — place match gems under a bankroll, grade, improve.

Trains and bets on live ESPN boards (soccer / basketball / cricket) — not
a finished World Cup archive. Walk-forward on recent completed fixtures,
then place open tickets on upcoming/live games and settle as scores land.
Ledger: ~/.bet_placer/paper_book.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bet_placer.config import data_path
from bet_placer.ml.gem_craft import (
    MAX_GEMS_PER_MATCH,
    spot_match_gems,
    update_craft_weights_from_tickets,
)

BOOK_PATH = data_path("paper_book.json")
DEFAULT_BANKROLL = 10_000.0
DEFAULT_MATCH_BUDGET = 200.0
BOARD_KEYS = ("soccer_all", "basketball_all", "cricket_all")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_book(bankroll: float = DEFAULT_BANKROLL) -> dict[str, Any]:
    return {
        "version": 2,
        "source": "espn_boards",
        "starting_bankroll": float(bankroll),
        "bankroll": float(bankroll),
        "match_budget": DEFAULT_MATCH_BUDGET,
        "tickets": [],
        "curve": [{"t": _now(), "bankroll": float(bankroll)}],
        "updated_at": _now(),
    }


def load_book() -> dict[str, Any]:
    try:
        if BOOK_PATH.exists():
            return json.loads(BOOK_PATH.read_text())
    except Exception:
        pass
    return _empty_book()


def save_book(book: dict[str, Any]) -> None:
    BOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    book["updated_at"] = _now()
    BOOK_PATH.write_text(json.dumps(book, indent=2))


def summarize(book: dict[str, Any] | None = None) -> dict[str, Any]:
    book = book or load_book()
    tickets = book.get("tickets") or []
    settled = [t for t in tickets if t.get("status") in ("won", "lost", "void")]
    open_t = [t for t in tickets if t.get("status") == "open"]
    wins = [t for t in settled if t.get("status") == "won"]
    losses = [t for t in settled if t.get("status") == "lost"]
    staked = sum(float(t.get("stake") or 0) for t in settled if t.get("status") != "void")
    pnl = sum(float(t.get("pnl") or 0) for t in settled)
    graded = [t for t in settled if t.get("status") in ("won", "lost")]
    acc = (len(wins) / len(graded)) if graded else None
    by_kind: dict[str, dict[str, float]] = {}
    by_market: dict[str, dict[str, float]] = {}
    by_sport: dict[str, dict[str, float]] = {}
    by_selection: dict[str, dict[str, float]] = {}
    for t in graded:
        sel_key = f"{(t.get('market') or 'other').lower()}::{(t.get('selection') or t.get('label') or '?')}"
        for bucket, key in (
            (by_kind, t.get("gem_kind") or "single"),
            (by_market, (t.get("market") or "other").lower()),
            (by_sport, t.get("sport") or "unknown"),
            (by_selection, sel_key),
        ):
            row = bucket.setdefault(key, {"n": 0, "hits": 0, "pnl": 0.0})
            row["n"] += 1
            row["hits"] += 1 if t.get("status") == "won" else 0
            row["pnl"] += float(t.get("pnl") or 0)
    for bucket in (by_kind, by_market, by_sport, by_selection):
        for row in bucket.values():
            row["hit_rate"] = round(row["hits"] / row["n"], 3) if row["n"] else None
            row["pnl"] = round(row["pnl"], 2)
    start = float(book.get("starting_bankroll") or DEFAULT_BANKROLL)
    bank = float(book.get("bankroll") or start)
    return {
        "bankroll": round(bank, 2),
        "starting_bankroll": round(start, 2),
        "pnl": round(bank - start, 2),
        "roi": round((bank - start) / start, 4) if start else None,
        "tickets": len(tickets),
        "open": len(open_t),
        "settled": len(settled),
        "wins": len(wins),
        "losses": len(losses),
        "accuracy": round(acc, 3) if acc is not None else None,
        "staked": round(staked, 2),
        "settled_pnl": round(pnl, 2),
        "by_kind": by_kind,
        "by_market": by_market,
        "by_sport": by_sport,
        "by_selection": by_selection,
        "source": book.get("source") or "espn_boards",
        "updated_at": book.get("updated_at"),
        "curve": (book.get("curve") or [])[-40:],
    }


def _ticket_id(match_id: str, gem: dict) -> str:
    line = gem.get("line")
    return (
        f"{match_id}|{(gem.get('market') or '')}|"
        f"{(gem.get('selection') or gem.get('label') or '')}|{line}"
    )


def _size_gems(gems: list[dict], match_budget: float) -> list[dict]:
    from bet_placer.engine.bankroll import allocate_match_budget

    picks = []
    for g in gems:
        picks.append({
            **g,
            "true_probability": g.get("our_probability") or 0.5,
            "decimal_odds": g.get("odds") or g.get("decimal_odds") or 1.9,
            "expected_value": max(0.0, float(g.get("gem_score") or 0) - 1.0) * 0.05,
        })
    return allocate_match_budget(picks, match_budget, spend_pct=0.85)


def _place_gems(
    book: dict,
    *,
    match_id: str,
    home: str,
    away: str,
    gems: list[dict],
    match_budget: float,
    status: str = "open",
    hs: int | None = None,
    aws: int | None = None,
    sport: str | None = None,
) -> int:
    """Place sized gems. If hs/aws given and status settled, grade immediately."""
    if not gems:
        return 0
    existing = {
        t.get("id") or _ticket_id(t.get("match_id") or match_id, t)
        for t in book.get("tickets") or []
    }
    sized = _size_gems(gems, match_budget)
    placed = 0
    bank = float(book.get("bankroll") or 0)
    for g in sized:
        tid = _ticket_id(match_id, g)
        if tid in existing:
            continue
        stake = float(
            g.get("stake_inr")
            or (g.get("stake_recommendation") or {}).get("recommended_stake")
            or 0
        )
        if stake <= 0 or stake > bank:
            continue
        odds = float(g.get("odds") or g.get("decimal_odds") or 0)
        if odds <= 1.0:
            odds = 1.85  # ponytail: missing book price → soft placeholder for paper P&L
        ticket = {
            "id": tid,
            "match_id": match_id,
            "home": home,
            "away": away,
            "sport": sport or g.get("sport"),
            "market": (g.get("market") or "").lower(),
            "selection": g.get("selection") or g.get("label"),
            "label": g.get("label") or g.get("selection"),
            "line": g.get("line"),
            "odds": odds,
            "stake": stake,
            "gem_kind": g.get("gem_kind"),
            "gem_score": g.get("gem_score"),
            "gem_why": g.get("gem_why"),
            "our_probability": g.get("our_probability"),
            "placed_at": _now(),
            "status": "open",
        }
        bank -= stake
        if status == "settled" and hs is not None and aws is not None:
            _settle_ticket(ticket, home=home, away=away, hs=hs, aws=aws)
            bank += float(ticket.get("return_inr") or 0)
        book.setdefault("tickets", []).append(ticket)
        existing.add(tid)
        placed += 1
    book["bankroll"] = round(bank, 2)
    return placed


def _settle_ticket(ticket: dict, *, home: str, away: str, hs: int, aws: int) -> None:
    from bet_placer.ml.rec_grading import grade_leg

    hit = grade_leg(ticket, home=home, away=away, hs=hs, aws=aws)
    stake = float(ticket.get("stake") or 0)
    odds = float(ticket.get("odds") or 0)
    if hit is None:
        ticket["status"] = "void"
        ticket["pnl"] = 0.0
        ticket["return_inr"] = stake
        ticket["hit"] = None
    elif hit:
        ret = round(stake * odds, 2)
        ticket["status"] = "won"
        ticket["return_inr"] = ret
        ticket["pnl"] = round(ret - stake, 2)
        ticket["hit"] = True
    else:
        ticket["status"] = "lost"
        ticket["return_inr"] = 0.0
        ticket["pnl"] = round(-stake, 2)
        ticket["hit"] = False
    ticket["settled_at"] = _now()
    ticket["score"] = f"{hs}-{aws}"


def _sport_bucket(sport_key: str) -> str:
    if sport_key.startswith("basketball"):
        return "basketball"
    if sport_key.startswith("cricket"):
        return "cricket"
    return "soccer"


def _iter_board_events() -> list[dict[str, Any]]:
    from bet_placer.data.espn_leagues import fetch_espn_events

    rows: list[dict[str, Any]] = []
    for key in BOARD_KEYS:
        try:
            events = fetch_espn_events(key)
        except Exception:
            continue
        sport = _sport_bucket(key)
        for e in events or []:
            hs, aws = e.get("home_score"), e.get("away_score")
            # Cricket / two-way boards: ESPN winner flag when run totals won't parse
            if hs is None or aws is None:
                if e.get("home_winner") and not e.get("away_winner"):
                    hs, aws = 1, 0
                elif e.get("away_winner") and not e.get("home_winner"):
                    hs, aws = 0, 1
            rows.append({
                "sport_key": key,
                "sport": sport,
                "id": e.get("id") or f"{sport}-{e.get('home_team')}-{e.get('away_team')}",
                "home": e.get("home_team") or "",
                "away": e.get("away_team") or "",
                "status": (e.get("status") or "").lower(),
                "hs": hs,
                "aws": aws,
                "kickoff": e.get("commence_time") or "",
                "league": e.get("sport_title") or sport,
                "raw": e,
            })
    return rows


def _team_key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


_BOARD_SCORE_CACHE: tuple[float, dict, dict] | None = None
_BOARD_SCORE_TTL = 90.0


def _board_score_index() -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    global _BOARD_SCORE_CACHE
    import time as _time

    now = _time.time()
    if _BOARD_SCORE_CACHE and now - _BOARD_SCORE_CACHE[0] < _BOARD_SCORE_TTL:
        return _BOARD_SCORE_CACHE[1], _BOARD_SCORE_CACHE[2]

    by_id: dict[str, dict] = {}
    by_pair: dict[tuple[str, str], dict] = {}
    for row in _iter_board_events():
        if row["status"] != "completed" or row["hs"] is None or row["aws"] is None:
            continue
        by_id[row["id"]] = row
        by_pair[(row["home"], row["away"])] = row
        by_pair[(_team_key(row["home"]), _team_key(row["away"]))] = row
    _BOARD_SCORE_CACHE = (now, by_id, by_pair)
    return by_id, by_pair


def lookup_finished_score(
    *,
    match_id: str | None = None,
    home: str | None = None,
    away: str | None = None,
    by_id: dict | None = None,
    by_pair: dict | None = None,
) -> dict | None:
    """Find a completed board row by match id or home/away (exact then normalized)."""
    if by_id is None or by_pair is None:
        by_id, by_pair = _board_score_index()
    if match_id and match_id in by_id:
        return by_id[match_id]
    if home and away:
        hit = by_pair.get((home, away)) or by_pair.get((_team_key(home), _team_key(away)))
        if hit:
            return hit
    return None


def settle_open(book: dict | None = None) -> dict[str, Any]:
    """Grade open tickets whose ESPN board fixtures have finished."""
    book = book or load_book()
    by_id, by_pair = _board_score_index()
    settled_n = 0
    bank = float(book.get("bankroll") or 0)
    for t in book.get("tickets") or []:
        if t.get("status") != "open":
            continue
        row = lookup_finished_score(
            match_id=t.get("match_id"),
            home=t.get("home"),
            away=t.get("away"),
            by_id=by_id,
            by_pair=by_pair,
        )
        if not row:
            continue
        hs, aws = int(row["hs"]), int(row["aws"])
        _settle_ticket(
            t,
            home=t.get("home") or row["home"],
            away=t.get("away") or row["away"],
            hs=hs,
            aws=aws,
        )
        bank += float(t.get("return_inr") or 0)
        settled_n += 1
    book["bankroll"] = round(bank, 2)
    if settled_n:
        book.setdefault("curve", []).append({"t": _now(), "bankroll": book["bankroll"]})
    save_book(book)
    return {"settled": settled_n, "summary": summarize(book)}


def apply_paper_learning(params: dict | None = None, book: dict | None = None) -> dict:
    """Blend paper craft weights into model params from board results."""
    from bet_placer.ml.activity_log import log_activity
    from bet_placer.ml.params import load_params, save_params

    params = params or load_params(force=True)
    book = book or load_book()
    summary = summarize(book)
    weights = update_craft_weights_from_tickets(book.get("tickets") or [])
    craft = {
        "version": 2,
        "source": "espn_boards",
        "weights": weights,
        "summary": {
            "accuracy": summary.get("accuracy"),
            "pnl": summary.get("pnl"),
            "roi": summary.get("roi"),
            "tickets": summary.get("tickets"),
            "settled": summary.get("settled"),
            "by_kind": summary.get("by_kind"),
            "by_market": summary.get("by_market"),
            "by_sport": summary.get("by_sport"),
        },
        "updated_at": _now(),
    }
    params["craft_learning"] = craft

    rec = dict(params.get("rec_learning") or {})
    sw = dict(rec.get("strategy_weights") or {})
    kind = summary.get("by_kind") or {}
    if kind.get("easy_money", {}).get("n", 0) >= 3:
        rate = kind["easy_money"].get("hit_rate") or 0.5
        sw["singles_focus"] = round(
            max(0.5, min(1.4, (sw.get("singles_focus") or 1.0) * (0.85 + 0.3 * rate))), 3,
        )
    if kind.get("niche", {}).get("n", 0) >= 3:
        rate = kind["niche"].get("hit_rate") or 0.5
        sw["value"] = round(
            max(0.5, min(1.4, (sw.get("value") or 1.0) * (0.85 + 0.3 * rate))), 3,
        )
        sw["match_card"] = round(
            max(0.5, min(1.4, (sw.get("match_card") or 1.0) * (0.9 + 0.2 * rate))), 3,
        )
    if sw:
        rec["strategy_weights"] = sw
        rec["paper_blend_at"] = _now()
        params["rec_learning"] = rec

    save_params(params)
    log_activity(
        "paper_craft",
        (
            f"Paper book (live boards): {summary.get('settled', 0)} settled · "
            f"acc {summary.get('accuracy')} · PnL ₹{summary.get('pnl')}"
        ),
        detail={
            "accuracy": summary.get("accuracy"),
            "pnl": summary.get("pnl"),
            "roi": summary.get("roi"),
            "craft_weights": weights,
            "strategy_weights": sw,
            "by_sport": summary.get("by_sport"),
        },
    )
    return params


def _model_events_for_board(row: dict) -> list[tuple[str, str, float]]:
    """Deep multi-market probs for this board fixture (all three sports)."""
    from bet_placer.data.odds_api import event_to_match
    from bet_placer.engine.all_markets import predict_all_markets
    from bet_placer.models.enums import MarketType

    match = event_to_match(row["raw"], row["sport_key"])
    estimates = predict_all_markets(match)
    events: list[tuple[str, str, float]] = []
    for e in estimates:
        m = e.market
        p = float(e.probability)
        sel = e.selection
        if m == MarketType.MATCH_WINNER:
            if row["sport"] != "soccer" and sel == "draw":
                continue
            events.append(("result", sel, p))
        elif m == MarketType.BTTS:
            events.append(("btts", sel, p))
        elif m == MarketType.OVER_UNDER_GOALS:
            line = e.line
            if line is None:
                continue
            # Keep selection as over/under/home_over/… — line travels separately
            events.append(("totals", str(sel), p, float(line)))
        elif m in (MarketType.ASIAN_HANDICAP, MarketType.DRAW_NO_BET):
            line = e.line
            tag = f"{sel}" if line is None else f"{sel}_{line}"
            events.append(("handicap", tag, p))
    # Flatten 4-tuples (totals with line) back to 3-tuples for gem spotter
    flat: list[tuple[str, str, float]] = []
    for row in events:
        if len(row) == 4:
            grp, sel, p, line = row  # type: ignore[misc]
            flat.append((grp, f"{sel}|{line}", p))
        else:
            flat.append(row)  # type: ignore[arg-type]
    events = flat
    if events:
        return events

    # Fallback: board Elo 2-way if predict path empty
    from bet_placer.data.team_names import canon_team
    from bet_placer.ml.board_train import _predict
    from bet_placer.ml.params import load_params

    sport = row["sport"]
    params = load_params()
    ratings = dict((params.get("elo_by_sport") or {}).get(sport) or {})
    hist = (params.get("sport_history") or {}).get("elo") or {}
    if isinstance(hist, dict):
        for k, v in (hist.get(sport) or {}).items():
            ratings.setdefault(k, v)
    probs = _predict(ratings, canon_team(row["home"]), canon_team(row["away"]), sport)
    return [
        ("result", "home", float(probs["home"])),
        ("result", "away", float(probs["away"])),
    ]


def _gems_for_board(row: dict, *, craft_w: dict, full_slip: bool = False) -> tuple[list[dict], dict]:
    from bet_placer.ml.gem_craft import spot_gems_from_events

    meta = {
        "match_id": row["id"],
        "home": row["home"],
        "away": row["away"],
        "hs": row.get("hs"),
        "aws": row.get("aws"),
        "sport": row["sport"],
        "league": row.get("league"),
    }
    if not row["home"] or not row["away"]:
        return [], {}

    if full_slip and row["sport"] == "soccer":
        try:
            from bet_placer.data.odds_api import event_to_match
            from bet_placer.engine.all_markets import predict_all_markets
            from bet_placer.engine.bet_builder import _match_thesis, build_match_flat_board
            from bet_placer.engine.match_slip import build_match_slip, serialize_slip
            from bet_placer.engine.smart_picks import align_slip_with_picks, build_smart_picks
            from bet_placer.intuition.analyst import AnalystIntuition
            from bet_placer.math.normalize import normalize_estimates
            from bet_placer.models.enums import MarketType

            match = event_to_match(row["raw"], row["sport_key"])
            adjusted = normalize_estimates(
                AnalystIntuition().adjust_probabilities(match, predict_all_markets(match))
            )
            ctx = {"status": "upcoming", "grading_replay": True, "stake_priced": False}
            flat, src = build_match_flat_board(
                match, adjusted, DEFAULT_MATCH_BUDGET, ctx, row["home"], row["away"],
                launch_browser=False,
            )
            ctx["_flat_board"] = flat
            ctx["_board_source"] = src
            mw = {
                p.selection: p.probability
                for p in adjusted if p.market == MarketType.MATCH_WINNER
            }
            thesis = _match_thesis(flat, row["home"], row["away"], model_probs=mw)
            unified = build_smart_picks(
                flat, row["home"], row["away"], match, adjusted, ctx, thesis=thesis,
            )
            ctx["unified_picks"] = unified.get("unified_picks") or []
            ctx["match_thesis"] = thesis
            slip = build_match_slip(
                row["id"], f"{row['home']} vs {row['away']}", row["home"], row["away"],
                match, adjusted, DEFAULT_MATCH_BUDGET, ctx, {"verdict": "BET"},
            )
            slip_data = align_slip_with_picks(serialize_slip(slip), unified)
            gems = spot_match_gems(
                unified=unified, slip_data=slip_data, flat=flat,
                craft_weights=craft_w, max_gems=MAX_GEMS_PER_MATCH,
            )
            return gems, meta
        except Exception:
            pass

    try:
        events = _model_events_for_board(row)
    except Exception:
        return [], {}
    gems = spot_gems_from_events(events, craft_weights=craft_w, max_gems=MAX_GEMS_PER_MATCH)
    return gems, meta


def run_paper_walkforward(
    *,
    bankroll: float = DEFAULT_BANKROLL,
    match_budget: float = DEFAULT_MATCH_BUDGET,
    max_games: int | None = 60,
    reset: bool = True,
    full_slip: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Paper book on recent finished ESPN board games (soccer / BB / cricket)."""
    from bet_placer.ml.gem_craft import load_craft_weights

    finished = [
        r for r in _iter_board_events()
        if r["status"] == "completed" and r["hs"] is not None and r["aws"] is not None
    ]
    finished.sort(key=lambda r: r.get("kickoff") or "")
    if max_games:
        finished = finished[-max(1, int(max_games)):]

    book = _empty_book(bankroll) if reset else load_book()
    book["match_budget"] = match_budget
    book["starting_bankroll"] = float(book.get("starting_bankroll") or bankroll)
    book["source"] = "espn_boards"
    if reset:
        book["bankroll"] = float(bankroll)
        book["tickets"] = []
        book["curve"] = [{"t": _now(), "bankroll": float(bankroll)}]

    craft_w = load_craft_weights()
    placed_total = 0
    for i, row in enumerate(finished):
        gems, meta = _gems_for_board(row, craft_w=craft_w, full_slip=full_slip)
        if not gems or not meta:
            if verbose:
                print(f"[paper] skip {row['sport']} {row['home']} vs {row['away']}")
            continue
        n = _place_gems(
            book,
            match_id=meta["match_id"],
            home=meta["home"],
            away=meta["away"],
            gems=gems,
            match_budget=match_budget,
            status="settled",
            hs=int(meta["hs"]),
            aws=int(meta["aws"]),
            sport=meta.get("sport"),
        )
        placed_total += n
        book.setdefault("curve", []).append({
            "t": _now(), "bankroll": book["bankroll"], "match": meta["match_id"],
        })
        if (i + 1) % 10 == 0:
            craft_w = update_craft_weights_from_tickets(book.get("tickets") or [])
            if verbose:
                print(f"[paper] mid-learn after {i+1} games · bank ₹{book['bankroll']:.0f}")

    craft_w = update_craft_weights_from_tickets(book.get("tickets") or [])
    save_book(book)
    params = apply_paper_learning(book=book)
    summary = summarize(book)
    if verbose:
        print(
            f"[paper] boards: {placed_total} bets on {len(finished)} games · "
            f"acc={summary.get('accuracy')} pnl=₹{summary.get('pnl')} · {summary.get('by_sport')}"
        )
    return {
        "placed": placed_total,
        "games": len(finished),
        "source": "espn_boards",
        "full_slip": full_slip,
        "summary": summary,
        "craft_weights": craft_w,
        "params_craft": (params.get("craft_learning") or {}).get("summary"),
    }


def place_upcoming(
    *,
    match_budget: float | None = None,
    max_matches: int = 24,
    full_slip: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Spot gems on live/upcoming ESPN fixtures and park open paper tickets."""
    from bet_placer.ml.gem_craft import load_craft_weights

    book = load_book()
    budget = float(match_budget or book.get("match_budget") or DEFAULT_MATCH_BUDGET)
    craft_w = load_craft_weights()
    open_rows = [
        r for r in _iter_board_events()
        if r["status"] in ("upcoming", "live", "scheduled") and r["home"] and r["away"]
    ]
    open_rows.sort(key=lambda r: r.get("kickoff") or "")
    per_sport: dict[str, int] = {}
    selected: list[dict] = []
    cap = max(4, max_matches // 3)
    for r in open_rows:
        sp = r["sport"]
        if per_sport.get(sp, 0) >= cap:
            continue
        selected.append(r)
        per_sport[sp] = per_sport.get(sp, 0) + 1
        if len(selected) >= max_matches:
            break

    placed = 0
    for row in selected:
        if float(book.get("bankroll") or 0) < 50:
            break
        gems, meta = _gems_for_board(row, craft_w=craft_w, full_slip=full_slip)
        if not gems or not meta:
            continue
        n = _place_gems(
            book,
            match_id=meta["match_id"],
            home=meta["home"],
            away=meta["away"],
            gems=gems,
            match_budget=min(budget, float(book.get("bankroll") or 0)),
            status="open",
            sport=meta.get("sport"),
        )
        placed += n
        if verbose and n:
            print(f"[paper] open {n} on {row['sport']} {row['home']} vs {row['away']}")

    if placed:
        book.setdefault("curve", []).append({"t": _now(), "bankroll": book["bankroll"]})
    save_book(book)
    return {
        "placed": placed,
        "matches": len(selected),
        "by_sport": per_sport,
        "summary": summarize(book),
    }


def run_cycle(
    *,
    train_walkforward: bool = False,
    bankroll: float = DEFAULT_BANKROLL,
    match_budget: float = DEFAULT_MATCH_BUDGET,
    max_games: int | None = 60,
    place_live: bool = True,
    full_slip: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Improve loop on live boards: walkforward → settle → place upcoming → learn."""
    out: dict[str, Any] = {}
    if train_walkforward:
        out["walkforward"] = run_paper_walkforward(
            bankroll=bankroll,
            match_budget=match_budget,
            max_games=max_games,
            reset=True,
            full_slip=full_slip,
            verbose=verbose,
        )
    out["settle"] = settle_open()
    if place_live:
        out["place"] = place_upcoming(
            match_budget=match_budget, full_slip=full_slip, verbose=verbose,
        )
    apply_paper_learning()
    out["summary"] = summarize()
    return out
