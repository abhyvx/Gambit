"""World Cup team strength — reputation, squad quality, FIFA-style power rankings.

MD1 is ONE game. These ratings anchor predictions so Germany doesn't
collapse because of one result and Panama doesn't look like Brazil.
"""

TEAM_RATINGS: dict[str, float] = {
  # Elite
  "Argentina": 94, "France": 93, "Brazil": 92, "England": 90, "Spain": 89,
  "Germany": 88, "Portugal": 87, "Netherlands": 86, "Belgium": 85, "Croatia": 84,
  # Strong
  "USA": 78, "Mexico": 77, "Japan": 76, "South Korea": 75, "Colombia": 74,
  "Uruguay": 73, "Switzerland": 72, "Denmark": 71, "Senegal": 70, "Morocco": 69,
  "Austria": 68, "Turkey": 67, "Ukraine": 66, "Ecuador": 65,
  "Czech Republic": 64, "Norway": 70, "Sweden": 68, "Bosnia": 58, "DR Congo": 54, "Iraq": 52,
  # Mid
  "Australia": 63, "Poland": 62, "Wales": 61, "Scotland": 60, "Canada": 59,
  "Paraguay": 58, "Algeria": 57, "Egypt": 56, "Iran": 55, "Tunisia": 54,
  "Ivory Coast": 53, "Ghana": 52, "South Africa": 51, "Costa Rica": 50,
  "Saudi Arabia": 49, "Qatar": 48, "Panama": 47, "Jordan": 46, "Uzbekistan": 45,
  # Weaker
  "Curaçao": 42, "Haiti": 41, "New Zealand": 40, "Cape Verde": 39,
  "Norway": 62, "IC Winner 2": 55,
}

# How much MD1 form shifts the rating (small — one game ≠ season)
MD1_FORM_WEIGHT = 0.12


def _elo_to_rating(elo: float) -> float:
    """Map a learned Elo (~1400-2060) onto the familiar 0-100 strength scale."""
    return max(20.0, min(97.0, 45.0 + (elo - 1550.0) * 0.0961))


def _rating_to_elo(rating: float) -> float:
    """Inverse of `_elo_to_rating` — turns a curated 0-100 rating into Elo scale."""
    return 1550.0 + (rating - 45.0) / 0.0961


# How much we trust the raw learned Elo vs. the curated reputation prior.
# Pure win/loss Elo over-rewards sides that farm weak confederation opponents
# (e.g. Australia historically beating Oceania minnows), inflating them above
# stronger teams. Blending toward reputation is Bayesian shrinkage that keeps
# the data signal while killing those distortions.
ELO_REP_WEIGHT = 0.5

_CANON_RATINGS: dict[str, float] | None = None


def _canon_ratings() -> dict[str, float]:
    global _CANON_RATINGS
    if _CANON_RATINGS is None:
        try:
            from bet_placer.data.team_names import canon_team
            _CANON_RATINGS = {canon_team(k): v for k, v in TEAM_RATINGS.items()}
        except Exception:
            _CANON_RATINGS = {}
    return _CANON_RATINGS


def reputation_rating(team: str) -> float | None:
    """Curated reputation on the 0-100 scale, robust to name variants."""
    if team in TEAM_RATINGS:
        return TEAM_RATINGS[team]
    try:
        from bet_placer.data.team_names import canon_team
        return _canon_ratings().get(canon_team(team))
    except Exception:
        return None


def blended_elo(team: str, learned_elo: float | None) -> float | None:
    """Learned Elo shrunk toward the team's curated reputation prior."""
    rep = reputation_rating(team)
    rep_elo = _rating_to_elo(rep) if rep is not None else None
    if learned_elo is None:
        return rep_elo
    if rep_elo is None:
        return learned_elo
    return ELO_REP_WEIGHT * learned_elo + (1.0 - ELO_REP_WEIGHT) * rep_elo


def get_team_rating(team: str) -> float:
    """Team strength on a 0-100 scale.

    Blends the Elo learned from ~49k real matches with a curated reputation
    prior (so confederation-farming sides don't get inflated), and keeps the
    displayed ranking, analyst factors, and the model all in agreement.
    """
    try:
        from bet_placer.data.team_names import canon_team
        from bet_placer.ml.params import load_params
        elo = (load_params().get("elo") or {}).get(canon_team(team))
        be = blended_elo(team, float(elo) if elo is not None else None)
        if be is not None:
            return round(_elo_to_rating(be), 1)
    except Exception:
        pass
    return TEAM_RATINGS.get(team, 50.0)


def rating_to_xg(rating: float) -> float:
    """Convert 0-100 rating to expected goals per match."""
    return 0.6 + (rating / 100) * 2.2


def blended_strength(team: str, md1_pts: int = 0, morale: float = 5.0) -> float:
    """Team quality + tiny MD1 nudge + morale. Fan-realistic."""
    base = get_team_rating(team)
    md1_boost = {0: -3, 1: 0, 3: 4}.get(md1_pts, 0)  # win=3pts, draw=1, loss=0
    morale_boost = (morale - 5.0) * 1.5
    return base + md1_boost * MD1_FORM_WEIGHT * 10 + morale_boost


def fan_read(home: str, away: str, home_pts: int, away_pts: int, home_must_win: bool, away_must_win: bool) -> str:
    """One-paragraph fan take — not robot stats."""
    hs = blended_strength(home, home_pts)
    aw = blended_strength(away, away_pts)
    diff = hs - aw

    if diff > 15:
        fav = home
        lean = f"{home} are the better side on paper and should control this at home."
    elif diff < -15:
        fav = away
        lean = f"{away} are clearly stronger — {home} need something special."
    elif abs(diff) < 5:
        lean = f"Tight game. {home} vs {away} — either team can win, could go either way."
    elif diff > 0:
        lean = f"Slight edge to {home}, but {away} can definitely hurt them on the counter."
    else:
        lean = f"{away} probably have more quality, but {home} at a World Cup are dangerous."

    extras = []
    if home_must_win:
        extras.append(f"{home} NEED points — they'll come out firing, but desperation can backfire")
    if away_must_win:
        extras.append(f"{away} are in must-win mode — expect them to push hard")
    if home_pts >= 3:
        extras.append(f"{home} won MD1 so confidence is high")
    if away_pts >= 3:
        extras.append(f"{away} won MD1 and travel with momentum")

    extra = ". ".join(extras)
    return f"{lean} {extra}." if extra else lean
