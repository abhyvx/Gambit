"""Score-matrix probability engine — rate (almost) ANY Stake market.

Instead of relying on a handful of pre-computed lines, this derives the
probability of a market directly from the Poisson score matrix (and small
half-time matrices + corner/card Poisson models). That lets us attach an honest
"our chance" read to the vast majority of Stake outcomes: result, double chance,
DNB, totals (any line), exact goals, correct score, BTTS, clean sheets, team
totals, Asian handicaps (any line), odd/even, winning margin, HT/FT, halves,
and goal-based combos ("Team & Over 2.5").

Pure player props (a specific player to score/be booked) are NOT modelled here —
we return None so the UI honestly shows "no strong read" rather than a fake edge.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson

from bet_placer.ml.poisson import expected_goals, score_matrix
from bet_placer.engine.stake_odds import _parse_handicap_outcome, _team_match, _tokens

_N = 10  # max goals per side in the full-time matrix


def _result(margin_mask, M):
    return float(M[margin_mask].sum())


class MatchModel:
    def __init__(self, match, home: str, away: str):
        self.home = home
        self.away = away
        hl, al = expected_goals(match)
        self.hl, self.al = hl, al
        self.M = score_matrix(hl, al, max_goals=_N)
        # Half matrices — ~45% of goals in H1, ~55% in H2.
        self.H1 = score_matrix(hl * 0.45, al * 0.45, max_goals=7)
        self.H2 = score_matrix(hl * 0.55, al * 0.55, max_goals=7)

        H = np.arange(_N + 1)[:, None]
        A = np.arange(_N + 1)[None, :]
        self.TOT = H + A
        self.MAR = H - A
        self.home_goals = self.M.sum(axis=1)  # marginal home dist
        self.away_goals = self.M.sum(axis=0)

        # Corners & cards expectations (team-level only).
        avg_c = match.league_profile.avg_corners if match.league_profile else 10.0
        self.corners_exp = max(7.0, avg_c + (hl + al - 2.6) * 0.9)
        self.cards_exp = 4.6  # tournament baseline; intel nudges happen elsewhere

    # ---- generic helpers over a matrix ----
    def _tot_over(self, M, line):
        H = np.arange(M.shape[0])[:, None]
        A = np.arange(M.shape[1])[None, :]
        tot = H + A
        over = float(M[tot > line].sum())
        under = float(M[tot < line].sum())
        if abs(line - round(line)) < 1e-6 and (over + under) > 0:  # integer → strip push
            over = over / (over + under)
        return over

    def _btts(self, M):
        return 1.0 - float(M[0, :].sum()) - float(M[:, 0].sum()) + float(M[0, 0])

    def _half_total_dist(self, M):
        H = np.arange(M.shape[0])[:, None]
        A = np.arange(M.shape[1])[None, :]
        tot = (H + A).ravel()
        flat = M.ravel()
        d = {}
        for t, p in zip(tot, flat):
            d[int(t)] = d.get(int(t), 0.0) + float(p)
        return d

    # ---- result family on the full matrix ----
    def result_prob(self, sel):
        if sel == "home":
            return _result(self.MAR > 0, self.M)
        if sel == "draw":
            return _result(self.MAR == 0, self.M)
        if sel == "away":
            return _result(self.MAR < 0, self.M)
        return None

    def dc_prob(self, sel):
        if sel == "home_draw":
            return _result(self.MAR >= 0, self.M)
        if sel == "draw_away":
            return _result(self.MAR <= 0, self.M)
        if sel == "home_away":
            return _result(self.MAR != 0, self.M)
        return None

    def dnb_prob(self, sel):
        h = self.result_prob("home")
        a = self.result_prob("away")
        if h + a == 0:
            return None
        return h / (h + a) if sel == "home" else a / (h + a)

    def handicap_prob(self, side, line):
        """Asian handicap win-probability (quarter lines averaged)."""
        def settle(c):
            # line c applied to `side`. win if adjusted margin > 0, strip push.
            if side == "home":
                win = float(self.M[(self.MAR + c) > 0].sum())
                lose = float(self.M[(self.MAR + c) < 0].sum())
            else:
                win = float(self.M[(-self.MAR + c) > 0].sum())
                lose = float(self.M[(-self.MAR + c) < 0].sum())
            return win / (win + lose) if (win + lose) > 0 else None
        # quarter line → average of the two adjacent half/whole lines
        if abs((line * 4) % 2) > 1e-6:  # .25 / .75
            lo, hi = line - 0.25, line + 0.25
            a, b = settle(lo), settle(hi)
            if a is None or b is None:
                return None
            return (a + b) / 2
        return settle(line)

    def team_total_over(self, team, line):
        dist = self.home_goals if _team_match(team, self.home) else self.away_goals
        idx = np.arange(len(dist))
        over = float(dist[idx > line].sum())
        under = float(dist[idx < line].sum())
        if abs(line - round(line)) < 1e-6 and (over + under) > 0:
            over = over / (over + under)
        return over

    def clean_sheet(self, team):
        # team keeps a clean sheet → opponent scores 0
        if _team_match(team, self.home):
            return float(self.away_goals[0])
        return float(self.home_goals[0])


# ---------------------------------------------------------------------------
# Dispatch: Stake (market_name, outcome_name, line) -> probability or None
# ---------------------------------------------------------------------------

def _ou(name: str) -> str | None:
    n = name.lower()
    if "over" in n:
        return "over"
    if "under" in n:
        return "under"
    return None


def rate_outcome(mm: MatchModel, market_name: str, outcome_name: str, line, home: str, away: str):
    n = (market_name or "").lower()
    s = (outcome_name or "").strip()
    sl = s.lower()

    # ---- combos: "A & B" ----
    if "&" in (market_name or "") or "&" in s:
        return _rate_combo(mm, market_name, s, home, away)

    # ---- halves ----
    half = None
    if n.startswith("1st half") or "1st half" in n or "first half" in n:
        half = mm.H1
    elif n.startswith("2nd half") or "2nd half" in n or "second half" in n:
        half = mm.H2

    # ---- correct score ----
    if "correct score" in n:
        M = half if half is not None else mm.M
        cs = _parse_score(s)
        if cs and cs[0] < M.shape[0] and cs[1] < M.shape[1]:
            return float(M[cs[0], cs[1]])
        if sl in ("any other", "other"):
            return None
        return None

    # ---- exact total goals ----
    if "exact" in n and "goal" in n:
        M = half if half is not None else mm.M
        d = mm._half_total_dist(M)
        m = _int(s)
        if m is not None:
            if "+" in s or "or more" in sl:
                return float(sum(p for t, p in d.items() if t >= m))
            return float(d.get(m, 0.0))
        return None

    # ---- odd / even total ----
    if "odd" in n and "even" in n:
        M = half if half is not None else mm.M
        d = mm._half_total_dist(M)
        even = sum(p for t, p in d.items() if t % 2 == 0)
        if "even" in sl:
            return float(even)
        if "odd" in sl:
            return float(1 - even)
        return None

    # ---- both teams to score ----
    if "both teams to score" in n or n == "btts":
        M = half if half is not None else mm.M
        y = mm._btts(M)
        if sl in ("yes", "y"):
            return y
        if sl in ("no", "n"):
            return 1 - y
        return None

    # ---- totals (asian total / over-under goals / team totals) ----
    if "corner" in n:
        return _rate_corners(mm, n, s, line, home, away)
    if "booking" in n or "card" in n:
        return _rate_cards(mm, n, s, line, home, away)

    if "total" in n or "asian total" in n or "over/under" in n or "goals over" in n:
        team = _leading_team(market_name, home, away)
        ou = _ou(s)
        ln = line if line is not None else _line_from(s)
        if ou and ln is not None:
            if team is not None:
                p = mm.team_total_over(team, ln)
                return p if ou == "over" else 1 - p
            M = half if half is not None else mm.M
            p = mm._tot_over(M, ln)
            return p if ou == "over" else 1 - p
        return None

    # ---- clean sheet ----
    if "clean sheet" in n:
        team = _leading_team(market_name, home, away)
        if team is None:
            team = home if _team_match(s, home) else (away if _team_match(s, away) else None)
        if team and sl in ("yes", "y"):
            return mm.clean_sheet(team)
        if team and sl in ("no", "n"):
            return 1 - mm.clean_sheet(team)
        return None

    # ---- handicap ----
    if "handicap" in n:
        team, hcp = _parse_handicap_outcome(s)
        if hcp is None:
            return None
        side = "home" if _team_match(team, home) else ("away" if _team_match(team, away) else None)
        return mm.handicap_prob(side, hcp) if side else None

    # ---- HT/FT ----
    if "halftime" in n.replace(" ", "") or "ht/ft" in n or ("half" in n and "full" in n):
        return _rate_htft(mm, s, home, away)

    # ---- highest scoring half ----
    if "highest scoring half" in n:
        return _rate_highest_half(mm, sl)

    # ---- result family (1x2 + half result) ----
    if n in ("1x2", "match result", "full time result") or "1x2" in n or (half is not None and "result" in n):
        M = half if half is not None else mm.M
        sel = _result_sel(s, home, away)
        if sel:
            if sel == "home":
                return _result((np.arange(M.shape[0])[:, None] - np.arange(M.shape[1])[None, :]) > 0, M)
            if sel == "draw":
                return _result((np.arange(M.shape[0])[:, None] - np.arange(M.shape[1])[None, :]) == 0, M)
            if sel == "away":
                return _result((np.arange(M.shape[0])[:, None] - np.arange(M.shape[1])[None, :]) < 0, M)
        return None
    if "double chance" in n:
        sel = _dc_sel(s, home, away)
        return mm.dc_prob(sel) if sel else None
    if "draw no bet" in n:
        if _team_match(s, home):
            return mm.dnb_prob("home")
        if _team_match(s, away):
            return mm.dnb_prob("away")
        return None

    # ---- winning margin ----
    if "winning margin" in n or "margin" in n:
        return _rate_margin(mm, s, home, away)

    return None


# ---- small parsers ----

def _int(s):
    import re
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _line_from(s):
    import re
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _parse_score(s):
    import re
    m = re.search(r"(\d+)\s*[-:]\s*(\d+)", s)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _result_sel(s, home, away):
    if _team_match(s, home):
        return "home"
    if _team_match(s, away):
        return "away"
    if s.lower() in ("draw", "x", "tie"):
        return "draw"
    return None


def _dc_sel(s, home, away):
    toks = _tokens(s)
    h = bool(toks & _tokens(home))
    a = bool(toks & _tokens(away))
    d = bool(toks & {"draw", "x"})
    if h and d:
        return "home_draw"
    if a and d:
        return "draw_away"
    if h and a:
        return "home_away"
    return None


def _leading_team(market_name, home, away):
    """A team named *inside* a market label, e.g. 'Uzbekistan Total'."""
    toks = _tokens(market_name or "")
    if not toks:
        return None
    if _tokens(home) and _tokens(home) <= toks:
        return home
    if _tokens(away) and _tokens(away) <= toks:
        return away
    return None


def _team_in_name(n, team):
    return bool(_tokens(team)) and _tokens(team) <= _tokens(n)


def _scope_mult(n, mm, home, away):
    """Scale a full-match expectation down for half/team-specific markets."""
    mult = 1.0
    if "1st half" in n or "first half" in n:
        mult *= 0.42
    elif "2nd half" in n or "second half" in n:
        mult *= 0.58
    if _team_in_name(n, home):
        mult *= mm.hl / (mm.hl + mm.al)
    elif _team_in_name(n, away):
        mult *= mm.al / (mm.hl + mm.al)
    return mult


def _over_under(exp, ln, ou):
    over = float(1 - poisson.cdf(ln, exp))
    if abs(ln - round(ln)) < 1e-6:  # integer line → strip push mass
        under = float(poisson.cdf(ln - 1, exp))
        tot = over + under
        over = over / tot if tot else over
    return over if ou == "over" else 1 - over


def _rate_corners(mm, n, s, line, home, away):
    exp = mm.corners_exp * _scope_mult(n, mm, home, away)
    ou = _ou(s)
    ln = line if line is not None else _line_from(s)
    if ou and ln is not None:
        return _over_under(exp, ln, ou)
    rng = _parse_score(s)  # range like "9 - 11"
    if rng:
        lo, hi = rng
        return float(poisson.cdf(hi, exp) - poisson.cdf(lo - 1, exp))
    if "odd" in s.lower() or "even" in s.lower():
        return 0.5
    return None


def _rate_cards(mm, n, s, line, home, away):
    # booking POINTS (yellow=10, red=25) is a different unit — don't fake it
    if "point" in n:
        return None
    if "player" in n:  # player-specific card props — honest skip
        return None
    exp = mm.cards_exp * _scope_mult(n, mm, home, away)
    ou = _ou(s)
    ln = line if line is not None else _line_from(s)
    # only sane card-COUNT lines; anything huge is a points/other market
    if ou and ln is not None and ("total" in n or "booking" in n or "card" in n) and ln <= 12:
        return _over_under(exp, ln, ou)
    rng = _parse_score(s)
    if rng and rng[1] <= 12:
        lo, hi = rng
        return float(poisson.cdf(hi, exp) - poisson.cdf(lo - 1, exp))
    return None


def _rate_combo(mm, market_name, outcome, home, away):
    """'A & B' — joint probability over the full score matrix."""
    out_parts = [p.strip() for p in outcome.replace(" and ", " & ").split("&")]
    mkt_parts = [p.strip() for p in (market_name or "").replace(" and ", " & ").split("&")]
    if len(out_parts) < 2:
        return None
    preds = []
    for i, op in enumerate(out_parts):
        hint = mkt_parts[i] if i < len(mkt_parts) else (market_name or "")
        pr = _clause_pred(mm, op, home, away, hint)
        if pr is None:
            return None
        preds.append(pr)
    H = np.arange(_N + 1)[:, None]
    A = np.arange(_N + 1)[None, :]
    mask = np.ones_like(mm.M, dtype=bool)
    for pred in preds:
        mask = mask & pred(H, A)
    return float(mm.M[mask].sum())


def _clause_pred(mm, clause, home, away, hint=""):
    """A predicate over (H, A) grids for one combo clause (market segment as hint)."""
    c = clause.strip()
    cl = c.lower()
    hl = (hint or "").lower()
    if _team_match(c, home) or cl == "home":
        return lambda H, A: H > A
    if _team_match(c, away) or cl == "away":
        return lambda H, A: A > H
    if cl in ("draw", "x"):
        return lambda H, A: H == A
    ou = _ou(c)
    ln = _line_from(c)
    if ou and ln is not None:
        return (lambda H, A: (H + A) > ln) if ou == "over" else (lambda H, A: (H + A) < ln)
    # BTTS clause — either explicit in the clause or implied by the market hint
    is_btts = "btts" in cl or "both teams" in cl or "both teams" in hl
    if is_btts:
        if "yes" in cl or cl == "y":
            return lambda H, A: (H >= 1) & (A >= 1)
        if "no" in cl or cl == "n":
            return lambda H, A: (H == 0) | (A == 0)
    return None


def _rate_htft(mm, s, home, away):
    parts = [p.strip() for p in s.split("/")]
    if len(parts) != 2:
        return None
    ht_sel = _result_sel(parts[0], home, away)
    ft_sel = _result_sel(parts[1], home, away)
    if not ht_sel or not ft_sel:
        return None
    n1 = mm.H1.shape[0]
    n2 = mm.H2.shape[0]

    def res(dh, da):
        return "home" if dh > da else ("away" if da > dh else "draw")

    total = 0.0
    for i1 in range(n1):
        for j1 in range(n1):
            p1 = mm.H1[i1, j1]
            if p1 <= 0:
                continue
            for i2 in range(n2):
                for j2 in range(n2):
                    p = p1 * mm.H2[i2, j2]
                    if p <= 0:
                        continue
                    if res(i1, j1) == ht_sel and res(i1 + i2, j1 + j2) == ft_sel:
                        total += p
    return float(total)


def _rate_highest_half(mm, sl):
    d1 = mm._half_total_dist(mm.H1)
    d2 = mm._half_total_dist(mm.H2)
    p_first = p_second = p_tie = 0.0
    for t1, pa in d1.items():
        for t2, pb in d2.items():
            p = pa * pb
            if t1 > t2:
                p_first += p
            elif t2 > t1:
                p_second += p
            else:
                p_tie += p
    if "1st" in sl or "first" in sl:
        return float(p_first)
    if "2nd" in sl or "second" in sl:
        return float(p_second)
    if "equal" in sl or "tie" in sl or "same" in sl:
        return float(p_tie)
    return None


def _rate_margin(mm, s, home, away):
    sel = _result_sel(s, home, away)
    m = _int(s)
    if sel == "draw":
        return _result(mm.MAR == 0, mm.M)
    if sel and m is not None:
        if sel == "home":
            return _result(mm.MAR == m, mm.M)
        if sel == "away":
            return _result(mm.MAR == -m, mm.M)
    return None
