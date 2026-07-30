"""Canonical team-name resolution shared across scraping, matching, and the
historical-data trainer.

Different sources spell nations differently (Stake: "Bosnia and Herzegovina",
the historical dataset: same; we use "Bosnia"). Everything funnels through
`canon_team` so a team is the same entity everywhere — matching never fails and
the model can attach learned Elo to the right side.
"""

from __future__ import annotations

import unicodedata

# Tokens that don't help identify a national / club team.
NOISE_TOKENS = {"fc", "afc", "cf", "sc", "club", "the", "of", "and"}

# Variant (accent-stripped, lowercased, noise-removed) -> OUR canonical name.
TEAM_ALIASES = {
    "bosnia and herzegovina": "bosnia",
    "bosnia herzegovina": "bosnia",
    "bosnia-herzegovina": "bosnia",
    "czechia": "czech republic",
    "czech rep": "czech republic",
    "korea republic": "south korea",
    "republic of korea": "south korea",
    "korea dpr": "north korea",
    "dpr korea": "north korea",
    "united states": "usa",
    "united states of america": "usa",
    "us": "usa",
    "usa": "usa",
    "turkiye": "turkey",
    "ir iran": "iran",
    "iran islamic republic": "iran",
    "cote divoire": "ivory coast",
    "cote d ivoire": "ivory coast",
    "congo dr": "dr congo",
    "democratic republic of the congo": "dr congo",
    "china pr": "china",
    "cabo verde": "cape verde",
    "republic of ireland": "ireland",
    # Club aliases — ESPN / Stake / OddsAPI spell the same side differently.
    # Without these, "Manchester United" and "Man United" get separate Elo
    # rows and a mid-table side can beat a top club on a split identity.
    "manchester united": "man united",
    "manchester utd": "man united",
    "man utd": "man united",
    "man u": "man united",
    "mufc": "man united",
    "manchester city": "man city",
    "manchester cty": "man city",
    "man city": "man city",
    "mcfc": "man city",
    "hull city": "hull",
    "tottenham hotspur": "tottenham",
    "spurs": "tottenham",
    "wolverhampton wanderers": "wolves",
    "wolverhampton": "wolves",
    "nottingham forest": "nottm forest",
    "notts forest": "nottm forest",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
    "west ham united": "west ham",
    "newcastle united": "newcastle",
    "leicester city": "leicester",
    "norwich city": "norwich",
    "cardiff city": "cardiff",
    "swansea city": "swansea",
    "leeds united": "leeds",
    "sheffield united": "sheffield utd",
    "sheffield wednesday": "sheffield wed",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def canon_team(name: str) -> str:
    """Canonicalize a team name (accents, noise tokens, known aliases)."""
    cleaned = strip_accents(name).lower()
    cleaned = "".join(c if c.isalnum() else " " for c in cleaned)
    toks = [t for t in cleaned.split() if t not in NOISE_TOKENS]
    key = " ".join(toks).strip()
    return TEAM_ALIASES.get(key, key)
