"""Internet consensus from Reddit and public prediction sources."""

from __future__ import annotations

import re
from collections import Counter

import requests

from bet_placer.config import get_settings
from bet_placer.models.stake_types import WebConsensus


REDDIT_SUBREDDITS = ("soccerbetting", "sportsbook", "football")


class WebConsensusFetcher:
    """
    Gathers public prediction consensus from Reddit JSON API.
    Does NOT blindly follow consensus — flags when to fade public.
    """

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "bet-placer/0.1 (research bot)"

    def fetch(self, home: str, away: str, league: str = "") -> WebConsensus:
        query = f"{home} vs {away}"
        snippets: list[str] = []
        sources: list[str] = []

        for sub in REDDIT_SUBREDDITS:
            posts = self._reddit_search(sub, query)
            for post in posts:
                snippets.append(post["text"])
                sources.append(post["url"])

        if not snippets:
            return WebConsensus(
                fixture_name=f"{home} vs {away}",
                home_pick_pct=0.33,
                draw_pick_pct=0.33,
                away_pick_pct=0.33,
                over_25_pct=0.5,
                btts_yes_pct=0.5,
                source_count=0,
                confidence=0.0,
                dominant_narrative="No public consensus data found — relying on model only",
            )

        picks = self._extract_picks(snippets, home, away)
        total = sum(picks.values()) or 1
        home_pct = picks.get("home", 0) / total
        draw_pct = picks.get("draw", 0) / total
        away_pct = picks.get("away", 0) / total
        over_pct = picks.get("over", 0) / max(picks.get("over", 0) + picks.get("under", 0), 1)
        btts_pct = picks.get("btts_yes", 0) / max(picks.get("btts_yes", 0) + picks.get("btts_no", 0), 1)

        dominant = self._dominant_narrative(home, away, home_pct, away_pct, over_pct)
        fade = max(home_pct, away_pct, draw_pct) > 0.72

        return WebConsensus(
            fixture_name=f"{home} vs {away}",
            home_pick_pct=home_pct,
            draw_pick_pct=draw_pct,
            away_pick_pct=away_pct,
            over_25_pct=over_pct if picks.get("over") or picks.get("under") else 0.5,
            btts_yes_pct=btts_pct if picks.get("btts_yes") or picks.get("btts_no") else 0.5,
            source_count=len(snippets),
            confidence=min(0.9, len(snippets) / 10),
            dominant_narrative=dominant,
            sources=sources[:5],
            fade_public=fade,
        )

    def _reddit_search(self, subreddit: str, query: str) -> list[dict]:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        try:
            r = self.session.get(
                url,
                params={"q": query, "restrict_sr": "on", "sort": "relevance", "limit": 15},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return []
            data = r.json()
            posts = []
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                text = f"{post.get('title', '')} {post.get('selftext', '')}"
                if len(text) > 20:
                    posts.append({
                        "text": text,
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                    })
            return posts
        except Exception:
            return []

    def _extract_picks(self, snippets: list[str], home: str, away: str) -> Counter:
        picks: Counter = Counter()
        home_l = home.lower()
        away_l = away.lower()

        win_patterns = [
            (rf"\b{re.escape(home_l)}\b.*\b(win|ml|moneyline|to beat)\b", "home"),
            (rf"\b{re.escape(away_l)}\b.*\b(win|ml|moneyline|to beat)\b", "away"),
            (rf"\b(win|ml|moneyline).*\b{re.escape(home_l)}\b", "home"),
            (rf"\b(win|ml|moneyline).*\b{re.escape(away_l)}\b", "away"),
            (r"\bdraw\b", "draw"),
            (r"\bover\s*2\.?5\b", "over"),
            (r"\bunder\s*2\.?5\b", "under"),
            (r"\bbtts\s*yes\b", "btts_yes"),
            (r"\bbtts\s*no\b", "btts_no"),
            (r"\bboth teams to score\b", "btts_yes"),
        ]

        for text in snippets:
            tl = text.lower()
            for pattern, pick in win_patterns:
                if re.search(pattern, tl):
                    picks[pick] += 1
        return picks

    def _dominant_narrative(
        self, home: str, away: str, home_pct: float, away_pct: float, over_pct: float
    ) -> str:
        if home_pct > 0.5:
            return f"Internet leans {home} ({home_pct:.0%} of mentions)"
        if away_pct > 0.5:
            return f"Internet leans {away} ({away_pct:.0%} of mentions)"
        if over_pct > 0.6:
            return f"Public expecting goals — over 2.5 mentioned frequently ({over_pct:.0%})"
        if over_pct < 0.4:
            return "Public expecting a low-scoring game"
        return "No clear internet consensus — split opinions"


def web_supports_selection(web: WebConsensus, selection: str, market: str) -> float:
    """-1 to +1: how much web consensus supports our pick."""
    if market == "match_winner":
        pct = {"home": web.home_pick_pct, "draw": web.draw_pick_pct, "away": web.away_pick_pct}.get(selection, 0.33)
        if web.fade_public and pct > 0.7:
            return -0.1  # fade heavy public
        return (pct - 0.33) * 0.5
    if market == "over_under_goals":
        if selection == "over":
            return (web.over_25_pct - 0.5) * 0.4
        return (0.5 - web.over_25_pct) * 0.4
    if market == "btts":
        if selection == "yes":
            return (web.btts_yes_pct - 0.5) * 0.4
        return (0.5 - web.btts_yes_pct) * 0.4
    return 0.0
