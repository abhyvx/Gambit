"""Full Stake analysis pipeline: scrape → analyze all markets → verdict."""

from __future__ import annotations

from bet_placer.consensus.bettors import analyze_bettor_consensus
from bet_placer.consensus.web import WebConsensusFetcher
from bet_placer.data.stake_cache import fetch_or_cache
from bet_placer.data.stake_mapper import stake_fixture_to_match
from bet_placer.data.stake_scraper import StakeScraper
from bet_placer.engine.probability import ProbabilityEngine
from bet_placer.engine.verdict import MatchVerdictEngine
from bet_placer.models.stake_types import BettorConsensus, MatchVerdict, StakeFixture, WebConsensus
from bet_placer.models.types import AnalysisResult, Match


class StakeAnalysisPipeline:
    def __init__(self):
        self.scraper = StakeScraper()
        self.engine = ProbabilityEngine()
        self.verdict_engine = MatchVerdictEngine()
        self.web_fetcher = WebConsensusFetcher()

    def run(
        self,
        sport: str = "soccer",
        match_filter: str | None = None,
        fixture_id: str | None = None,
    ) -> list[dict]:
        fixtures, live_bets, hr_bets, from_live = fetch_or_cache(self.scraper, sport=sport)

        if fixture_id:
            try:
                fixtures = [self.scraper.fetch_fixture_odds(fixture_id)]
                from_live = True
            except Exception:
                fixtures = [f for f in fixtures if f.id == fixture_id]

        if match_filter:
            needle = match_filter.lower()
            fixtures = [
                f for f in fixtures
                if needle in f.home_team.lower() or needle in f.away_team.lower()
            ]

        results: list[dict] = []
        for fixture in fixtures:
            match = stake_fixture_to_match(fixture)
            analysis = self.engine.analyze_match(match)
            bettor = analyze_bettor_consensus(fixture, live_bets, hr_bets)
            web = self.web_fetcher.fetch(fixture.home_team, fixture.away_team, fixture.league)
            verdict = self.verdict_engine.evaluate(
                analysis,
                bettor_consensus=bettor,
                web_consensus=web,
                stake_markets_scanned=_count_stake_markets(fixture),
            )
            results.append({
                "fixture": fixture,
                "match": match,
                "analysis": analysis,
                "bettor_consensus": bettor,
                "web_consensus": web,
                "verdict": verdict,
                "from_live_stake": from_live,
            })
        return results


def _count_stake_markets(fixture: StakeFixture) -> int:
    return sum(len(m.outcomes) for m in fixture.markets)
