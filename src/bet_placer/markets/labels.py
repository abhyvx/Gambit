"""Label every Stake market option in plain English."""

from __future__ import annotations

import re

from bet_placer.models.enums import MarketType

_STAKE_COMBO_SUFFIX_RE = re.compile(
    r"\s*(?:1x2\s*&\s*)?Total\s*\(90'[^)]*\)\s*$", re.I
)


def _looks_vague_label(label: str) -> bool:
    s = (label or "").strip().lower()
    if not s:
        return True
    if re.match(r"^handicap\b", s):
        return True
    if re.match(r"^[+-]?\d", s):
        return True
    if s in ("yes", "no", "over", "under", "home", "away", "draw"):
        return True
    return False


def _total_unit(line: float | None, sport: str | None = None) -> str:
    """Goals / points / runs — prefer sport when known."""
    sp = (sport or "").lower()
    if sp.startswith("basket") or "nba" in sp or "wnba" in sp:
        return "points"
    if sp.startswith("cricket"):
        return "runs"
    if sp.startswith("soccer") or sp.startswith("football"):
        return "goals"
    if line is None:
        return "goals"
    if line < 20:
        return "goals"
    # Ambiguous mid-band without sport: NBA game ~200–250, T20 match ~150–180, ODI 260+
    if 195 <= line <= 255:
        return "points"
    if line >= 100:
        return "runs"
    if line >= 50:
        return "points"
    return "goals"


def format_market_label(
    market: MarketType | str,
    selection: str,
    line: float | None,
    home: str,
    away: str,
    player: str | None = None,
    sport: str | None = None,
) -> str:
    m = market.value if hasattr(market, "value") else str(market)
    sel = selection
    low = str(sel or "").lower()

    if m == "match_winner":
        if sel in ("home", "draw", "away"):
            return {"home": f"{home} to win", "draw": "Draw", "away": f"{away} to win"}.get(sel, sel)
        if home and sel.lower() == home.lower():
            return f"{home} to win"
        if away and sel.lower() == away.lower():
            return f"{away} to win"
        if sel.lower() == "draw":
            return "Draw"
        if sel and sel.lower() not in ("yes", "no"):
            if " to win" in sel.lower():
                return sel
            return f"{sel} to win"
        return sel
    if m == "double_chance":
        return {
            "home_draw": f"{home} or Draw",
            "home_away": f"{home} or {away}",
            "draw_away": f"Draw or {away}",
        }.get(sel, sel)
    if m == "draw_no_bet":
        team = home if sel == "home" else away
        return f"{team} Draw No Bet" if team else f"{sel.title()} Draw No Bet"
    if m == "over_under_goals":
        ln = line
        if ln is None:
            hit = re.search(r"(?:over|under)\s*([\d.]+)", low)
            if hit:
                ln = float(hit.group(1))
        unit = _total_unit(ln, sport)
        if low in ("home_over", "home_under", "away_over", "away_under"):
            team = home if low.startswith("home") else away
            side = "Over" if low.endswith("over") else "Under"
            if ln is not None:
                return f"{team} {side} {ln} {unit}"
            return f"{team} {side} {unit}"
        side = sel if sel in ("over", "under") else (
            "over" if low.startswith("over") else "under"
        )
        if ln is not None:
            return f"{'Over' if side == 'over' else 'Under'} {ln} {unit}"
        return f"{'Over' if side == 'over' else 'Under'} {unit}"
    if m == "btts":
        return f"Both teams to score — {'Yes' if sel == 'yes' else 'No'}"
    if m == "corners":
        return f"{'Over' if sel == 'over' else 'Under'} {line} Corners"
    if m == "cards":
        return f"{'Over' if sel == 'over' else 'Under'} {line} Cards"
    if m == "half_time":
        return f"Half Time — {home if sel == 'home' else away if sel == 'away' else 'Draw'}"
    if m == "exact_score":
        return f"Correct Score {sel}"
    if m == "asian_handicap":
        team = home if sel == "home" else away if sel == "away" else ""
        sign = f"+{line}" if line and line > 0 else str(line)
        if team:
            return f"{team} handicap {sign}"
        side = "Home" if sel == "home" else "Away" if sel == "away" else "Team"
        return f"{side} handicap {sign}"
    if m == "player_goal":
        return f"{player or selection} Anytime Goalscorer"
    if m == "team_prop":
        return f"{selection}"
    return f"{m}: {sel}" + (f" {line}" if line else "")


