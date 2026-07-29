"""Squad lists for goalscorer props — key attackers per nation."""

from __future__ import annotations

import unicodedata

# Best-first attacking options for modelled goalscorer props (not the full roster).
TEAM_SQUAD: dict[str, list[str]] = {
    "Mexico": ["Santiago Giménez", "Hirving Lozano", "Raúl Jiménez", "Alexis Vega"],
    "South Africa": ["Percy Tau", "Lyle Foster", "Sphephelo Mbhonambi"],
    "South Korea": ["Son Heung-min", "Lee Kang-in", "Hwang Hee-chan", "Cho Gue-sung"],
    "Denmark": ["Rasmus Højlund", "Christian Eriksen", "Jonas Wind"],
    "Canada": ["Jonathan David", "Alphonso Davies", "Cyle Larin"],
    "Qatar": ["Almoez Ali", "Akram Afif"],
    "Switzerland": ["Breel Embolo", "Granit Xhaka", "Dan Ndoye"],
    "Scotland": ["Scott McTominay", "Che Adams", "Lyndon Dykes"],
    "USA": ["Christian Pulisic", "Folarin Balogun", "Gio Reyna", "Weston McKennie"],
    "Paraguay": ["Miguel Almirón", "Gustavo Gómez", "Julio Enciso"],
    "Australia": [
        "Nestory Irankunda", "Mohamed Toure", "Tete Yengi",
        "Awer Mabil", "Nishan Velupillay", "Cristian Volpato",
    ],
    "Czech Republic": ["Patrik Schick", "Tomáš Souček", "Michal Sadílek"],
    "Bosnia": ["Edin Džeko", "Ermedin Demirović"],
    "DR Congo": ["Cédric Bakambu", "Yoane Wissa"],
    "Iraq": ["Aymen Hussein", "Zidane Iqbal"],
    "Norway": ["Erling Haaland", "Martin Ødegaard", "Alexander Sørloth"],
    "Sweden": ["Viktor Gyökeres", "Dejan Kulusevski"],
    "Turkey": ["Hakan Çalhanoğlu", "Arda Güler", "Kerem Aktürkoğlu"],
    "Germany": ["Jamal Musiala", "Niclas Füllkrug", "Florian Wirtz", "Kai Havertz"],
    "Curaçao": ["Leandro Bacuna", "Roly Bonevacia"],
    "Ivory Coast": ["Sébastien Haller", "Nicolas Pépé", "Franck Kessié"],
    "Ecuador": ["Enner Valencia", "Moises Caicedo", "Pervis Estupiñán"],
    "Argentina": ["Lionel Messi", "Lautaro Martínez", "Ángel Di María", "Julián Álvarez"],
    "Algeria": ["Riyad Mahrez", "Youcef Atal", "Islam Slimani"],
    "Austria": ["Marcel Sabitzer", "Marko Arnautović", "Christoph Baumgartner"],
    "Jordan": ["Musa Al-Taamari", "Yazan Al-Naimat"],
    "Portugal": ["Cristiano Ronaldo", "Bernardo Silva", "Rafael Leão", "Bruno Fernandes"],
    "Uzbekistan": ["Eldor Shomurodov", "Jasurbek Yakhshibekov"],
    "Colombia": ["Luis Díaz", "James Rodríguez", "Luis Sinisterra", "Rafael Santos Borré"],
    "Ghana": ["Mohammed Kudus", "Jordan Ayew", "Inaki Williams"],
    "England": ["Harry Kane", "Bukayo Saka", "Phil Foden", "Jude Bellingham"],
    "Croatia": ["Luka Modrić", "Bruno Petković", "Marko Livaja"],
    "Panama": ["José Fajardo", "Adalberto Carrasquilla"],
    "Brazil": ["Vinícius Júnior", "Richarlison", "Rodrygo", "Neymar"],
    "France": ["Kylian Mbappé", "Olivier Giroud", "Antoine Griezmann", "Ousmane Dembélé"],
    "Spain": ["Álvaro Morata", "Lamine Yamal", "Nico Williams", "Dani Olmo"],
    "Netherlands": ["Memphis Depay", "Cody Gakpo", "Steven Bergwijn"],
    "Japan": ["Kaoru Mitoma", "Takefusa Kubo", "Daizen Maeda"],
    "Morocco": ["Achraf Hakimi", "Youssef En-Nesyri", "Sofiane Boufal"],
}

