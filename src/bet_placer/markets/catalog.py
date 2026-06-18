"""Complete Stake-style market catalog — every bet type we analyze."""

from bet_placer.models.enums import MarketType

# All markets available on Stake sportsbook (soccer)
STAKE_SOCCER_MARKETS = [
    {"type": MarketType.MATCH_WINNER, "name": "Match Winner (1X2)", "selections": ["home", "draw", "away"]},
    {"type": MarketType.DOUBLE_CHANCE, "name": "Double Chance", "selections": ["home_draw", "home_away", "draw_away"]},
    {"type": MarketType.DRAW_NO_BET, "name": "Draw No Bet", "selections": ["home", "away"]},
    {"type": MarketType.OVER_UNDER_GOALS, "name": "Total Goals", "lines": [0.5, 1.5, 2.5, 3.5, 4.5]},
    {"type": MarketType.BTTS, "name": "Both Teams To Score", "selections": ["yes", "no"]},
    {"type": MarketType.ASIAN_HANDICAP, "name": "Asian Handicap", "lines": [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]},
    {"type": MarketType.CORNERS, "name": "Total Corners", "lines": [8.5, 9.5, 10.5, 11.5]},
    {"type": MarketType.CARDS, "name": "Total Cards", "lines": [2.5, 3.5, 4.5, 5.5]},
    {"type": MarketType.HALF_TIME, "name": "Half Time Result", "selections": ["home", "draw", "away"]},
    {"type": MarketType.EXACT_SCORE, "name": "Correct Score", "scores": ["1-0", "2-0", "2-1", "1-1", "0-0", "0-1", "1-2", "0-2", "3-1", "2-2", "3-2"]},
]

MARKET_COUNT = sum(
    len(m.get("selections", [])) + len(m.get("lines", [])) * 2 + len(m.get("scores", []))
    for m in STAKE_SOCCER_MARKETS
)
