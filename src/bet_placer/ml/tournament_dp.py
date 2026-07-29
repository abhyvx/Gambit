"""Knockout tournament odds via bottom-up dynamic programming.

Uses exact Poisson match win rates (no Monte Carlo). Memoized on fixture state.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from bet_placer.data.team_ratings import blended_strength, get_team_rating, rating_to_xg
from bet_placer.data.wc_stages import (
    STAGE_FINAL,
    STAGE_QF,
    STAGE_R16,
    STAGE_R32,
    STAGE_SF,
    is_bracket_placeholder,
)
from bet_placer.data.worldcup2026 import WCMatch, get_group_standings
from bet_placer.ml.poisson import match_outcome_probs
from bet_placer.models.types import ChemistrySignals, LeagueProfile, Match, TeamStats

_TOP_K = 5
_R16_WINNER_RE = re.compile(r"round of 16\s+(\d+)\s+winner", re.I)
_QF_WINNER_RE = re.compile(r"quarterfinal\s+(\d+)\s+winner", re.I)

_QF_SLOT_R16_INDEX = {1: 8, 2: 10, 3: 9, 4: 11}

WinDist = dict[str, float]


@dataclass
class _KnockoutMatch:
    stage: int
    index: int
    home: str
    away: str
    wc: WCMatch | None = None
    p_home: float = 0.5
    p_away: float = 0.5
    winner: str | None = None


def compute_tournament_odds(
    all_wc_matches: list[WCMatch],
    *,
    completed_only: bool = False,
) -> dict:
    """Return champion / reach-round odds and top paths to the title."""
    return collapse_tournament_odds(all_wc_matches, completed_only=completed_only)


def collapse_tournament_odds(
    all_wc_matches: list[WCMatch],
    *,
    completed_only: bool = False,
) -> dict:
    fp = _matches_fingerprint(all_wc_matches)
    return _collapse_cached(fp, completed_only)


@lru_cache(maxsize=16)
def _collapse_cached(fingerprint: str, completed_only: bool) -> dict:
    matches = _FINGERPRINT_STORE.get(fingerprint, [])
    return _compute_from_matches(matches, completed_only=completed_only)


_FINGERPRINT_STORE: dict[str, list[WCMatch]] = {}


def _matches_fingerprint(matches: list[WCMatch]) -> str:
    parts = []
    for m in sorted(matches, key=lambda x: (x.matchday, x.kickoff, x.id)):
        parts.append(
            f"{m.id}|{m.matchday}|{m.home}|{m.away}|{m.status}|"
            f"{m.home_score}|{m.away_score}|{m.is_knockout}"
        )
    fp = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]
    _FINGERPRINT_STORE[fp] = list(matches)
    return fp


def _compute_from_matches(all_wc: list[WCMatch], *, completed_only: bool) -> dict:
    t0 = time.perf_counter()
    knockout = [m for m in all_wc if m.is_knockout]
    if completed_only:
        knockout = [m for m in knockout if m.status == "completed"]

    win_cache: dict[tuple[str, str], tuple[float, float]] = {}
    rounds = _organize_knockout_rounds(knockout, all_wc, win_cache)

    r32 = rounds.get(STAGE_R32, [])
    r16 = rounds.get(STAGE_R16, [])
    qf = rounds.get(STAGE_QF, [])
    sf = rounds.get(STAGE_SF, [])
    final_m = rounds.get(STAGE_FINAL, [])

    r32_dists = [_leaf_dist(km) for km in r32]
    r16_dists: list[WinDist] = []
    for km in r16:
        r16_dists.append(_resolve_match_dist(km, r16_dists, [], win_cache))
    qf_dists: list[WinDist] = []
    for km in qf:
        qf_dists.append(_resolve_match_dist(km, r16_dists, qf_dists, win_cache))

    sf_dists: list[WinDist] = []
    if sf:
        sf_dists = [_resolve_match_dist(km, r16_dists, qf_dists, win_cache) for km in sf]
    elif len(qf_dists) >= 2:
        sf_dists = [
            _merge_dists(qf_dists[0], qf_dists[1], win_cache),
            _merge_dists(qf_dists[2], qf_dists[3], win_cache) if len(qf_dists) >= 4 else {},
        ]

    champ: WinDist = {}
    if final_m:
        champ = _resolve_match_dist(final_m[0], r16_dists, qf_dists, win_cache)
    elif len(sf_dists) >= 2 and sf_dists[0] and sf_dists[1]:
        champ = _merge_dists(sf_dists[0], sf_dists[1], win_cache)
    elif qf_dists:
        acc: WinDist = {}
        for d in qf_dists:
            for t, p in d.items():
                acc[t] = acc.get(t, 0.0) + p
        total = sum(acc.values()) or 1.0
        champ = {t: p / total for t, p in acc.items()}

    reach_semis: WinDist = {}
    for d in qf_dists:
        for t, p in d.items():
            reach_semis[t] = reach_semis.get(t, 0.0) + p
    reach_semis = _normalize_dist(reach_semis)

    reach_final: WinDist = {}
    for d in sf_dists:
        for t, p in d.items():
            reach_final[t] = reach_final.get(t, 0.0) + p
    if not reach_final:
        reach_final = dict(reach_semis)
    reach_final = _normalize_dist(reach_final)

    top_paths = _top_champion_paths(champ, r32_dists, r16_dists)

    return {
        "champion_odds": _sorted_dist(champ),
        "reach_final": _sorted_dist(reach_final),
        "reach_semis": _sorted_dist(reach_semis),
        "top_paths": top_paths[:_TOP_K],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "compute_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _organize_knockout_rounds(
    knockout: list[WCMatch],
    all_wc: list[WCMatch],
    win_cache: dict[tuple[str, str], tuple[float, float]],
) -> dict[int, list[_KnockoutMatch]]:
    by_stage: dict[int, list[WCMatch]] = {}
    for m in knockout:
        by_stage.setdefault(m.matchday, []).append(m)

    out: dict[int, list[_KnockoutMatch]] = {}
    for stage, ms in by_stage.items():
        ms = sorted(ms, key=lambda x: x.kickoff)
        nodes: list[_KnockoutMatch] = []
        for i, wc in enumerate(ms):
            ph, pa, winner = _match_advance_probs(wc, all_wc, win_cache)
            nodes.append(_KnockoutMatch(stage, i, wc.home, wc.away, wc, ph, pa, winner))
        out[stage] = nodes
    return out


def _match_advance_probs(
    wc: WCMatch,
    all_wc: list[WCMatch],
    win_cache: dict[tuple[str, str], tuple[float, float]],
) -> tuple[float, float, str | None]:
    if wc.status == "completed" and wc.home_score is not None and wc.away_score is not None:
        if wc.home_score > wc.away_score:
            return 1.0, 0.0, wc.home
        if wc.away_score > wc.home_score:
            return 0.0, 1.0, wc.away
        return 0.5, 0.5, wc.home

    if is_bracket_placeholder(wc.home, wc.away):
        return 0.5, 0.5, None

    key = (wc.home, wc.away)
    if key not in win_cache:
        match = _light_match(wc, all_wc)
        probs = match_outcome_probs(match)
        ph, pd, pa = probs["home"], probs["draw"], probs["away"]
        ph = ph + pd * 0.5
        pa = pa + pd * 0.5
        s = ph + pa
        if s > 0:
            ph, pa = ph / s, pa / s
        win_cache[key] = (ph, pa)
    return *win_cache[key], None


def _light_match(wc: WCMatch, all_wc: list[WCMatch]) -> Match:
    from bet_placer.data.odds_api import event_to_match
    from bet_placer.data.worldcup2026 import wc_match_to_event

    match = event_to_match(wc_match_to_event(wc), "soccer_fifa_world_cup")
    standings_pts: dict[str, int] = {}
    if not wc.is_knockout and wc.group:
        for s in get_group_standings(wc.group, all_wc):
            standings_pts[s["team"]] = s["pts"]

    home_str = blended_strength(wc.home, standings_pts.get(wc.home, 0), wc.home_morale)
    away_str = blended_strength(wc.away, standings_pts.get(wc.away, 0), wc.away_morale)
    match.home_stats = TeamStats(
        name=wc.home, xg=rating_to_xg(home_str), xga=rating_to_xg(away_str) * 0.85,
    )
    match.away_stats = TeamStats(
        name=wc.away, xg=rating_to_xg(away_str), xga=rating_to_xg(home_str) * 0.85,
    )
    match.league_profile = LeagueProfile(
        name=f"WC 2026 {'Knockout' if wc.is_knockout else 'Group ' + wc.group}",
        avg_goals_per_match=2.45 if wc.is_knockout else 2.55,
        home_advantage_factor=0.05 if wc.is_knockout else 0.08,
    )
    match.chemistry = ChemistrySignals(morale_home=wc.home_morale, morale_away=wc.away_morale)
    return match


def _leaf_dist(km: _KnockoutMatch) -> WinDist:
    if km.winner:
        return {km.winner: 1.0}
    return {km.home: km.p_home, km.away: km.p_away}


def _resolve_side(name: str, r16_dists: list[WinDist], qf_dists: list[WinDist]) -> WinDist | str:
    m = _R16_WINNER_RE.search(name or "")
    if m:
        idx = int(m.group(1)) - 1
        return r16_dists[idx] if 0 <= idx < len(r16_dists) else {}
    m = _QF_WINNER_RE.search(name or "")
    if m:
        slot = int(m.group(1))
        r16_idx = _QF_SLOT_R16_INDEX.get(slot)
        if r16_idx is not None and 0 <= r16_idx < len(r16_dists) and r16_dists[r16_idx]:
            return r16_dists[r16_idx]
        idx = slot - 1
        return qf_dists[idx] if 0 <= idx < len(qf_dists) else {}
    if is_bracket_placeholder(name, name):
        return {}
    return name


def _resolve_match_dist(
    km: _KnockoutMatch,
    r16_dists: list[WinDist],
    qf_dists: list[WinDist],
    win_cache: dict[tuple[str, str], tuple[float, float]],
) -> WinDist:
    if km.winner:
        return {km.winner: 1.0}

    home_side = _resolve_side(km.home, r16_dists, qf_dists)
    away_side = _resolve_side(km.away, r16_dists, qf_dists)

    if isinstance(home_side, dict) and isinstance(away_side, dict):
        return _merge_dists(home_side, away_side, win_cache)
    if isinstance(home_side, dict) and isinstance(away_side, str):
        return _dist_vs_team(home_side, away_side, win_cache)
    if isinstance(home_side, str) and isinstance(away_side, dict):
        return _dist_vs_team(away_side, home_side, win_cache, flip=True)
    if isinstance(home_side, str) and isinstance(away_side, str):
        ph, pa = _pair_win_probs(home_side, away_side, win_cache)
        return {home_side: ph, away_side: pa}
    return {}


def _dist_vs_team(
    dist: WinDist,
    team: str,
    win_cache: dict[tuple[str, str], tuple[float, float]],
    *,
    flip: bool = False,
) -> WinDist:
    out: WinDist = {}
    for t, pt in dist.items():
        if t == team:
            continue
        ph, pa = _pair_win_probs(t, team, win_cache)
        if flip:
            ph, pa = pa, ph
        out[t] = out.get(t, 0.0) + pt * ph
        out[team] = out.get(team, 0.0) + pt * pa
    return out


def _merge_dists(left: WinDist, right: WinDist, win_cache: dict[tuple[str, str], tuple[float, float]]) -> WinDist:
    out: WinDist = {}
    for t1, p1 in left.items():
        for t2, p2 in right.items():
            if t1 == t2:
                continue
            joint = p1 * p2
            ph, pa = _pair_win_probs(t1, t2, win_cache)
            out[t1] = out.get(t1, 0.0) + joint * ph
            out[t2] = out.get(t2, 0.0) + joint * pa
    return out


def _pair_win_probs(home: str, away: str, win_cache: dict[tuple[str, str], tuple[float, float]]) -> tuple[float, float]:
    key = (home, away)
    if key in win_cache:
        return win_cache[key]
    hr = get_team_rating(home)
    ar = get_team_rating(away)
    diff = (hr - ar) / 100.0
    ph = max(0.08, min(0.92, 0.5 + diff * 0.35))
    win_cache[key] = (ph, 1.0 - ph)
    return win_cache[key]


def _top_champion_paths(champ: WinDist, r32_dists: list[WinDist], r16_dists: list[WinDist]) -> list[dict]:
    if not champ:
        return []
    r32_teams = {t for d in r32_dists for t in d}
    out: list[dict] = []
    for team, prob in sorted(champ.items(), key=lambda kv: -kv[1])[:_TOP_K]:
        path = [team]
        if team not in r32_teams:
            for dist in r16_dists:
                if team in dist and dist[team] > 0.05:
                    path = [max(dist, key=dist.get), team] if max(dist, key=dist.get) != team else [team]
                    break
        out.append({"path": path, "prob": round(prob, 5)})
    return out


def _normalize_dist(d: WinDist) -> WinDist:
    s = sum(d.values())
    return d if s <= 0 else {k: v / s for k, v in d.items()}


def _sorted_dist(d: WinDist) -> dict[str, float]:
    return dict(sorted(d.items(), key=lambda kv: -kv[1]))


def top_path_summary(team: str, top_paths: list[dict]) -> str | None:
    for entry in top_paths:
        path = entry.get("path") or []
        if team in path:
            idx = path.index(team)
            return " → ".join(path[idx:idx + 4])
    return None