# Full tournament squads where we have verified 26-man lists.
TEAM_FULL_SQUAD: dict[str, list[str]] = {
    "Australia": [
        "Mathew Ryan", "Milos Degenek", "Alessandro Circati", "Jacob Italiano",
        "Jordan Bos", "Jason Geria", "Mathew Leckie", "Connor Metcalfe",
        "Mohamed Toure", "Ajdin Hrustic", "Awer Mabil", "Paul Izzo",
        "Aiden O'Neill", "Cameron Devlin", "Kai Trewin", "Aziz Behich",
        "Nestory Irankunda", "Patrick Beach", "Harry Souttar", "Cristian Volpato",
        "Cameron Burgess", "Jackson Irvine", "Nishan Velupillay",
        "Paul Okon-Engstler", "Lucas Herrington", "Tete Yengi",
    ],
}


def _strip(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)
    )


def _surname(name: str) -> str:
    toks = _strip(name).lower().replace(",", " ").split()
    return toks[-1] if toks else ""


def get_attackers(team: str, max_players: int = 4) -> list[str]:
    squad = TEAM_SQUAD.get(team, [])
    if squad:
        return squad[:max_players]
    return [f"{team} Forward", f"{team} Midfielder"][:max_players]


def get_squad(team: str) -> list[str]:
    """Full tournament squad if known, else the attacker short-list."""
    return list(TEAM_FULL_SQUAD.get(team) or TEAM_SQUAD.get(team, []))


def _names_same_player(a: str, b: str) -> bool:
    """True when two labels refer to the same person (not just same surname)."""
    sa = _strip(a).lower().replace(",", " ").split()
    sb = _strip(b).lower().replace(",", " ").split()
    if not sa or not sb:
        return False
    if _strip(a).lower() == _strip(b).lower():
        return True
    if sa[-1] != sb[-1] or len(sa[-1]) <= 2:
        return False
    fa, fb = sa[0], sb[0]
    if fa == fb:
        return True
    if len(fa) == 1 and fb.startswith(fa):
        return True
    if len(fb) == 1 and fa.startswith(fb):
        return True
    return False


def player_on_squad(team: str, player_name: str) -> bool:
    """True when *player_name* matches a listed squad member."""
    for member in get_squad(team):
        if _names_same_player(player_name, member):
            return True
    return False


def player_goal_eligible(home: str, away: str, selection: str) -> bool:
    """Goalscorer recs: listed attackers only (avoids Lisandro/Lautaro Martínez clashes)."""
    for team in (home, away):
        for attacker in get_attackers(team, 8):
            if _names_same_player(selection, attacker):
                return True
    return False


# Backward compat
TEAM_STARS = {k: v[:2] for k, v in TEAM_SQUAD.items()}


def add_player_props(match, odds_list: list, estimates: list, hl: float, al: float) -> None:
    """Add anytime goalscorer markets for squad attackers."""
    from bet_placer.markets.odds import decimal_to_implied
    from bet_placer.models.enums import MarketType
    from bet_placer.models.types import MarketOdds, ProbabilityEstimate

    home_stars = get_attackers(match.home_team, 4)
    away_stars = get_attackers(match.away_team, 4)
    shares = [0.35, 0.22, 0.14, 0.10]

    for i, player in enumerate(home_stars):
        share = shares[i] if i < len(shares) else 0.08
        prob = min(0.55, (hl / 2.5) * share * 0.9)
        odds = max(1.8, round(1 / prob * 0.94, 2))
        odds_list.append(MarketOdds(
            market=MarketType.PLAYER_GOAL, selection=player, line=None,
            best_odds=odds, avg_odds=odds,
            implied_probability=decimal_to_implied(odds), bookmaker_count=5,
        ))
        estimates.append(ProbabilityEstimate(
            market=MarketType.PLAYER_GOAL, selection=player, line=None,
            probability=prob, confidence=0.55,
            model_contributions={"xg_share": prob},
        ))

    for i, player in enumerate(away_stars):
        share = shares[i] if i < len(shares) else 0.08
        prob = min(0.55, (al / 2.5) * share * 0.9)
        odds = max(1.8, round(1 / prob * 0.94, 2))
        odds_list.append(MarketOdds(
            market=MarketType.PLAYER_GOAL, selection=player, line=None,
            best_odds=odds, avg_odds=odds,
            implied_probability=decimal_to_implied(odds), bookmaker_count=5,
        ))
        estimates.append(ProbabilityEstimate(
            market=MarketType.PLAYER_GOAL, selection=player, line=None,
            probability=prob, confidence=0.55,
            model_contributions={"xg_share": prob},
        ))