def market_category(market: MarketType | str, line: float | None = None, sport: str | None = None) -> str:
    m = market.value if hasattr(market, "value") else str(market)
    if m == "over_under_goals":
        unit = _total_unit(line, sport)
        return {"goals": "Goals", "points": "Totals", "runs": "Runs"}.get(unit, "Totals")
    cats = {
        "match_winner": "Match Result",
        "double_chance": "Match Result",
        "draw_no_bet": "Match Result",
        "btts": "Goals",
        "exact_score": "Goals",
        "half_time": "Half Time",
        "corners": "Corners",
        "cards": "Cards",
        "asian_handicap": "Handicap",
        "player_goal": "Player Props",
        "team_prop": "Team Props",
    }
    return cats.get(m, "Other")


_CORE_BET_MARKETS = frozenset({
    "match_winner", "double_chance", "draw_no_bet",
    "over_under_goals", "btts", "asian_handicap",
    "corners", "cards", "player_goal",
    "half_time", "exact_score", "team_prop", "team_first_goal",
})


def is_core_bet_market(market: str) -> bool:
    """Markets we model and recommend — not exotic Stake props."""
    return str(market or "") in _CORE_BET_MARKETS


def format_leg_label(
    market: str,
    selection: str | None,
    line: float | None,
    home: str,
    away: str,
    raw_label: str | None = None,
) -> str:
    """Plain-English line for a ticket card — never bare 'Yes' or '2nd Half'."""
    m = str(market or "").strip()
    sel = (selection or "").strip()
    low = sel.lower()
    raw = (raw_label or "").strip()

    if is_core_bet_market(m):
        built = format_market_label(
            m, low or sel, line, home, away,
            player=sel if m == "player_goal" else None,
        )
        if not _looks_vague_label(built):
            return built

    ml = m.lower()
    if m == "btts" or "both teams to score" in ml:
        return f"Both teams to score — {'Yes' if low == 'yes' else 'No'}"
    if low in ("over", "under") or raw.lower().startswith(("over ", "under ")):
        ln = line
        if ln is None:
            hit = re.search(r"(\d+(?:\.\d+)?)", raw)
            ln = float(hit.group(1)) if hit else None
        side = low if low in ("over", "under") else (
            "over" if raw.lower().startswith("over") else "under"
        )
        unit = _total_unit(ln)
        if ln is not None:
            return f"{side.title()} {ln} {unit}"
        return f"{side.title()} {unit}"
    if m == "asian_handicap" or "handicap" in ml:
        team = home if low == "home" else away if low == "away" else ""
        if team and line is not None:
            sign = f"+{line}" if line > 0 else str(line)
            return f"{team} handicap {sign}"
        if raw and not _looks_vague_label(raw):
            return raw.replace("Asian Handicap", "handicap").strip()

    if raw and len(raw) > 14 and low not in ("yes", "no", "1st half", "2nd half"):
        if not _looks_vague_label(raw):
            return raw
    if low in ("yes", "no") and ("both" in ml or "btts" in m):
        return f"Both teams to score — {sel.title()}"
    if low in ("1st half", "2nd half"):
        return f"Highest-scoring half — {sel}"
    if raw and not _looks_vague_label(raw):
        return raw
    return f"{m}: {sel}" if sel else m


