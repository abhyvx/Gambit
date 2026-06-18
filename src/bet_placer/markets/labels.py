"""Label every Stake market option in plain English."""

from __future__ import annotations

from bet_placer.models.enums import MarketType


def format_market_label(
    market: MarketType | str,
    selection: str,
    line: float | None,
    home: str,
    away: str,
    player: str | None = None,
) -> str:
    m = market.value if hasattr(market, "value") else str(market)
    sel = selection

    if m == "match_winner":
        return {"home": f"{home} to Win", "draw": "Draw", "away": f"{away} to Win"}.get(sel, sel)
    if m == "double_chance":
        return {
            "home_draw": f"{home} or Draw",
            "home_away": f"{home} or {away}",
            "draw_away": f"Draw or {away}",
        }.get(sel, sel)
    if m == "draw_no_bet":
        return f"{home if sel == 'home' else away} Draw No Bet"
    if m == "over_under_goals":
        return f"{'Over' if sel == 'over' else 'Under'} {line} Goals"
    if m == "btts":
        return f"Both Teams To Score — {'Yes' if sel == 'yes' else 'No'}"
    if m == "corners":
        return f"{'Over' if sel == 'over' else 'Under'} {line} Corners"
    if m == "cards":
        return f"{'Over' if sel == 'over' else 'Under'} {line} Cards"
    if m == "half_time":
        return f"Half Time — {home if sel == 'home' else away if sel == 'away' else 'Draw'}"
    if m == "exact_score":
        return f"Correct Score {sel}"
    if m == "asian_handicap":
        team = home if sel == "home" else away
        sign = f"+{line}" if line and line > 0 else str(line)
        return f"{team} Asian Handicap {sign}"
    if m == "player_goal":
        return f"{player or selection} Anytime Goalscorer"
    if m == "team_prop":
        return f"{selection}"
    return f"{m}: {sel}" + (f" {line}" if line else "")


def market_category(market: MarketType | str) -> str:
    m = market.value if hasattr(market, "value") else str(market)
    cats = {
        "match_winner": "Match Result",
        "double_chance": "Match Result",
        "draw_no_bet": "Match Result",
        "over_under_goals": "Goals",
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
