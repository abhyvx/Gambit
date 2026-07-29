"""Stake.com GraphQL scraper for live odds, markets, and bettor activity."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests

from bet_placer.config import get_settings
from bet_placer.models.stake_types import BettorPick, StakeFixture, StakeMarket, StakeOutcome

DEFAULT_ENDPOINT = "https://stake.com/_api/graphql"
STABLE_COINS = {"USDT", "USDC", "BUSD", "DAI", "USD"}
FIAT_BASE = {"USD", "INR", "EUR", "GBP", "AUD", "CAD"}

TRENDING_QUERY = """
query TrendingMatches {
  sportHomepageTrendingMatches(sortBy: totalBetValue) {
    fixtureStatistics { totalUserCount totalBetCount totalBetValue }
    fixture {
      id name status
      data { ... on SportFixtureDataMatch {
        startTime
        competitors { name extId }
      }}
      tournament {
        name
        category { name sport { name slug } }
      }
      groups {
        name
        templates(limit: 120, includeEmpty: false) {
          name
          markets(limit: 250) {
            id
            name
            status
            specifiers
            outcomes { id name odds active }
          }
        }
      }
    }
  }
}
"""

FIXTURE_ODDS_QUERY = """
query FixtureOdds($id: String!) {
  sportFixture(id: $id) {
    id name status
    data { ... on SportFixtureDataMatch {
      startTime
      competitors { name extId }
    }}
    tournament {
      name
      category { name sport { name slug } }
    }
    groups {
      name
      templates(limit: 200, includeEmpty: false) {
        name
        markets(limit: 400) {
          id name status specifiers
          outcomes { id name odds active }
        }
      }
    }
  }
}
"""

ALL_SPORT_BETS_QUERY = """
query AllSportBets($limit: Int) {
  allSportBets(limit: $limit) {
    id
    bet {
      ... on SportBet {
        id amount currency potentialMultiplier active createdAt
        user { name preferenceHideBets }
        outcomes {
          odds
          fixtureName
          outcome { name }
          fixture {
            id name status
            tournament { name category { name sport { name slug } } }
          }
        }
      }
    }
  }
}
"""

HIGHROLLER_BETS_QUERY = """
query HighrollerBets($limit: Int) {
  highrollerSportBets(limit: $limit) {
    id
    bet {
      ... on SportBet {
        id amount currency potentialMultiplier active createdAt
        user { name preferenceHideBets }
        outcomes {
          odds
          fixtureName
          outcome { name }
          fixture {
            id name status
            tournament { name category { name sport { name slug } } }
          }
        }
      }
    }
  }
}
"""

USER_SPORT_BET_LIST_QUERY = """
query UserSportBetList($limit: Int!, $offset: Int!) {
  user {
    sportBetList(limit: $limit, offset: $offset) {
      id
      bet {
        ... on SportBet {
          id
          amount
          currency
          payout
          payoutMultiplier
          potentialMultiplier
          active
          createdAt
          status
          outcomes {
            odds
            status
            fixtureName
            outcome { name payout }
            fixture {
              id
              name
              status
              tournament { name category { name sport { name slug } } }
              data { ... on SportFixtureDataMatch { competitors { name extId } } }
            }
          }
        }
      }
    }
  }
}
"""


class StakeScraper:
    """Scrape Stake.com sportsbook via internal GraphQL API."""

    def __init__(
        self,
        api_token: str | None = None,
        endpoint: str | None = None,
        timeout: int = 20,
        use_browser: bool | None = None,
        allow_browser_launch: bool = False,
    ):
        settings = get_settings()
        self.api_token = api_token or settings.stake_api_token
        self.endpoint = endpoint or settings.stake_graphql_endpoint or DEFAULT_ENDPOINT
        self.timeout = timeout
        self.use_browser = settings.stake_use_browser if use_browser is None else use_browser
        self.allow_browser_launch = allow_browser_launch
        self.session = requests.Session()
        self.session.headers.update({
            "content-type": "application/json",
            "x-language": "en",
            "accept": "application/json",
            "origin": "https://stake.com",
            "referer": "https://stake.com/sports",
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        })
        if self.api_token:
            self.session.headers["x-access-token"] = self.api_token

    def _graphql(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        if self.use_browser:
            from bet_placer.data.stake_browser import graphql as browser_graphql
            return browser_graphql(
                query,
                variables,
                timeout=self.timeout,
                launch_if_needed=self.allow_browser_launch,
            )
        payload = {"query": query, "variables": variables or {}}
        resp = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if errors := data.get("errors"):
            msg = errors[0].get("message", str(errors))
            raise RuntimeError(f"Stake GraphQL error: {msg}")
        return data.get("data") or {}

    def get_crypto_prices(self) -> dict[str, float]:
        try:
            r = self.session.get(
                "https://api.binance.com/api/v3/ticker/price", timeout=8
            )
            r.raise_for_status()
            prices = {c: 1.0 for c in STABLE_COINS}
            for item in r.json():
                sym = item["symbol"]
                if sym.endswith("USDT"):
                    prices[sym[:-4]] = float(item["price"])
            return prices
        except Exception:
            return {c: 1.0 for c in STABLE_COINS}

    def fetch_trending_fixtures(self, sport_slug: str | None = "soccer") -> list[StakeFixture]:
        data = self._graphql(TRENDING_QUERY)
        rows = data.get("sportHomepageTrendingMatches") or []
        fixtures: list[StakeFixture] = []
        for row in rows:
            stats = row.get("fixtureStatistics") or {}
            fixture = self._parse_fixture(
                row.get("fixture") or {},
                total_bet_value=float(stats.get("totalBetValue") or 0),
                total_bet_count=int(stats.get("totalBetCount") or 0),
                total_user_count=int(stats.get("totalUserCount") or 0),
            )
            if sport_slug:
                sport = fixture.sport.lower()
                if sport_slug not in sport and sport_slug != sport:
                    if sport_slug == "soccer" and sport not in ("soccer", "football"):
                        continue
            fixtures.append(fixture)
        return fixtures

    def fetch_fixture_odds(self, fixture_id: str) -> StakeFixture:
        data = self._graphql(FIXTURE_ODDS_QUERY, {"id": fixture_id})
        fixture_raw = data.get("sportFixture")
        if not fixture_raw:
            raise ValueError(f"Fixture not found: {fixture_id}")
        return self._parse_fixture(fixture_raw)

    def search_fixture_by_teams(self, home: str, away: str) -> StakeFixture | None:
        """Find a fixture not in trending by scanning the live bet feed."""
        from bet_placer.engine.stake_odds import _team_match

        def _scan_bets(limit: int) -> str | None:
            prices = self.get_crypto_prices()
            data = self._graphql(ALL_SPORT_BETS_QUERY, {"limit": limit})
            for item in data.get("allSportBets") or []:
                bet = item.get("bet") or {}
                for oc in bet.get("outcomes") or []:
                    fx = oc.get("fixture") or {}
                    fid = str(fx.get("id") or "")
                    if not fid:
                        continue
                    h = (fx.get("name") or oc.get("fixtureName") or "").lower()
                    if _team_match(home, h) and _team_match(away, h):
                        return fid
                    # fixtureName often "Team A - Team B"
                    parts = re.split(r"\s[-–]\s", h, maxsplit=1)
                    if len(parts) == 2:
                        if (_team_match(home, parts[0]) and _team_match(away, parts[1])) or (
                            _team_match(home, parts[1]) and _team_match(away, parts[0])
                        ):
                            return fid
            return None

        fid = _scan_bets(200)
        if not fid:
            fid = _scan_bets(400)
        if not fid:
            return None
        try:
            fx = self.fetch_fixture_odds(fid)
        except Exception:
            return None
        if not (_team_match(home, fx.home_team) and _team_match(away, fx.away_team)):
            if not (_team_match(home, fx.away_team) and _team_match(away, fx.home_team)):
                return None
        return fx

    def fetch_live_bets(self, limit: int = 100) -> list[BettorPick]:
        prices = self.get_crypto_prices()
        data = self._graphql(ALL_SPORT_BETS_QUERY, {"limit": limit})
        return self._parse_bet_feed(data.get("allSportBets") or [], prices, highroller=False)

    def fetch_highroller_bets(self, limit: int = 50) -> list[BettorPick]:
        prices = self.get_crypto_prices()
        data = self._graphql(HIGHROLLER_BETS_QUERY, {"limit": limit})
        return self._parse_bet_feed(data.get("highrollerSportBets") or [], prices, highroller=True)

    def fetch_user_bet_history(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        prices = self.get_crypto_prices()
        data = self._graphql(USER_SPORT_BET_LIST_QUERY, {"limit": limit, "offset": offset})
        items = ((data.get("user") or {}).get("sportBetList")) or []
        return self._parse_user_bet_history(items, prices)

    def _parse_fixture(
        self,
        raw: dict,
        total_bet_value: float = 0,
        total_bet_count: int = 0,
        total_user_count: int = 0,
    ) -> StakeFixture:
        data = raw.get("data") or {}
        competitors = data.get("competitors") or []
        home = competitors[0]["name"] if len(competitors) > 0 else "Home"
        away = competitors[1]["name"] if len(competitors) > 1 else "Away"

        tournament = raw.get("tournament") or {}
        category = tournament.get("category") or {}
        sport = (category.get("sport") or {}).get("name", "Soccer")
        league = tournament.get("name") or category.get("name") or "Unknown"

        kickoff = None
        if start := data.get("startTime"):
            try:
                kickoff = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except ValueError:
                pass

        markets: list[StakeMarket] = []
        for group in raw.get("groups") or []:
            group_name = group.get("name", "")
            for template in group.get("templates") or []:
                for market in template.get("markets") or []:
                    if market.get("status") == "deactivated":
                        continue
                    outcomes = []
                    for oc in market.get("outcomes") or []:
                        if not oc.get("active", True):
                            continue
                        try:
                            odds = float(oc.get("odds") or 0)
                        except (TypeError, ValueError):
                            continue
                        if odds <= 1.0:
                            continue
                        outcomes.append(StakeOutcome(
                            id=str(oc.get("id", "")),
                            name=oc.get("name", ""),
                            odds=odds,
                            active=True,
                            market_id=str(market.get("id", "")),
                            raw=oc,
                        ))
                    if outcomes:
                        markets.append(StakeMarket(
                            id=str(market.get("id", "")),
                            name=market.get("name") or template.get("name", ""),
                            group=group_name,
                            outcomes=outcomes,
                            line=_extract_line(market.get("name", ""), market.get("specifiers", "")),
                            specifiers=market.get("specifiers", ""),
                            template=template.get("name", ""),
                            status=market.get("status", ""),
                            raw=market,
                        ))

        return StakeFixture(
            id=str(raw.get("id", "")),
            name=raw.get("name") or f"{home} vs {away}",
            home_team=home,
            away_team=away,
            sport=sport,
            league=league,
            status=raw.get("status", "active"),
            kickoff=kickoff,
            markets=markets,
            total_bet_value=total_bet_value,
            total_bet_count=total_bet_count,
            total_user_count=total_user_count,
            raw=raw,
        )

    def _parse_bet_feed(
        self,
        items: list[dict],
        prices: dict[str, float],
        highroller: bool,
    ) -> list[BettorPick]:
        picks: list[BettorPick] = []
        for item in items:
            bet = item.get("bet") or {}
            amount = float(bet.get("amount") or 0)
            currency = (bet.get("currency") or "USDT").upper()
            usd = amount * prices.get(currency, 0)
            user = bet.get("user") or {}
            name = "hidden" if user.get("preferenceHideBets") else (user.get("name") or "anon")
            ts = None
            if created := bet.get("createdAt"):
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    ts = datetime.now(timezone.utc)

            for oc in bet.get("outcomes") or []:
                fixture = oc.get("fixture") or {}
                sport = (
                    (fixture.get("tournament") or {})
                    .get("category", {})
                    .get("sport", {})
                    .get("name", "")
                )
                picks.append(BettorPick(
                    fixture_name=oc.get("fixtureName") or fixture.get("name", ""),
                    outcome_name=(oc.get("outcome") or {}).get("name", ""),
                    odds=float(oc.get("odds") or 0),
                    amount_usd=round(usd, 2),
                    user_name=name,
                    is_highroller=highroller,
                    sport=sport,
                    timestamp=ts,
                ))
        return picks

    def _parse_user_bet_history(self, items: list[dict], prices: dict[str, float]) -> list[dict[str, Any]]:
        bets: list[dict[str, Any]] = []
        for item in items:
            wrapper_id = str(item.get("id") or "")
            bet = item.get("bet") or {}
            amount = float(bet.get("amount") or 0)
            payout = float(bet.get("payout") or 0)
            currency = (bet.get("currency") or "USDT").upper()
            fx = prices.get(currency, 0) or 0
            if currency in FIAT_BASE:
                stake_value = round(amount, 2)
                payout_value = round(payout, 2)
                display_currency = currency
            elif fx:
                stake_value = round(amount * fx, 2)
                payout_value = round(payout * fx, 2)
                display_currency = "USD"
            else:
                stake_value = round(amount, 2)
                payout_value = round(payout, 2)
                display_currency = currency
            created_at = None
            if created := bet.get("createdAt"):
                try:
                    created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    created_at = datetime.now(timezone.utc)

            outcomes = bet.get("outcomes") or []
            first = outcomes[0] if outcomes else {}
            fixture = first.get("fixture") or {}
            fixture_data = fixture.get("data") or {}
            competitors = fixture_data.get("competitors") or []
            home = competitors[0].get("name") if len(competitors) > 0 else None
            away = competitors[1].get("name") if len(competitors) > 1 else None
            league = ((fixture.get("tournament") or {}).get("name")) or "Unknown"

            selections: list[dict[str, Any]] = []
            odds_values: list[float] = []
            for oc in outcomes:
                try:
                    odds = float(oc.get("odds") or 0)
                except (TypeError, ValueError):
                    odds = 0.0
                if odds > 0:
                    odds_values.append(odds)
                selections.append(
                    {
                        "fixture_name": oc.get("fixtureName") or fixture.get("name") or "",
                        "selection": ((oc.get("outcome") or {}).get("name")) or "",
                        "odds": odds,
                        "status": (oc.get("status") or "").lower(),
                        "payout": float(((oc.get("outcome") or {}).get("payout") or 0) or 0),
                    }
                )

            combined_odds = 1.0
            if odds_values:
                for odds in odds_values:
                    combined_odds *= odds

            raw_status = (bet.get("status") or "").lower()
            active = bool(bet.get("active"))
            outcome_statuses = {str(s.get("status") or "").lower() for s in selections}
            status = raw_status
            result = "open"
            if active or raw_status in {"open", "pending"}:
                status = "open"
                result = "open"
            elif raw_status == "cashout":
                status = "cashout"
                result = "cashed_out"
            elif raw_status in {"cancelled", "canceled", "void"} or "voided" in outcome_statuses:
                status = "void"
                result = "push"
            elif raw_status in {"won"} or (outcome_statuses and outcome_statuses <= {"won"}):
                status = "won"
                result = "won"
            elif raw_status in {"lost", "lose"} or "lost" in outcome_statuses:
                status = "lost"
                result = "lost"
            elif payout_value > amount:
                status = "won"
                result = "won"
            elif payout_value == amount and amount > 0:
                status = "void"
                result = "push"
            elif payout_value > 0:
                status = "cashout"
                result = "cashed_out"
            else:
                status = "lost"
                result = "lost"

            profit_value = round(payout_value - stake_value, 2) if status != "open" else 0.0

            bets.append(
                {
                    "id": wrapper_id or str(bet.get("id") or ""),
                    "bet_id": str(bet.get("id") or ""),
                    "created_at": created_at.isoformat() if created_at else None,
                    "status": status or ("open" if active else "unknown"),
                    "result": result,
                    "active": active,
                    "currency": currency,
                    "display_currency": display_currency,
                    "stake": amount,
                    "stake_value": stake_value,
                    "payout": payout,
                    "payout_value": payout_value,
                    "profit_value": profit_value,
                    "combined_odds": round(combined_odds, 2) if combined_odds > 1 else None,
                    "potential_multiplier": float(bet.get("potentialMultiplier") or 0) or None,
                    "payout_multiplier": float(bet.get("payoutMultiplier") or 0) or None,
                    "fixture_name": first.get("fixtureName") or fixture.get("name") or "Unknown fixture",
                    "fixture_id": str(fixture.get("id") or ""),
                    "fixture_status": (fixture.get("status") or "").lower() or None,
                    "home_team": home,
                    "away_team": away,
                    "league": league,
                    "selection_count": len(selections),
                    "bet_type": "parlay" if len(selections) > 1 else "single",
                    "market_family": _infer_market_family(selections),
                    "selections": selections,
                }
            )

        bets.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return bets


def _infer_market_family(selections: list[dict[str, Any]]) -> str:
    text = " ".join(
        f"{sel.get('selection', '')} {sel.get('fixture_name', '')}".lower()
        for sel in selections
    )
    if any(word in text for word in ("draw", "1x2", "moneyline", "to win", "winner")):
        return "result"
    if any(word in text for word in ("over", "under", "total")):
        return "totals"
    if any(word in text for word in ("both teams to score", "btts")):
        return "btts"
    if any(word in text for word in ("handicap", "+", "-")):
        return "handicap"
    if any(word in text for word in ("score", "goal scorer", "first goal")):
        return "scorers"
    return "other"


def _parse_specifiers(specifiers: str) -> dict[str, str]:
    """Stake encodes lines as 'total=2.5', 'hcp=-0.5', 'goalnr=1', etc."""
    out: dict[str, str] = {}
    for part in (specifiers or "").split("|"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
    return out


def _extract_line(market_name: str, specifiers: str) -> float | None:
    """Only return a real betting line from the specifiers (total/handicap).

    The old version scraped any digit from the name, so '1x2' became line 1.0
    and '1st Goal' became 1.0 — pure noise. Lines only exist for totals and
    handicaps, and Stake puts them in the specifiers field.
    """
    spec = _parse_specifiers(specifiers)
    for key in ("total", "hcp", "handicap"):
        if key in spec:
            try:
                return float(spec[key])
            except (TypeError, ValueError):
                return None
    return None