def format_combo_label(
    raw: str,
    odds: float | None = None,
    home: str = "",
    away: str = "",
    *,
    stake_market: str | None = None,
) -> str:
    """Readable Stake same-game combo — e.g. 'Canada to win & Both teams to score — Yes @ 10x'."""
    from bet_placer.engine.card_coherence import decompose_stake_combo

    s = re.sub(r"\s*@\s*[\d.]+x\s*$", "", (raw or "").strip(), flags=re.I).strip()
    combo = {"label": s, "stake_market": stake_market or "", "selection": s}
    parts = decompose_stake_combo(combo, home, away)
    if len(parts) >= 2:
        labels = [
            format_leg_label(
                p["market"],
                p.get("selection"),
                p.get("line"),
                home,
                away,
                p.get("label"),
            )
            for p in parts
        ]
        body = " & ".join(labels)
        body = re.sub(r"\bto win to win\b", "to win", body, flags=re.I)
        body = re.sub(r"\bmatch_winner:\s*", "", body, flags=re.I)
    else:
        body = _STAKE_COMBO_SUFFIX_RE.sub("", s).strip()
        body = re.sub(r"\bBoth Teams to Score\b", "Both teams to score", body, flags=re.I)
        body = re.sub(r"\bUnder ([\d.]+)\s*&\s*No\b", r"Under \1 goals & Both teams to score — No", body, flags=re.I)
        body = re.sub(r"\bOver ([\d.]+)\s*&\s*Yes\b", r"Over \1 goals & Both teams to score — Yes", body, flags=re.I)
        body = re.sub(r"\s+", " ", body)
    if odds and float(odds) > 1:
        return f"{body} @ {float(odds):g}x"
    return body


def format_combo_parts(leg: dict, home: str, away: str) -> list[str]:
    """Short bullet lines for each leg of a Stake SGM."""
    from bet_placer.engine.card_coherence import decompose_stake_combo

    raw = (leg.get("selection") or "").strip()
    if "&" not in raw:
        raw = re.sub(r"\s*@\s*[\d.]+x\s*$", "", (leg.get("label") or "").strip(), flags=re.I)
    combo = {
        "label": raw,
        "stake_market": leg.get("stake_market") or "",
        "selection": leg.get("selection") or raw,
    }
    parts = decompose_stake_combo(combo, home, away)
    if len(parts) >= 2:
        return [
            format_leg_label(
                p["market"],
                p.get("selection"),
                p.get("line"),
                home,
                away,
                p.get("label"),
            )
            for p in parts
        ]
    if "&" in raw:
        from bet_placer.engine.bet_builder import _sel_side
        out: list[str] = []
        for seg in re.split(r"\s*&\s*", raw):
            seg = seg.strip()
            if not seg:
                continue
            low = seg.lower()
            if low in ("yes", "no"):
                out.append(f"Both teams to score — {seg.title()}")
            elif _sel_side(seg, home, away) in ("home", "away", "draw"):
                team = home if _sel_side(seg, home, away) == "home" else away if _sel_side(seg, home, away) == "away" else "Draw"
                out.append(f"{team} to win" if team != "Draw" else "Draw")
            elif re.search(r"(over|under)\s*[\d.]+", low):
                ou = re.search(r"(over|under)\s*([\d.]+)", low)
                out.append(f"{ou.group(1).title()} {ou.group(2)} goals")
            else:
                out.append(seg)
        return out
    return []


def format_ticket_label(
    leg: dict,
    home: str,
    away: str,
    *,
    with_odds: bool = True,
) -> str:
    """Full ticket line for UI cards."""
    m = str(leg.get("market") or "")
    if m == "stake_combo":
        raw = leg.get("label") or leg.get("stake_market") or "Stake combo"
        return format_combo_label(
            raw,
            leg.get("odds") if with_odds else None,
            home,
            away,
            stake_market=leg.get("stake_market"),
        )
    display = format_leg_label(
        m,
        leg.get("selection"),
        leg.get("line"),
        home,
        away,
        leg.get("label"),
    )
    if with_odds:
        odds = float(leg.get("odds") or 0)
        if odds > 1.01 and " @ " not in display.lower():
            display = f"{display} @ {odds:g}x"
    return display


def format_solo_outcome_label(
    net: float,
    *,
    hits_target: bool = False,
    breaks_even: bool = False,
) -> str:
    """Only surface solo outcome for profit route or break-even insurance."""
    n = float(net or 0)
    if hits_target:
        return f"Wins alone → +₹{int(round(n)):,} profit"
    if breaks_even:
        return "Wins alone → covers stake"
    return ""
