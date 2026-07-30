"""Resolve team strength from Elo / ratings for any sport.

League boards stamp flat home/away xG priors (1.45 / 1.20). That makes every
home side look like a slight favourite unless we overwrite with real ratings
before analyze / stats strip / GBM features.
"""

from __future__ import annotations

from typing import Any

from bet_placer.data.team_names import canon_team

# Soccer Elo → attack rate. Keep rates in a realistic club band (~0.6–2.8);
# a linear (elo-1500)*0.012 mapping used to blow top clubs past 6 xG on the strip.
_SOCCER_HOME_ADV_XG = 0.12


def sport_from_match(match: Any) -> str:
    """Soccer / basketball / cricket from a Match object or board dict."""
    if match is None:
        return "soccer"
    if isinstance(match, dict):
        raw = str(match.get("sport") or match.get("sport_key") or match.get("id") or "").strip().lower()
        league = str(match.get("league") or "").lower()
    else:
        raw = str(
            getattr(match, "sport_key", None)
            or getattr(match, "sport", None)
            or getattr(match, "id", None)
            or ""
        ).strip().lower()
        league = str(getattr(match, "league", None) or "").lower()
    blob = f"{raw} {league}"
    if raw.startswith("basket") or any(k in blob for k in ("nba", "wnba", "ncaa", "fiba", "nbl", "basketball")):
        return "basketball"
    if raw.startswith("cricket") or any(
        k in blob for k in ("cricket", "ipl", "t20", "t20i", "bbl", "hundred", "psl", "cpl")
    ):
        return "cricket"
    if "odi" in blob.split() or "test match" in blob or "test cricket" in blob:
        return "cricket"
    return "soccer"


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _lookup_in_table(table: dict[str, Any] | None, team: str) -> float | None:
    """Best Elo for a team in a raw ratings dict (canon + alias scan, keep max)."""
    if not isinstance(table, dict) or not team:
        return None
    keys = [team]
    c = canon_team(team)
    if c and c not in keys:
        keys.append(c)
    best: float | None = None
    for key in keys:
        hit = _as_float(table.get(key))
        if hit is not None and (best is None or hit > best):
            best = hit
    # Orphan spellings that canonicalize to the same club
    for k, v in table.items():
        if canon_team(str(k)) != c:
            continue
        hit = _as_float(v)
        if hit is not None and (best is None or hit > best):
            best = hit
    return best


def resolve_team_elo(
    team: str,
    *,
    sport: str = "soccer",
    elo_model: Any = None,
    elo_by_sport: dict[str, Any] | None = None,
    elo: Any = None,
    params: dict[str, Any] | None = None,
) -> float | None:
    """Best available Elo for a club/side across sport buckets + ratings fallback.

    Accepts EloModel instances, raw ``dict`` tables, or a full ``load_params()``
    payload via ``params=`` (``elo`` + ``elo_by_sport``).
    """
    name = str(team or "").strip()
    if not name:
        return None
    sport_key = str(sport or "soccer").strip().lower() or "soccer"

    if isinstance(params, dict):
        if elo is None:
            elo = params.get("elo")
        if elo_by_sport is None:
            elo_by_sport = params.get("elo_by_sport")

    best: float | None = None

    def _consider(val: float | None) -> None:
        nonlocal best
        if val is None:
            return
        if best is None or val > best:
            best = val

    # Explicit EloModel-like objects
    for model in (elo_model, elo if not isinstance(elo, dict) else None):
        if model is None:
            continue
        getter = getattr(model, "get_rating", None)
        if callable(getter):
            try:
                _consider(float(getter(name, sport_key)))
            except Exception:
                try:
                    _consider(float(getter(name)))
                except Exception:
                    pass
            continue
        getter = getattr(model, "get", None)
        if callable(getter):
            try:
                _consider(_as_float(getter(name)))
            except Exception:
                pass

    # Raw dict from params["elo"]
    if isinstance(elo, dict):
        _consider(_lookup_in_table(elo, name))

    # Per-sport tables (dict of dict, or dict of EloModel)
    if isinstance(elo_by_sport, dict):
        for sk in (sport_key, "soccer", "basketball", "cricket"):
            tbl = elo_by_sport.get(sk)
            if tbl is None:
                continue
            if isinstance(tbl, dict):
                _consider(_lookup_in_table(tbl, name))
            else:
                getter = getattr(tbl, "get_rating", None)
                if callable(getter):
                    try:
                        _consider(float(getter(name, sk)))
                    except Exception:
                        pass
        for tbl in elo_by_sport.values():
            if isinstance(tbl, dict):
                _consider(_lookup_in_table(tbl, name))

    if best is not None:
        return best

    # Static / reputation fallback on Elo scale
    try:
        from bet_placer.data.team_ratings import lookup_rating

        r = lookup_rating(name, sport=sport_key)
        if r is None and sport_key != "soccer":
            r = lookup_rating(name, sport="soccer")
        if r is not None:
            return float(r)
    except Exception:
        pass
    return None


