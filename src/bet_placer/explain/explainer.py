from __future__ import annotations

from bet_placer.models.enums import MarketType
from bet_placer.models.types import Match, ProbabilityEstimate, ValueBet


def explain_bet(
    match: Match,
    bet: ValueBet,
    probabilities: list[ProbabilityEstimate],
    factors: list[str],
) -> str:
    market_label = _market_label(bet.market, bet.selection, bet.line)
    edge_pct = (bet.true_probability - bet.implied_probability) * 100
    ev_pct = bet.expected_value * 100

    parts = [
        f"{market_label} is rated highly with {bet.true_probability:.0%} true probability "
        f"vs {bet.implied_probability:.0%} implied ({edge_pct:+.1f}% edge, EV {ev_pct:+.1f}%).",
    ]

    # Statistical reasons
    h, a = match.home_stats, match.away_stats
    if bet.market in (MarketType.OVER_UNDER_GOALS, MarketType.BTTS):
        combined_xg = (h.xg or h.goals_scored) + (a.xg or a.goals_scored)
        parts.append(
            f"Both teams combine for {combined_xg:.1f} xG per match on average."
        )
        if match.h2h.over_25_rate > 0.6 and bet.market == MarketType.OVER_UNDER_GOALS:
            parts.append(
                f"Historical H2H shows {match.h2h.over_25_rate:.0%} over 2.5 rate "
                f"(avg {match.h2h.avg_goals:.1f} goals)."
            )

    if bet.market == MarketType.MATCH_WINNER:
        if bet.selection == "home":
            parts.append(
                f"{match.home_team} average {h.xg:.1f} xG at home vs "
                f"{match.away_team}'s {a.xga:.1f} xGA away."
            )
        elif bet.selection == "away":
            parts.append(
                f"{match.away_team} attacking output ({a.xg:.1f} xG) may exceed market expectation."
            )

    if bet.market == MarketType.CORNERS:
        total_corners = h.corners + a.corners
        parts.append(f"Combined corner average: {total_corners:.1f} per match.")

    # Injury context
    injured_home = [p.name for p in match.home_players if p.injured or p.suspended]
    injured_away = [p.name for p in match.away_players if p.injured or p.suspended]
    if injured_home or injured_away:
        if injured_home:
            parts.append(f"Home absences: {', '.join(injured_home)}.")
        if injured_away:
            parts.append(f"Away absences: {', '.join(injured_away)} — may weaken defense.")

    # Tactical
    parts.append(
        f"Tactical matchup: {match.home_tactics.style.replace('_', ' ')} vs "
        f"{match.away_tactics.style.replace('_', ' ')}."
    )

    # Referee
    if match.referee and bet.market in (MarketType.OVER_UNDER_GOALS, MarketType.CARDS):
        parts.append(
            f"Referee {match.referee.name} averages {match.referee.avg_cards_per_match:.1f} cards "
            f"and {match.referee.avg_penalties_per_match:.2f} penalties per game."
        )

    # Weather
    if match.external.weather not in ("clear", ""):
        parts.append(f"Weather: {match.external.weather.replace('_', ' ')}.")

    # Intuition factors
    for f in factors[:4]:
        if f not in " ".join(parts):
            parts.append(f)

    # Market inefficiency
    if bet.true_probability > bet.implied_probability + 0.05:
        parts.append("Market odds appear inefficient relative to our composite model.")

    return " ".join(parts)


def _market_label(market: MarketType, selection: str, line: float | None) -> str:
    labels = {
        MarketType.MATCH_WINNER: f"{selection.title()} win",
        MarketType.OVER_UNDER_GOALS: f"{'Over' if selection == 'over' else 'Under'} {line} goals",
        MarketType.BTTS: f"BTTS {'Yes' if selection == 'yes' else 'No'}",
        MarketType.CORNERS: f"Corners {'Over' if selection == 'over' else 'Under'} {line}",
    }
    return labels.get(market, f"{market.value} {selection}")
