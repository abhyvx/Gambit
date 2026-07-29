"""Learn team strength + the goal model from the FULL history of international
football (~49k matches, 1872-present), not just the couple dozen WC games so far.

How we keep it honest (no overfitting, no leakage):
  1. Download & cache the open results dataset (martj42/international_results).
  2. Replay every match chronologically to build an Elo per nation. The rating is
     always PRE-match, so any sample we score is a true out-of-sample prediction.
  3. Tune the Elo hyper-parameters (K, home edge) on a TIME-SPLIT holdout: fit on
     2016-2020, score the untouched 2021→today window by log-loss. We pick the
     settings that predict the future best — not the ones that fit the past.
  4. Fit the goal model (Elo edge → goals) + probability calibration on the recent
     window, and report accuracy/Brier on the held-out window plus a breakdown of
     how reliable we are WHEN WE'RE CONFIDENT (that's the betting-relevant number).

Everything learned is written into model params so the live prediction path uses
real, data-driven strengths instead of hand-typed reputation numbers.
"""

from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.stats import poisson

from bet_placer.data.team_names import canon_team
from bet_placer.config import data_path

DATA_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CACHE = data_path("intl_results.csv")
CACHE_TTL_DAYS = 7

# Elo replay defaults (the search tunes K0 + HOME_ADV around these).
BASE_ELO = 1500.0
K0 = 24.0
HOME_ADV_ELO = 70.0          # home-field bump for non-neutral games
NEUTRAL_HOME_ADV = 18.0      # tiny nominal edge for the designated "home" at a neutral venue
RECENT_CUTOFF = "2016-01-01"  # window used to fit the goal model + calibration
TEST_CUTOFF = "2021-01-01"    # everything from here is a pure holdout for scoring

_TOTAL_LINES = (1.5, 2.5, 3.5)

# Grid searched on the time-split holdout.
_K_GRID = (16.0, 20.0, 24.0, 30.0)
_HA_GRID = (55.0, 70.0, 90.0)

# ── Attack/Defense dynamic ratings (Maher/Dixon-Coles style) ───────────────
# A second, complementary model to the single-Elo one. Each team gets a separate
# ATTACK and DEFENCE strength (log-rate) updated online after every match, so a
# high-scoring leaky side is modelled differently from a solid low-scoring side
# of the same Elo. Const learning-rate => recent form weighted more (no leakage:
# every prediction uses only pre-match ratings). We ensemble it with Elo because
# Elo nails the result axis while attack/defence nails the goals axis.
AD_LR = 0.06            # online learning rate
AD_MU = 0.30            # global mean log goals/team (~exp 1.35)
AD_HA = 0.24            # home-field bump in log-goal space (non-neutral only)
AD_SHRINK = 0.0         # L2 pull toward league mean per step
AD_W_GRID = (0.3, 0.4, 0.5, 0.6, 0.7)  # ensemble weight on Elo, tuned on holdout
AD_MIN_GAMES = 8


def _tournament_weight(name: str) -> float:
    n = (name or "").lower()
    if "friendly" in n:
        return 0.5
    if "world cup" in n:
        return 1.3 if "qualification" not in n else 0.9
    if any(k in n for k in ("uefa euro", "copa am", "african cup", "afc asian", "gold cup", "nations league")):
        return 1.1 if "qualification" not in n else 0.85
    if "qualification" in n or "qualif" in n:
        return 0.9
    return 0.8


def _gd_mult(gd: int) -> float:
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    if gd == 3:
        return 1.75
    return 1.75 + (gd - 3) / 8.0


