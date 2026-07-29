from __future__ import annotations

from datetime import datetime

from bet_placer.models.types import (
    ChemistrySignals,
    ExternalFactors,
    HeadToHead,
    LeagueProfile,
    Match,
    MarketOdds,
    PlayerStatus,
    RefereeProfile,
    TacticalProfile,
    TeamStats,
)
from bet_placer.models.enums import MarketType, MatchContext


def get_demo_matches() -> list[Match]:
    """Sample matches for demonstration when no live API keys are configured."""
    return [
        _build_liverpool_chelsea(),
        _build_arsenal_man_city(),
    ]


def _build_liverpool_chelsea() -> Match:
    home = TeamStats(
        name="Liverpool",
        goals_scored=2.4,
        goals_conceded=0.9,
        xg=2.1,
        xga=1.0,
        shots=16.2,
        shots_on_target=5.8,
        possession=58.0,
        passing_accuracy=87.0,
        corners=6.5,
        cards=1.8,
        league_position=2,
        form_last_5=["W", "W", "D", "W", "W"],
        form_last_10=["W", "W", "D", "W", "W", "L", "W", "W", "D", "W"],
    )
    away = TeamStats(
        name="Chelsea",
        goals_scored=1.6,
        goals_conceded=1.3,
        xg=1.5,
        xga=1.4,
        shots=13.1,
        shots_on_target=4.2,
        possession=52.0,
        passing_accuracy=84.0,
        corners=5.2,
        cards=2.1,
        league_position=6,
        form_last_5=["W", "L", "W", "D", "W"],
        form_last_10=["W", "L", "W", "D", "W", "W", "L", "D", "W", "L"],
    )
    return Match(
        id="demo-001",
        home_team="Liverpool",
        away_team="Chelsea",
        league="Premier League",
        kickoff=datetime(2026, 6, 21, 16, 30),
        home_stats=home,
        away_stats=away,
        home_tactics=TacticalProfile(
            formation="4-3-3",
            style="high_press",
            avg_possession=58.0,
            press_intensity=8.5,
            transition_speed=8.0,
            set_piece_strength=7.0,
            manager_tenure_matches=180,
            tactical_flexibility=8.0,
        ),
        away_tactics=TacticalProfile(
            formation="4-2-3-1",
            style="possession",
            avg_possession=52.0,
            press_intensity=6.0,
            transition_speed=6.5,
            set_piece_strength=6.0,
            manager_tenure_matches=45,
            tactical_flexibility=7.0,
        ),
        home_players=[
            PlayerStatus("Salah", "RW", goals=18, assists=12, xg=0.65, is_key_player=True, form_rating=8.5),
            PlayerStatus("Van Dijk", "CB", injured=False, is_key_player=True, form_rating=7.8),
            PlayerStatus("Alexander-Arnold", "RB", injured=True, is_key_player=True),
        ],
        away_players=[
            PlayerStatus("Palmer", "CAM", goals=14, assists=8, xg=0.45, is_key_player=True, form_rating=8.2),
            PlayerStatus("Jackson", "ST", goals=10, xg=0.38, is_key_player=True),
            PlayerStatus("Colwill", "CB", suspended=True, is_key_player=True),
        ],
        external=ExternalFactors(
            weather="light_rain",
            temperature_c=12.0,
            wind_speed_kmh=18.0,
            rest_days_home=6,
            rest_days_away=5,
            fixture_congestion_home=0.3,
            fixture_congestion_away=0.45,
            crowd_intensity=9.0,
        ),
        referee=RefereeProfile("Michael Oliver", avg_cards_per_match=3.8, avg_penalties_per_match=0.28, home_bias=0.05),
        league_profile=LeagueProfile(
            name="Premier League",
            avg_goals_per_match=2.85,
            avg_corners=10.2,
            home_advantage_factor=0.11,
            pace=8.0,
        ),
        h2h=HeadToHead(home_wins=4, draws=2, away_wins=1, avg_goals=3.1, recent_results=["H", "H", "D"], btts_rate=0.72, over_25_rate=0.78),
        chemistry=ChemistrySignals(
            morale_home=8.0,
            morale_away=6.5,
            momentum_home=8.5,
            momentum_away=6.0,
            media_pressure_away=7.5,
            notes=["Chelsea missing key CB", "Liverpool unbeaten in 8 at Anfield"],
        ),
        context=MatchContext.DERBY,
        sentiment_score_home=0.35,
        sentiment_score_away=-0.1,
        market_odds=_liverpool_chelsea_odds(),
    )