def soccer_xg_from_rating(rating: float) -> float:
    """Map Elo (~1200–2100) onto a realistic goals-for expectation."""
    strength = max(20.0, min(97.0, 45.0 + (float(rating) - 1550.0) * 0.0961))
    return max(0.45, min(2.85, 0.55 + (strength / 100.0) * 2.15))


def _set_team_stats_rates(stats: Any, attack: float, defence: float) -> None:
    if stats is None:
        return
    for attr, val in (
        ("xg", attack),
        ("xga", defence),
        ("goals_scored", attack),
        ("goals_conceded", defence),
    ):
        if hasattr(stats, attr):
            setattr(stats, attr, round(float(val), 3))


def apply_strength_stats(match: Any, params: dict[str, Any] | None = None) -> Any:
    """Overwrite flat board priors with Elo/rating-based attack/defence rates.

    Works on ``Match`` objects (mutates ``home_stats`` / ``away_stats``) and on
    plain dicts used by older board helpers.
    """
    if match is None:
        return match

    is_dict = isinstance(match, dict)
    sport = sport_from_match(match)
    home = str((match.get("home_team") if is_dict else getattr(match, "home_team", None)) or "").strip()
    away = str((match.get("away_team") if is_dict else getattr(match, "away_team", None)) or "").strip()
    if not home or not away:
        return match

    if params is None:
        try:
            from bet_placer.ml.params import load_params

            params = load_params()
        except Exception:
            params = {}

    hr = resolve_team_elo(home, sport=sport, params=params)
    ar = resolve_team_elo(away, sport=sport, params=params)
    if hr is None and ar is None:
        return match

    if sport == "soccer":
        if hr is None:
            hr = 1500.0
        if ar is None:
            ar = 1500.0
        hx = soccer_xg_from_rating(hr) + _SOCCER_HOME_ADV_XG
        ax = soccer_xg_from_rating(ar)
        if is_dict:
            match["home_xg"] = round(hx, 3)
            match["away_xg"] = round(ax, 3)
            match["home_xga"] = round(ax, 3)
            match["away_xga"] = round(hx, 3)
            match["home_gf"] = round(hx, 3)
            match["away_gf"] = round(ax, 3)
            match["home_ga"] = round(ax, 3)
            match["away_ga"] = round(hx, 3)
            match["home_elo"] = round(hr, 1)
            match["away_elo"] = round(ar, 1)
        else:
            _set_team_stats_rates(getattr(match, "home_stats", None), hx, ax)
            _set_team_stats_rates(getattr(match, "away_stats", None), ax, hx)
            try:
                setattr(match, "home_elo", round(hr, 1))
                setattr(match, "away_elo", round(ar, 1))
            except Exception:
                pass
    elif sport == "basketball":
        # Bias points priors toward the stronger Elo side when we have both.
        if hr is not None and ar is not None:
            diff = (hr - ar) / 400.0
            if is_dict:
                base_h = float(match.get("home_ppg") or match.get("home_xg") or 112.0)
                base_a = float(match.get("away_ppg") or match.get("away_xg") or 110.0)
                match["home_ppg"] = round(base_h + 6.0 * diff, 2)
                match["away_ppg"] = round(base_a - 4.0 * diff, 2)
                match["home_elo"] = round(hr, 1)
                match["away_elo"] = round(ar, 1)
            else:
                hs = getattr(match, "home_stats", None)
                aws = getattr(match, "away_stats", None)
                base_h = float(getattr(hs, "xg", None) or getattr(hs, "goals_scored", None) or 112.0)
                base_a = float(getattr(aws, "xg", None) or getattr(aws, "goals_scored", None) or 110.0)
                _set_team_stats_rates(hs, base_h + 6.0 * diff, base_a - 2.0 * diff)
                _set_team_stats_rates(aws, base_a - 4.0 * diff, base_h + 2.0 * diff)
    elif sport == "cricket":
        if is_dict:
            if hr is not None:
                match["home_elo"] = round(hr, 1)
            if ar is not None:
                match["away_elo"] = round(ar, 1)
        else:
            # Soft-touch on TeamStats so GBM/xG features aren't flat-home-favoured
            if hr is not None and ar is not None:
                diff = (hr - ar) / 400.0
                hs = getattr(match, "home_stats", None)
                aws = getattr(match, "away_stats", None)
                base_h = float(getattr(hs, "xg", None) or 1.35)
                base_a = float(getattr(aws, "xg", None) or 1.30)
                _set_team_stats_rates(hs, base_h + 0.25 * diff, base_a - 0.15 * diff)
                _set_team_stats_rates(aws, base_a - 0.20 * diff, base_h + 0.10 * diff)
    return match