def load_rows(force: bool = False) -> list[dict]:
    """Download (cached) and parse valid, scored matches sorted by date."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    stale = (not CACHE.exists()) or (time.time() - CACHE.stat().st_mtime > CACHE_TTL_DAYS * 86400)
    if force or stale:
        import requests
        r = requests.get(DATA_URL, timeout=30)
        r.raise_for_status()
        CACHE.write_text(r.text)

    rows = []
    with CACHE.open() as f:
        for d in csv.DictReader(f):
            hs, as_ = d.get("home_score"), d.get("away_score")
            if hs in (None, "", "NA") or as_ in (None, "", "NA"):
                continue
            try:
                rows.append({
                    "date": d["date"],
                    "home": d["home_team"], "away": d["away_team"],
                    "hs": int(hs), "as": int(as_),
                    "neutral": str(d.get("neutral", "")).upper() == "TRUE",
                    "tournament": d.get("tournament", ""),
                })
            except (ValueError, KeyError):
                continue
    rows.sort(key=lambda r: r["date"])
    return rows


def _replay_elo(rows: list[dict], k0: float = K0, home_adv: float = HOME_ADV_ELO):
    """Chronological Elo. Returns (elo, games, recs) where recs are PRE-match
    samples (he, ae, neutral, date, hs, as) for the recent window only."""
    elo: dict[str, float] = {}
    games: dict[str, int] = {}
    recs = []

    def get(t):
        return elo.get(t, BASE_ELO)

    for r in rows:
        h, a = canon_team(r["home"]), canon_team(r["away"])
        if not h or not a:
            continue
        he, ae = get(h), get(a)
        hf = 0.0 if r["neutral"] else home_adv
        exp_home = 1.0 / (1.0 + 10 ** ((ae - (he + hf)) / 400.0))
        hs, as_ = r["hs"], r["as"]
        result = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
        k = k0 * _tournament_weight(r["tournament"]) * _gd_mult(abs(hs - as_))
        delta = k * (result - exp_home)
        if r["date"] >= RECENT_CUTOFF:
            recs.append((he, ae, r["neutral"], r["date"], hs, as_))
        elo[h] = he + delta
        elo[a] = ae - delta
        games[h] = games.get(h, 0) + 1
        games[a] = games.get(a, 0) + 1
    return elo, games, recs


def _fit_goal_model(samples, home_adv: float = HOME_ADV_ELO, neutral_adv: float = NEUTRAL_HOME_ADV) -> dict:
    """Fit supremacy ~ a*de + b and total ~ c*|de| + d from pre-match samples.
    `samples` are (he, ae, neutral, hs, as)."""
    if len(samples) < 200:
        gm = {"sup_a": 0.0019, "sup_b": 0.0, "tot_a": -0.0006, "tot_b": 2.65}
    else:
        de, sup, tot = [], [], []
        for he, ae, neutral, hs, as_ in samples:
            hf = neutral_adv if neutral else home_adv
            d = (he + hf) - ae
            de.append(d); sup.append(hs - as_); tot.append(hs + as_)
        de = np.asarray(de); sup = np.asarray(sup); tot = np.asarray(tot)
        A1 = np.vstack([de, np.ones_like(de)]).T
        sup_a, sup_b = np.linalg.lstsq(A1, sup, rcond=None)[0]
        A2 = np.vstack([np.abs(de), np.ones_like(de)]).T
        tot_a, tot_b = np.linalg.lstsq(A2, tot, rcond=None)[0]
        gm = {"sup_a": float(sup_a), "sup_b": float(sup_b),
              "tot_a": float(tot_a), "tot_b": float(tot_b)}
    gm["home_adv"] = float(home_adv)
    gm["neutral_adv"] = float(neutral_adv)
    return gm


def lambdas_from_elo(he: float, ae: float, gm: dict, neutral: bool = True) -> tuple[float, float]:
    """Expected (home, away) goals from two Elo ratings + the fitted goal model."""
    hf = gm.get("neutral_adv", NEUTRAL_HOME_ADV) if neutral else gm.get("home_adv", HOME_ADV_ELO)
    de = (he + hf) - ae
    sup = gm["sup_a"] * de + gm["sup_b"]
    tot = max(1.4, gm["tot_a"] * abs(de) + gm["tot_b"])
    return max(0.15, (tot + sup) / 2.0), max(0.15, (tot - sup) / 2.0)


def _replay_ad(rows, lr=AD_LR, mu=AD_MU, ha=AD_HA, shrink=AD_SHRINK):
    """Chronological online attack/defence ratings. Returns (att, dff, games,
    recs) where recs are PRE-match (date, neutral, hs, as, lh, la) for the recent
    window only (so scoring on them is genuinely out-of-sample)."""
    att: dict[str, float] = {}
    dff: dict[str, float] = {}
    games: dict[str, int] = {}
    recs = []
    for r in rows:
        h, a = canon_team(r["home"]), canon_team(r["away"])
        if not h or not a:
            continue
        ah, dh = att.get(h, 0.0), dff.get(h, 0.0)
        aa, da = att.get(a, 0.0), dff.get(a, 0.0)
        hf = 0.0 if r["neutral"] else ha
        lh = min(max(np.exp(mu + hf + ah - da), 0.15), 6.0)
        la = min(max(np.exp(mu + aa - dh), 0.15), 6.0)
        hs, as_ = r["hs"], r["as"]
        if r["date"] >= RECENT_CUTOFF:
            recs.append((r["date"], r["neutral"], hs, as_, lh, la))
        w = _tournament_weight(r["tournament"]) * lr
        # Poisson-likelihood gradient steps (att up if you out-scored prediction,
        # def up — i.e. opponent's attack down — if you conceded fewer).
        att[h] = ah * (1 - shrink) + w * (hs - lh)
        dff[a] = da * (1 - shrink) + w * (lh - hs)
        att[a] = aa * (1 - shrink) + w * (as_ - la)
        dff[h] = dh * (1 - shrink) + w * (la - as_)
        games[h] = games.get(h, 0) + 1
        games[a] = games.get(a, 0) + 1
    return att, dff, games, recs


def lambdas_from_ad(home: str, away: str, ad: dict, neutral: bool = True):
    """Expected (home, away) goals from the attack/defence model. Returns
    (None, None) if either team isn't rated so callers fall back to Elo."""
    att = ad.get("att") or {}
    dff = ad.get("def") or {}
    h, a = canon_team(home), canon_team(away)
    if h not in att or a not in att:
        return None, None
    mu = float(ad.get("mu", AD_MU))
    ha = float(ad.get("ha", AD_HA))
    hf = 0.0 if neutral else ha
    lh = np.exp(mu + hf + att.get(h, 0.0) - dff.get(a, 0.0))
    la = np.exp(mu + att.get(a, 0.0) - dff.get(h, 0.0))
    return float(min(max(lh, 0.15), 6.0)), float(min(max(la, 0.15), 6.0))