def _build_arsenal_man_city() -> Match:
    home = TeamStats(
        name="Arsenal",
        goals_scored=2.2,
        goals_conceded=0.8,
        xg=2.0,
        xga=0.9,
        shots=15.0,
        shots_on_target=5.5,
        possession=56.0,
        league_position=1,
        form_last_5=["W", "W", "W", "D", "W"],
    )
    away = TeamStats(
        name="Man City",
        goals_scored=2.5,
        goals_conceded=1.0,
        xg=2.3,
        xga=1.1,
        shots=17.5,
        shots_on_target=6.2,
        possession=62.0,
        league_position=3,
        form_last_5=["W", "W", "L", "W", "W"],
    )
    return Match(
        id="demo-002",
        home_team="Arsenal",
        away_team="Man City",
        league="Premier League",
        kickoff=datetime(2026, 6, 22, 17, 0),
        home_stats=home,
        away_stats=away,
        home_tactics=TacticalProfile(formation="4-3-3", style="high_press", press_intensity=8.0),
        away_tactics=TacticalProfile(formation="4-1-4-1", style="possession", press_intensity=7.5),
        home_players=[
            PlayerStatus("Saka", "RW", goals=12, assists=10, is_key_player=True, form_rating=8.8),
            PlayerStatus("Rice", "CDM", is_key_player=True, form_rating=8.0),
        ],
        away_players=[
            PlayerStatus("Haaland", "ST", goals=22, xg=0.85, is_key_player=True, form_rating=9.0),
            PlayerStatus("De Bruyne", "CM", injured=True, is_key_player=True),
        ],
        external=ExternalFactors(rest_days_home=7, rest_days_away=4, fixture_congestion_away=0.6),
        league_profile=LeagueProfile(name="Premier League", avg_goals_per_match=2.85, home_advantage_factor=0.10),
        h2h=HeadToHead(home_wins=2, draws=3, away_wins=3, avg_goals=2.4, btts_rate=0.55, over_25_rate=0.50),
        chemistry=ChemistrySignals(
            morale_home=8.5,
            morale_away=7.5,
            notes=["Title race implications", "De Bruyne ruled out"],
        ),
        context=MatchContext.TITLE_RACE,
        sentiment_score_home=0.2,
        sentiment_score_away=0.15,
        market_odds=_arsenal_city_odds(),
    )


def _liverpool_chelsea_odds() -> list[MarketOdds]:
    from bet_placer.markets.odds import decimal_to_implied

    def mo(market, sel, line, odds, opening=None):
        return MarketOdds(
            market=market,
            selection=sel,
            line=line,
            best_odds=odds,
            avg_odds=odds * 0.98,
            implied_probability=decimal_to_implied(odds),
            opening_odds=opening,
            bookmaker_count=8,
        )

    return [
        mo(MarketType.MATCH_WINNER, "home", None, 1.75, 1.80),
        mo(MarketType.MATCH_WINNER, "draw", None, 4.00, 3.90),
        mo(MarketType.MATCH_WINNER, "away", None, 4.50, 4.20),
        mo(MarketType.OVER_UNDER_GOALS, "over", 2.5, 1.72, 1.65),
        mo(MarketType.OVER_UNDER_GOALS, "under", 2.5, 2.15, 2.25),
        mo(MarketType.BTTS, "yes", None, 1.62, 1.58),
        mo(MarketType.BTTS, "no", None, 2.30, 2.35),
        mo(MarketType.CORNERS, "over", 9.5, 1.85, 1.90),
        mo(MarketType.CORNERS, "under", 9.5, 1.95, 1.88),
    ]


def _arsenal_city_odds() -> list[MarketOdds]:
    from bet_placer.markets.odds import decimal_to_implied

    def mo(market, sel, line, odds, opening=None):
        return MarketOdds(
            market=market,
            selection=sel,
            line=line,
            best_odds=odds,
            avg_odds=odds * 0.99,
            implied_probability=decimal_to_implied(odds),
            opening_odds=opening,
            bookmaker_count=10,
        )

    return [
        mo(MarketType.MATCH_WINNER, "home", None, 2.60, 2.70),
        mo(MarketType.MATCH_WINNER, "draw", None, 3.50, 3.40),
        mo(MarketType.MATCH_WINNER, "away", None, 2.70, 2.55),
        mo(MarketType.OVER_UNDER_GOALS, "over", 2.5, 1.80, 1.75),
        mo(MarketType.OVER_UNDER_GOALS, "under", 2.5, 2.05, 2.10),
        mo(MarketType.BTTS, "yes", None, 1.70, 1.68),
        mo(MarketType.BTTS, "no", None, 2.15, 2.18),
    ]
