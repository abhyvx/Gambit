from __future__ import annotations

from bet_placer.models.types import Match


class SentimentAnalyzer:
    """
    NLP layer for news, social, and interview sentiment.
    Extension point for News API, Twitter, Reddit integrations.
    """

    def analyze(self, match: Match) -> dict[str, float]:
        # Uses pre-loaded sentiment scores; wire to real NLP pipeline with API keys
        return {
            "home_sentiment": match.sentiment_score_home,
            "away_sentiment": match.sentiment_score_away,
            "divergence": abs(match.sentiment_score_home - match.sentiment_score_away),
        }

    def fetch_and_analyze(self, team: str, league: str) -> float:
        """Placeholder for live news/social scraping."""
        raise NotImplementedError("Connect NEWS_API_KEY or social APIs to enable live sentiment")
