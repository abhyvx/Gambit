from enum import Enum


class MarketType(str, Enum):
    MATCH_WINNER = "match_winner"
    DOUBLE_CHANCE = "double_chance"
    DRAW_NO_BET = "draw_no_bet"
    OVER_UNDER_GOALS = "over_under_goals"
    BTTS = "btts"
    ASIAN_HANDICAP = "asian_handicap"
    HANDICAP = "handicap"
    CORNERS = "corners"
    CARDS = "cards"
    SHOTS = "shots"
    SHOTS_ON_TARGET = "shots_on_target"
    PLAYER_GOAL = "player_goal"
    PLAYER_ASSIST = "player_assist"
    PLAYER_BOOKING = "player_booking"
    HALF_TIME = "half_time"
    EXACT_SCORE = "exact_score"
    TEAM_PROP = "team_prop"


class Selection(str, Enum):
    HOME = "home"
    AWAY = "away"
    DRAW = "draw"
    OVER = "over"
    UNDER = "under"
    YES = "yes"
    NO = "no"


class MatchContext(str, Enum):
    TITLE_RACE = "title_race"
    RELEGATION = "relegation"
    DERBY = "derby"
    MUST_WIN = "must_win"
    DEAD_RUBBER = "dead_rubber"
    CUP_ROTATION = "cup_rotation"
    NORMAL = "normal"
