"""Analyst intuition layer — EDITORIAL football knowledge, not live data.

This is hand-authored scouting intel (playing style, tempo, discipline, mentality,
danger man, weakness) plus a rivalries/grudges map. It is OPINION used to pick
which betting angles to feature for a given matchup and to write the human read —
it is deliberately NOT fed into the EV / payout math, which stays grounded in the
real odds. Treat every value here as "an analyst's take", clearly labelled as such
in the UI.

style:     possession | counter | high_press | direct | defensive | balanced
tempo:     high | medium | low      (how end-to-end / open the team plays)
discipline:hot | physical | normal | disciplined   (card tendency)
mentality: ruthless | resilient | tournament_savvy | streaky | fragile | naive
"""

from __future__ import annotations

# Per-team scouting intel. Missing teams fall back to _DEFAULT_INTEL.
TEAM_INTEL: dict[str, dict] = {
    "Argentina": {"style": "possession", "tempo": "medium", "discipline": "physical", "mentality": "ruthless",
                  "threat": "Messi pulls strings; Julián Álvarez runs in behind", "weakness": "ageing legs late in games", "note": "Champions' mentality — manage games and kill them off."},
    "France": {"style": "counter", "tempo": "high", "discipline": "normal", "mentality": "ruthless",
               "threat": "Mbappé's pace in transition is unplayable", "weakness": "can switch off when cruising", "note": "Devastating on the break; don't need the ball to win."},
    "Brazil": {"style": "possession", "tempo": "high", "discipline": "physical", "mentality": "streaky",
               "threat": "Vinícius & Rodrygo 1v1 dribbling", "weakness": "emotional, can lose the plot under pressure", "note": "Flair going forward, occasionally naive defensively."},
    "England": {"style": "possession", "tempo": "medium", "discipline": "normal", "mentality": "fragile",
                "threat": "Kane drops and links, Saka/Foden carry", "weakness": "go conservative and invite pressure", "note": "Talented but tighten up in knockouts — games can get cagey."},
    "Spain": {"style": "possession", "tempo": "medium", "discipline": "disciplined", "mentality": "tournament_savvy",
              "threat": "Yamal & Nico Williams stretch the pitch", "weakness": "lack a ruthless No.9 at times", "note": "Dominate the ball and corners; can lack a killer finish."},
    "Germany": {"style": "possession", "tempo": "high", "discipline": "normal", "mentality": "resilient",
                "threat": "Musiala & Wirtz between the lines", "weakness": "high line exposed to pace", "note": "Open, attack-minded — goals at both ends."},
    "Portugal": {"style": "possession", "tempo": "medium", "discipline": "physical", "mentality": "streaky",
                 "threat": "Leão & Bruno Fernandes; Ronaldo in the box", "weakness": "over-reliant on moments", "note": "Loaded attack, sometimes disjointed."},
    "Netherlands": {"style": "possession", "tempo": "medium", "discipline": "normal", "mentality": "tournament_savvy",
                    "threat": "Gakpo & Depay", "weakness": "can be ponderous breaking down low blocks", "note": "Structured, patient — games can be controlled and low-event."},
    "Croatia": {"style": "possession", "tempo": "low", "discipline": "physical", "mentality": "resilient",
                "threat": "Modrić dictates midfield", "weakness": "ageing core, short on goals", "note": "Slow-burn, midfield-controlled games — often low-scoring and tight."},
    "Belgium": {"style": "counter", "tempo": "medium", "discipline": "normal", "mentality": "fragile",
                "threat": "De Bruyne's delivery", "weakness": "ageing golden generation, dressing-room friction", "note": "Quality fading; can underperform expectations."},
    "Morocco": {"style": "counter", "tempo": "medium", "discipline": "physical", "mentality": "resilient",
                "threat": "Hakimi overlaps; En-Nesyri aerial", "weakness": "limited possession dominance", "note": "Elite defensive organisation — frustrate big teams, low-scoring."},
    "USA": {"style": "high_press", "tempo": "high", "discipline": "normal", "mentality": "naive",
            "threat": "Pulisic carrying, Balogun runs", "weakness": "game-management in tight spots", "note": "Athletic and pressing — end-to-end games."},
    "Mexico": {"style": "possession", "tempo": "medium", "discipline": "physical", "mentality": "fragile",
               "threat": "Giménez & Lozano", "weakness": "freeze in knockout pressure", "note": "Tidy but tighten up when it matters."},
    "Japan": {"style": "high_press", "tempo": "high", "discipline": "disciplined", "mentality": "tournament_savvy",
              "threat": "Mitoma & Kubo dribbling", "weakness": "size at set pieces", "note": "Sharp pressing, well-drilled, very low card count."},
    "South Korea": {"style": "counter", "tempo": "high", "discipline": "physical", "mentality": "resilient",
                    "threat": "Son in transition", "weakness": "defensive lapses", "note": "Quick and committed — open, physical games."},
    "Uruguay": {"style": "direct", "tempo": "medium", "discipline": "hot", "mentality": "ruthless",
                "threat": "Núñez & Darwin runs", "weakness": "indiscipline boils over", "note": "Snarling, aggressive — expect cards."},
    "Colombia": {"style": "possession", "tempo": "medium", "discipline": "physical", "mentality": "streaky",
                 "threat": "Luis Díaz & James creativity", "weakness": "can go missing away from home", "note": "Technical with a physical edge."},
    "Norway": {"style": "direct", "tempo": "high", "discipline": "normal", "mentality": "streaky",
               "threat": "Haaland — feed him and he scores", "weakness": "thin beyond the stars", "note": "Get the ball to Haaland; goals revolve around him."},
    "Senegal": {"style": "counter", "tempo": "high", "discipline": "physical", "mentality": "resilient",
                "threat": "pace & power in wide areas", "weakness": "final-third decision making", "note": "Athletic, physical contests."},
    "Switzerland": {"style": "defensive", "tempo": "low", "discipline": "physical", "mentality": "tournament_savvy",
                    "threat": "Xhaka controls tempo", "weakness": "short of attacking spark", "note": "Compact, hard to beat — low-scoring."},
    "Denmark": {"style": "balanced", "tempo": "medium", "discipline": "normal", "mentality": "resilient",
                "threat": "Højlund's runs, Eriksen's passing", "weakness": "can be blunt vs deep blocks", "note": "Well-organised, even contests."},
    "Ecuador": {"style": "counter", "tempo": "medium", "discipline": "hot", "mentality": "resilient",
                "threat": "Caicedo drives; Valencia leads the line", "weakness": "discipline", "note": "Physical, combative — card risk."},
    "Australia": {"style": "direct", "tempo": "medium", "discipline": "physical", "mentality": "resilient",
                  "threat": "set pieces & graft", "weakness": "limited quality", "note": "Honest, physical, set-piece reliant — low-scoring."},
    "Ghana": {"style": "counter", "tempo": "high", "discipline": "physical", "mentality": "streaky",
              "threat": "Kudus carrying", "weakness": "leaky at the back", "note": "Open, transition-heavy — goals possible both ends."},
    "Panama": {"style": "defensive", "tempo": "low", "discipline": "hot", "mentality": "resilient",
               "threat": "set pieces, counters", "weakness": "quality gap vs top sides", "note": "Sit deep and scrap — physical, card-prone."},
    "Uzbekistan": {"style": "balanced", "tempo": "low", "discipline": "normal", "mentality": "naive",
                   "threat": "Shomurodov hold-up", "weakness": "step up in class", "note": "Organised debutants — likely to sit in and keep it tight."},
    "Iran": {"style": "defensive", "tempo": "low", "discipline": "physical", "mentality": "resilient",
             "threat": "Taremi", "weakness": "creativity", "note": "Deep block, low-event games."},
    "Saudi Arabia": {"style": "high_press", "tempo": "high", "discipline": "hot", "mentality": "streaky",
                     "threat": "aggressive press", "weakness": "leaves space behind", "note": "Brave press, card-prone, open."},
    "DR Congo": {"style": "defensive", "tempo": "low", "discipline": "physical", "mentality": "resilient",
                 "threat": "Bakambu on the break", "weakness": "sit deep and absorb", "note": "Compact low block — frustrate favourites."},
    "Canada": {"style": "high_press", "tempo": "high", "discipline": "normal", "mentality": "naive",
               "threat": "Davies' pace, David's finishing", "weakness": "tournament inexperience", "note": "Quick and front-foot — open games."},
}