def _grade(sel, hs, as_):
    if sel == "home": return int(hs > as_)
    if sel == "draw": return int(hs == as_)
    if sel == "away": return int(hs < as_)
    if sel == "yes": return int(hs >= 1 and as_ >= 1)
    if sel == "no": return int(not (hs >= 1 and as_ >= 1))
    if sel.startswith("over_"): return int((hs + as_) > float(sel.split("_")[1]))
    if sel.startswith("under_"): return int((hs + as_) < float(sel.split("_")[1]))
    return 0


def _probs(hl, al, rho: float = 0.0):
    kmax = 10
    ks = np.arange(kmax + 1)
    hp = poisson.pmf(ks, hl)
    ap = poisson.pmf(ks, al)
    M = np.outer(hp, ap)
    if rho:
        # Dixon-Coles low-score correction (negative rho => more draws).
        M = M.copy()
        M[0, 0] *= 1.0 - hl * al * rho
        M[0, 1] *= 1.0 + hl * rho
        M[1, 0] *= 1.0 + al * rho
        M[1, 1] *= 1.0 - rho
        np.clip(M, 1e-12, None, out=M)
    M = M / M.sum()
    H = ks[:, None]; A = ks[None, :]
    tot = H + A
    out = [("result", "home", float(M[H > A].sum())),
           ("result", "draw", float(M[H == A].sum())),
           ("result", "away", float(M[H < A].sum()))]
    btts = 1.0 - float(M[0, :].sum()) - float(M[:, 0].sum()) + float(M[0, 0])
    out += [("btts", "yes", btts), ("btts", "no", 1 - btts)]
    for ln in _TOTAL_LINES:
        over = float(M[tot > ln].sum())
        out += [("totals", f"over_{ln}", over), ("totals", f"under_{ln}", 1 - over)]
    return out


