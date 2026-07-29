"""Player goalscorer model — honest reads for anytime / first / 2+ scorer markets.

We don't have shot-level data, so instead of faking a sharp edge we derive each
listed attacker's scoring rate from two things we DO model well:

  * the team's expected goals for this match (from the Poisson engine), and
  * the player's attacking rank inside the squad (lists are best-first).

A team scores `team_xg` goals on average; roughly ~72% of those come from its
front-line attackers. We split that covered share across the listed attackers by
a decaying rank weight, giving each a per-match scoring rate λ. From λ the goal
markets follow directly from the Poisson distribution:

  anytime  = 1 − e^(−λ)
  2+       = 1 − e^(−λ)(1 + λ)
  hat-trick= 1 − e^(−λ)(1 + λ + λ²/2)
  first    ≈ (λ / total_match_goals) · P(any goal is scored)

Players we don't recognise stay "no read" — we won't invent an edge for a name
we can't place. This keeps player props honest while still giving real
consideration to the stars who actually decide these markets.
"""

from __future__ import annotations

import math
import unicodedata

from bet_placer.data.team_stars import get_attackers, _names_same_player, _strip

# Fraction of a team's goals that come from its listed front-line attackers
# (the rest: defenders on set pieces, deep midfielders, own goals).
_COVERED_SHARE = 0.86
# Rank weights (best-first) used to split the covered share across attackers.
# Steeper so the main striker carries a realistic anytime price (~35-45%).
_RANK_W = [1.0, 0.6, 0.4, 0.28, 0.2, 0.15, 0.12, 0.1]


def _strip(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)
    )


def _surname(name: str) -> str:
    toks = _strip(name).lower().replace(",", " ").split()
    return toks[-1] if toks else ""


def _anytime(lam: float) -> float:
    return min(0.62, 1.0 - math.exp(-lam))


def _two_plus(lam: float) -> float:
    return max(0.0, 1.0 - math.exp(-lam) * (1.0 + lam))


def _three_plus(lam: float) -> float:
    return max(0.0, 1.0 - math.exp(-lam) * (1.0 + lam + lam * lam / 2.0))


class PlayerModel:
    """Per-match scoring rates for each listed attacker on both teams."""

    def __init__(self, mm, home: str, away: str):
        self.home = home
        self.away = away
        self.total = max(0.1, float(mm.hl) + float(mm.al))
        # full normalized name -> (lambda, team, canonical name)
        self._by_name: dict[str, tuple[float, str, str]] = {}
        self._build(home, float(mm.hl))
        self._build(away, float(mm.al))

    def _build(self, team: str, team_xg: float) -> None:
        squad = get_attackers(team, 8)
        weights = [_RANK_W[i] if i < len(_RANK_W) else 0.08 for i in range(len(squad))]
        wsum = sum(weights) or 1.0
        for i, player in enumerate(squad):
            share = (weights[i] / wsum) * _COVERED_SHARE
            lam = max(0.0, team_xg * share)
            key = _strip(player).lower()
            if key and key not in self._by_name:
                self._by_name[key] = (lam, team, player)

    def _lookup(self, name: str) -> tuple[float, str, str] | None:
        key = _strip(name).lower()
        if key in self._by_name:
            return self._by_name[key]
        for team in (self.home, self.away):
            for player in get_attackers(team, 8):
                if _names_same_player(name, player):
                    return self._by_name.get(_strip(player).lower())
        return None

    def rate(self, market_name: str, outcome_name: str) -> float | None:
        """Probability for a goalscorer outcome, or None if we can't place him."""
        player = (outcome_name or "").strip()
        low = player.lower()
        if low in ("no goalscorer", "no", "yes", "none"):
            return None
        found = self._lookup(player)
        if not found:
            return None
        lam, _team, _full = found
        if lam <= 0:
            return None

        n = (market_name or "").lower()
        if "hat" in n or "3+" in n or "three or more" in n:
            return round(_three_plus(lam), 4)
        if "2" in n or "two or more" in n or "2+" in n or "brace" in n:
            return round(_two_plus(lam), 4)
        if "first" in n or "1st" in n:
            p = (lam / self.total) * (1.0 - math.exp(-self.total))
            return round(min(0.45, p), 4)
        if "last" in n:
            p = (lam / self.total) * (1.0 - math.exp(-self.total))
            return round(min(0.45, p), 4)
        # default: anytime goalscorer
        return round(_anytime(lam), 4)