_DEFAULT_INTEL = {
    "style": "balanced", "tempo": "medium", "discipline": "normal", "mentality": "resilient",
    "threat": "their main forward", "weakness": "no glaring edge", "note": "No strong stylistic read — judge on the odds.",
}

# Rivalries / grudges — sorted-pair key. intensity: derby weight; note: the story.
_RIVALRIES = {
    frozenset({"Argentina", "Brazil"}): {"intensity": 10, "note": "Superclásico de las Américas — fierce, niggly, high-stakes."},
    frozenset({"England", "Argentina"}): {"intensity": 9, "note": "Maradona/1986 & 1998 history — bad blood, tense affair."},
    frozenset({"Germany", "Netherlands"}): {"intensity": 9, "note": "One of football's nastiest rivalries — tackles fly."},
    frozenset({"Spain", "Portugal"}): {"intensity": 7, "note": "Iberian derby — pride on the line."},
    frozenset({"Mexico", "USA"}): {"intensity": 9, "note": "CONCACAF grudge match — always feisty and card-heavy."},
    frozenset({"Serbia", "Croatia"}): {"intensity": 10, "note": "Balkan rivalry with deep tensions — volatile, physical."},
    frozenset({"England", "Germany"}): {"intensity": 8, "note": "Historic rivalry — tight, edgy occasions."},
    frozenset({"France", "England"}): {"intensity": 7, "note": "Cross-Channel rivalry — cagey, respect-driven."},
    frozenset({"Uruguay", "Argentina"}): {"intensity": 8, "note": "Río de la Plata derby — snarling and physical."},
    frozenset({"Korea Republic", "Japan"}): {"intensity": 9, "note": "East-Asian rivalry — intense and committed."},
    frozenset({"South Korea", "Japan"}): {"intensity": 9, "note": "East-Asian rivalry — intense and committed."},
    frozenset({"Iran", "Saudi Arabia"}): {"intensity": 8, "note": "Regional rivalry — tense, physical."},
}


def get_team_intel(team: str) -> dict:
    return {**_DEFAULT_INTEL, **TEAM_INTEL.get(team, {})}


def get_rivalry(home: str, away: str) -> dict | None:
    return _RIVALRIES.get(frozenset({home, away}))