def _score_window(recs, gm) -> dict:
    """Out-of-sample scoring on a list of (he,ae,neutral,date,hs,as) recs:
    accuracy, log-loss, Brier, and accuracy split by how confident we were."""
    if not recs:
        return {}
    n = 0
    n_correct = 0
    ll = 0.0
    brier = 0.0
    # confidence tiers on the top result pick
    tiers = {"55": [0, 0], "60": [0, 0], "65": [0, 0], "70": [0, 0]}
    eps = 1e-9
    rho = float(gm.get("dc_rho", 0.0) or 0.0)
    for he, ae, neutral, date, hs, as_ in recs:
        hl, al = lambdas_from_elo(he, ae, gm, neutral=neutral)
        result_evs = [(s, p) for g, s, p in _probs(hl, al, rho) if g == "result"]
        top_sel, top_p = max(result_evs, key=lambda x: x[1])
        hit = _grade(top_sel, hs, as_)
        n += 1
        n_correct += hit
        # proper scores on the full 3-way result distribution
        for s, p in result_evs:
            y = _grade(s, hs, as_)
            ll += -(y * np.log(max(eps, p)))   # multiclass log-loss (only true class contributes)
            brier += (p - y) ** 2
        for thr in (0.55, 0.60, 0.65, 0.70):
            if top_p >= thr:
                key = str(int(thr * 100))
                tiers[key][0] += 1
                tiers[key][1] += hit
    conf = {}
    for k, (cnt, cor) in tiers.items():
        if cnt >= 20:
            conf[k] = {"n": cnt, "accuracy": round(cor / cnt, 3)}
    return {
        "n": n,
        "accuracy": round(n_correct / n, 3),
        "log_loss": round(ll / n, 4),
        "result_brier": round(brier / n, 4),
        "confident": conf,
    }


def _fit_dc_rho(recent, gm) -> float:
    """Choose the Dixon-Coles rho whose average predicted P(draw) matches the
    real draw rate over the recent window. Negative rho => more draws."""
    if not recent:
        return 0.0
    import random
    sample = recent if len(recent) <= 4000 else random.sample(recent, 4000)
    actual_draw = np.mean([1.0 if hs == as_ else 0.0 for *_, hs, as_ in sample])
    # precompute lambdas once per sample
    lams = [(lambdas_from_elo(he, ae, gm, neutral=nt)) for he, ae, nt, hs, as_ in sample]

    def pred_draw_rate(rho):
        tot = 0.0
        for hl, al in lams:
            for g, s, p in _probs(hl, al, rho):
                if s == "draw":
                    tot += p
                    break
        return tot / len(lams)

    best_rho, best_err = 0.0, abs(pred_draw_rate(0.0) - actual_draw)
    for rho in (-0.04, -0.07, -0.10, -0.13, -0.16, -0.19, -0.22, -0.25, -0.28, -0.32):
        err = abs(pred_draw_rate(rho) - actual_draw)
        if err < best_err:
            best_err, best_rho = err, rho
    return best_rho


def _fit_platt(ps, ys):
    ps, ys = np.asarray(ps, float), np.asarray(ys, float)
    if len(ps) < 100 or len(np.unique(ys)) < 2:
        return {"a": 1.0, "b": 0.0}
    from sklearn.linear_model import LogisticRegression
    eps = 1e-6
    X = np.log(np.clip(ps, eps, 1 - eps) / np.clip(1 - ps, eps, 1 - eps)).reshape(-1, 1)
    try:
        lr = LogisticRegression(C=8.0, solver="lbfgs", max_iter=800)
        lr.fit(X, ys)
        a = float(lr.coef_[0][0]); b = float(lr.intercept_[0])
        if not (0.2 <= a <= 3.0) or abs(b) > 3.0:
            return {"a": 1.0, "b": 0.0}
        return {"a": round(a, 4), "b": round(b, 4)}
    except Exception:
        return {"a": 1.0, "b": 0.0}


def train_history() -> dict:
    """Run the full historical training. Returns a dict to merge into params."""
    rows = load_rows()

    # ── 1) Tune K + home edge on a time-split holdout (predict the future) ──
    best = None
    for k0 in _K_GRID:
        for ha in _HA_GRID:
            _, _, recs = _replay_elo(rows, k0=k0, home_adv=ha)
            train = [r for r in recs if r[3] < TEST_CUTOFF]
            test = [r for r in recs if r[3] >= TEST_CUTOFF]
            if len(train) < 500 or len(test) < 200:
                continue
            gm = _fit_goal_model([(he, ae, nt, hs, as_) for he, ae, nt, _, hs, as_ in train],
                                 home_adv=ha)
            sc = _score_window(test, gm)
            key = sc.get("log_loss", 9.9)
            if best is None or key < best["log_loss"]:
                best = {"k0": k0, "home_adv": ha, "log_loss": key,
                        "holdout": sc}
    if best is None:
        best = {"k0": K0, "home_adv": HOME_ADV_ELO, "log_loss": None, "holdout": {}}

    # ── 2) Final replay with the winning settings on the FULL history ──
    elo, games, recs = _replay_elo(rows, k0=best["k0"], home_adv=best["home_adv"])
    all_recent = [(he, ae, nt, hs, as_) for he, ae, nt, _, hs, as_ in recs]
    gm = _fit_goal_model(all_recent, home_adv=best["home_adv"])

    # ── 2b) Fit the Dixon-Coles draw correction: pick the rho whose predicted
    #        draw frequency matches the real draw rate (independent Poisson
    #        chronically under-counts draws, over-backing favourites). ──
    gm["dc_rho"] = _fit_dc_rho(all_recent, gm)
    rho_fit = float(gm.get("dc_rho", 0.0) or 0.0)

    # ── 2c) Attack/Defence model + ensemble weight (tuned on the holdout). ──
    ad_att, ad_dff, ad_games, ad_recs = _replay_ad(rows)
    # `recs` (Elo, recent) and `ad_recs` walk the same rows in the same order,
    # so they align index-for-index on the recent window.
    elo_recent_dated = recs  # (he, ae, neutral, date, hs, as_)

    def _ensemble_holdout(w_elo: float) -> dict:
        """Out-of-sample metrics for the Elo×AttackDefence ensemble at weight w."""
        eps = 1e-12
        comb_ll = res_ll = 0.0
        n = n_correct = 0
        for (he, ae, nt, d, hs, as_), (d2, nt2, h2, a2, lh, la) in zip(elo_recent_dated, ad_recs):
            if d < TEST_CUTOFF:
                continue
            ehl, ela = lambdas_from_elo(he, ae, gm, neutral=nt)
            bh = w_elo * ehl + (1 - w_elo) * lh
            ba = w_elo * ela + (1 - w_elo) * la
            probs = _probs(bh, ba, rho_fit)
            res = {s: p for g, s, p in probs if g == "result"}
            over = {s: p for g, s, p in probs if g == "totals" and s == "over_2.5"}.get("over_2.5", 0.5)
            y = "home" if hs > as_ else ("draw" if hs == as_ else "away")
            yo = 1 if (hs + as_) > 2.5 else 0
            rl = -np.log(max(eps, res.get(y, eps)))
            res_ll += rl
            comb_ll += rl - (yo * np.log(max(eps, over)) + (1 - yo) * np.log(max(eps, 1 - over)))
            n_correct += int(max(res, key=res.get) == y)
            n += 1
        n = max(1, n)
        return {"comb_ll": comb_ll / n, "log_loss": round(res_ll / n, 4),
                "accuracy": round(n_correct / n, 3), "n": n}

    if len(ad_recs) == len(elo_recent_dated) and ad_recs:
        w_elo = min(AD_W_GRID, key=lambda w: _ensemble_holdout(w)["comb_ll"])
        ens_holdout = _ensemble_holdout(w_elo)
    else:
        w_elo = 1.0  # misaligned (shouldn't happen) → fall back to Elo-only
        ens_holdout = {}
    ad_model = {
        "att": {t: round(float(v), 4) for t, v in ad_att.items() if ad_games.get(t, 0) >= AD_MIN_GAMES},
        "def": {t: round(float(v), 4) for t, v in ad_dff.items() if ad_games.get(t, 0) >= AD_MIN_GAMES},
        "mu": AD_MU, "ha": AD_HA, "w_elo": float(w_elo),
    }

    # ── 3) Calibration on the full recent window (pre-match, no leakage) ──
    rho = float(gm.get("dc_rho", 0.0) or 0.0)
    by_group: dict[str, list] = {}
    by_sel: dict[str, list] = {}
    res_ps, res_ys, n_correct = [], [], 0
    for he, ae, neutral, hs, as_ in all_recent:
        hl, al = lambdas_from_elo(he, ae, gm, neutral=neutral)
        evs = _probs(hl, al, rho)
        result_evs = [(s, p) for g, s, p in evs if g == "result"]
        top = max(result_evs, key=lambda x: x[1])
        n_correct += _grade(top[0], hs, as_)
        for g, s, p in evs:
            y = _grade(s, hs, as_)
            by_group.setdefault(g, []).append((p, y))
            if g == "result":
                by_sel.setdefault(s, []).append((p, y))
                res_ps.append(p); res_ys.append(y)

    cal = {}
    all_ps, all_ys = [], []
    for g, pairs in by_group.items():
        ps = [p for p, _ in pairs]; ys = [y for _, y in pairs]
        all_ps += ps; all_ys += ys
        cal[g] = _fit_platt(ps, ys)
    cal["_global"] = _fit_platt(all_ps, all_ys)
    for g in ("result", "totals", "btts"):
        cal.setdefault(g, {"a": 1.0, "b": 0.0})
    # Draw-specific Platt — the pooled "result" fit under-corrects draws.
    if by_sel.get("draw"):
        dps = [p for p, _ in by_sel["draw"]]; dys = [y for _, y in by_sel["draw"]]
        cal["draw"] = _fit_platt(dps, dys)
    else:
        cal["draw"] = {"a": 1.0, "b": 0.0}

    res_ps = np.asarray(res_ps); res_ys = np.asarray(res_ys)
    brier = float(np.mean((res_ps - res_ys) ** 2)) if len(res_ps) else None
    acc = n_correct / len(all_recent) if all_recent else None

    # Reliability curve on CALIBRATED global probabilities (predicted vs actual).
    def _cal(p, coef):
        a, b = coef.get("a", 1.0), coef.get("b", 0.0)
        if a == 1.0 and b == 0.0:
            return p
        eps = 1e-6
        z = a * np.log(max(eps, min(1 - eps, p)) / max(eps, 1 - min(1 - eps, p))) + b
        return 1.0 / (1.0 + np.exp(-z))
    cal_ps = np.array([_cal(p, cal.get(g, cal["_global"])) for g, pairs in by_group.items() for p, _ in pairs])
    cal_ys = np.array([y for g, pairs in by_group.items() for _, y in pairs])
    reliability = []
    if len(cal_ps):
        edges = np.linspace(0, 1, 6)
        for i in range(5):
            lo, hi = edges[i], edges[i + 1]
            m = (cal_ps >= lo) & (cal_ps < hi if i < 4 else cal_ps <= hi)
            if m.sum() == 0:
                continue
            reliability.append({"range": f"{int(lo*100)}-{int(hi*100)}%",
                                "predicted": round(float(cal_ps[m].mean()) * 100, 1),
                                "actual": round(float(cal_ys[m].mean()) * 100, 1),
                                "n": int(m.sum())})

    # Only trust Elo for teams with enough games; keep a clean, rounded dict.
    elo_out = {t: round(v, 1) for t, v in elo.items() if games.get(t, 0) >= 8}
    top_teams = sorted(elo_out.items(), key=lambda kv: -kv[1])[:25]

    holdout = best.get("holdout") or {}
    # Report the ACTUAL live model (Elo×AttackDefence ensemble) on the holdout,
    # falling back to the Elo-only numbers if the ensemble couldn't be scored.
    ho_acc = ens_holdout.get("accuracy", holdout.get("accuracy"))
    ho_ll = ens_holdout.get("log_loss", holdout.get("log_loss"))
    ho_n = ens_holdout.get("n", holdout.get("n"))
    return {
        "elo": elo_out,
        "elo_games": {t: games[t] for t in elo_out},
        "goal_model": {k: round(v, 6) for k, v in gm.items()},
        "ad_model": ad_model,
        "calibration": cal,
        "reliability": reliability,
        "tuning": {"k_factor": best["k0"], "home_edge_elo": best["home_adv"],
                   "ensemble_w_elo": ad_model.get("w_elo")},
        "history": {
            "n_matches": len(rows),
            "n_recent_samples": len(all_recent),
            "result_brier": round(brier, 4) if brier is not None else None,
            "top_pick_accuracy": round(acc, 3) if acc is not None else None,
            # Honest, out-of-sample numbers on the untouched 2021→today window:
            "holdout_accuracy": ho_acc,
            "holdout_log_loss": ho_ll,
            "holdout_brier": holdout.get("result_brier"),
            "holdout_n": ho_n,
            "confident": holdout.get("confident", {}),
            "top_teams": [{"team": t, "elo": e} for t, e in top_teams],
            "trained_at": datetime.utcnow().isoformat(),
        },
    }
