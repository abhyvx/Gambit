"""Discover match-specific betting stories — each signal names teams/players and
maps to diverse Stake market types. No generic template spam."""

from __future__ import annotations

from dataclasses import dataclass, field

from bet_placer.data.football_intel import get_rivalry, get_team_intel
from bet_placer.data.team_ratings import get_team_rating
from bet_placer.data.team_stars import get_attackers


@dataclass
class BettingAngle:
    market: str
    selection: str
    why: str
    tag: str
    signal: str
    priority: int = 5
    line: float | None = None
    player: str | None = None
    situational: bool = True


@dataclass
class MatchStory:
    signal: str
    headline: str
    angles: list[BettingAngle] = field(default_factory=list)


def _is_low(intel: dict) -> bool:
    return intel["tempo"] == "low" or intel["style"] in ("defensive",)


def _is_high(intel: dict) -> bool:
    return intel["tempo"] == "high" or intel["style"] in ("high_press", "counter")


def _hot_morale(ctx: dict, side: str) -> bool:
    m = (ctx.get("morale") or {}).get(side, 5.0)
    return m >= 7.0


def _star_for_threat(team: str, threat: str) -> str | None:
    """Pick the named danger man from intel, not a random squad filler."""
    attackers = get_attackers(team, 4)
    if not attackers:
        return None
    tl = threat.lower()
    for name in attackers:
        parts = name.lower().split()
        if any(len(p) > 3 and p in tl for p in parts):
            return name
    return attackers[0]


def discover_match_stories(
    home: str,
    away: str,
    profile: dict,
    ctx: dict | None = None,
) -> list[MatchStory]:
    """Return ranked stories for THIS fixture — each with 1–2 concrete bet angles."""
    ctx = ctx or {}
    hi = get_team_intel(home)
    ai = get_team_intel(away)
    rivalry = get_rivalry(home, away)
    fav = profile.get("favorite", home)
    dog = away if fav == home else home
    fav_intel = hi if fav == home else ai
    dog_intel = ai if fav == home else hi
    fav_side = "home" if fav == home else "away"
    dog_side = "away" if fav_side == "home" else "home"
    gap = max(profile.get("rating_gap", 0), abs(get_team_rating(home) - get_team_rating(away)))
    style = profile.get("style", "balanced")
    draw_live = profile.get("draw_live", False)
    narrative = (ctx.get("narrative") or "").strip()
    fan_take = (ctx.get("fan_take") or "").strip()
    stories: list[MatchStory] = []

    def story(signal: str, headline: str, angles: list[BettingAngle]) -> None:
        if angles:
            stories.append(MatchStory(signal=signal, headline=headline, angles=angles))

    # ── Must-win desperation (standings-driven) ───────────────────────────────
    if ctx.get("home_must_win"):
        story("must_win", f"{home} must take points or they're in trouble.", [
            BettingAngle("over_under_goals", "over",
                         f"{home} chase the win — gaps open, goals follow.", " Must win",
                         "must_win", 10, line=2.5),
            BettingAngle("btts", "yes",
                         f"{away} get counter chances while {home} push.", " Open game",
                         "must_win", 8),
            BettingAngle("first_goal_team", "home",
                         f"{home} should throw bodies forward first.", " First blood",
                         "must_win", 7),
        ])
    if ctx.get("away_must_win"):
        story("must_win", f"{away} need a result — they'll take risks.", [
            BettingAngle("over_under_goals", "over",
                         f"{away} have to attack; {home} can punish transitions.", " Must win",
                         "must_win", 10, line=2.5),
            BettingAngle("first_goal_team", "away",
                         f"{away} can't sit back — they need the opener.", " First blood",
                         "must_win", 8),
        ])

    # ── Hot streak / confidence (morale + narrative) ────────────────────────
    if _hot_morale(ctx, "home") and ("flying" in narrative.lower() or "confident" in narrative.lower()):
        star = _star_for_threat(home, hi["threat"])
        angles = [
            BettingAngle("match_winner", "home",
                         f"{home} are flying — confidence shows on the pitch.", " Hot streak",
                         "momentum", 8),
        ]
        if star:
            angles.append(BettingAngle("player_goal", star,
                                        f"{star} is {home}'s main outlet in this run.", " In-form scorer",
                                        "momentum", 9, player=star))
        story("momentum_home", f"{home} on a hot streak.", angles)

    if _hot_morale(ctx, "away") and ("confident" in narrative.lower() or "flying" in narrative.lower()):
        star = _star_for_threat(away, ai["threat"])
        angles = [
            BettingAngle("match_winner", "away",
                         f"{away} arrive with swagger — back the form.", " Hot streak",
                         "momentum", 8),
        ]
        if star:
            angles.append(BettingAngle("player_goal", star,
                                        f"{star} leads {away}'s attack right now.", " In-form scorer",
                                        "momentum", 9, player=star))
        story("momentum_away", f"{away} riding confidence.", angles)

    # ── Class gap + tactical script ───────────────────────────────────────────
    if gap >= 22 and style == "dominant_favorite" and not draw_live:
        class_edge = get_team_rating(fav) - get_team_rating(dog)
        angles = []
        if fav_intel["style"] in ("possession", "high_press", "direct") and (
            _is_low(dog_intel) or dog_intel["style"] in ("defensive", "balanced")
        ):
            angles.append(BettingAngle("first_goal_team", fav_side,
                                      f"{fav} boss the ball vs a deep {dog} — they score first.",
                                      " Control script", "control_script", 10))
        if class_edge >= 25:
            angles.append(BettingAngle("asian_handicap", fav_side,
                                      f"{round(gap)}-pt quality gap — {fav} win with cushion.",
                                      " Handicap", "class_gap", 8, line=-1.0 if fav_side == "home" else 1.0))
        if _is_low(dog_intel) or "deep" in dog_intel["note"].lower():
            angles.append(BettingAngle("btts", "no",
                                      f"{dog} park the bus — {fav} can win to nil.", " Clean sheet",
                                      "class_gap", 7))
        story("class_gap", f"{fav} should control {dog}.", angles)

    # ── Striker mismatch (named player vs named weakness) ─────────────────────
    for team, intel, side, opp, opp_intel in (
        (home, hi, "home", away, ai),
        (away, ai, "away", home, hi),
    ):
        weak = opp_intel["weakness"].lower()
        if any(w in weak for w in ("leaky", "lapses", "naive", "exposed", "high line")):
            star = _star_for_threat(team, intel["threat"])
            if star:
                story(f"striker_mismatch_{side}",
                      f"{star} vs a {opp} defence that {opp_intel['weakness']}.",
                      [BettingAngle("player_goal", star,
                                    f"{star} targets {opp}'s weak spot: {opp_intel['weakness']}.",
                                    " Mismatch", "striker_mismatch", 9, player=star)])

    # ── Star-dependent attack (Haaland-type teams) ─────────────────────────────
    if "revolve around" in hi["note"].lower() or "feed him" in hi["note"].lower():
        star = get_attackers(home, 1)[0] if get_attackers(home, 1) else None
        if star:
            story("star_dependent_home", f"{home}'s attack runs through {star}.", [
                BettingAngle("player_goal", star,
                             f"{hi['note']} — {star} anytime is the natural bet.", "⭐ Main man",
                             "star_dependent", 8, player=star),
            ])
    if "revolve around" in ai["note"].lower() or "feed him" in ai["note"].lower():
        star = get_attackers(away, 1)[0] if get_attackers(away, 1) else None
        if star:
            story("star_dependent_away", f"{away}'s attack runs through {star}.", [
                BettingAngle("player_goal", star,
                             f"{ai['note']} — back {star} to score.", "⭐ Main man",
                             "star_dependent", 8, player=star),
            ])

    # ── Rivalry / grudge (specific history — cards + goals) ───────────────────
    if rivalry and rivalry.get("intensity", 0) >= 7:
        story("rivalry", rivalry["note"], [
            BettingAngle("over_under_goals", "over",
                         f"Grudge match ({home} vs {away}) — neither side settles.", " Rivalry",
                         "rivalry", 9, line=2.5),
            BettingAngle("cards", "over",
                         f"{rivalry['note']} — expect a feisty, card-heavy 90.",
                         " Grudge cards", "rivalry", 8, line=3.5),
        ])

    # ── Card magnets (both sides hot OR famous physical teams) ──────────────
    elif hi["discipline"] == "hot" and ai["discipline"] in ("hot", "physical"):
        story("card_battle", f"{home} and {away} both play on the edge.", [
            BettingAngle("cards", "over",
                         f"{hi['note']} + {ai['note']} — referee will be busy.",
                         " Card battle", "discipline", 8, line=3.5),
        ])
    elif hi["discipline"] == "hot":
        story("cards_home", f"{home}'s discipline is a story ({hi['note']}).", [
            BettingAngle("cards", "over",
                         f"{home} pick up bookings — this matchup stays physical.",
                         " Card risk", "discipline", 7, line=3.5),
        ])
    elif ai["discipline"] == "hot":
        story("cards_away", f"{away}'s discipline is a story ({ai['note']}).", [
            BettingAngle("cards", "over",
                         f"{away} run hot — cards market fits this fixture.",
                         " Card risk", "discipline", 7, line=3.5),
        ])

    # ── Possession vs low block → corners (only when intel says so) ─────────
    if hi["style"] == "possession" and _is_low(ai) and "corner" in hi["note"].lower():
        story("corners_home", f"{home} pin {away} back — corners stack up.", [
            BettingAngle("corners", "over",
                         f"{hi['note']} vs a deep {away} block.", " Corner siege",
                         "corner_siege", 7, line=9.5),
        ])
    if ai["style"] == "possession" and _is_low(hi) and "corner" in ai["note"].lower():
        story("corners_away", f"{away} dominate the ball vs a low {home}.", [
            BettingAngle("corners", "over",
                         f"{ai['note']} vs a deep {home} block.", " Corner siege",
                         "corner_siege", 7, line=9.5),
        ])

    # ── Knockout nerves ─────────────────────────────────────────────────────
    if ctx.get("is_knockout"):
        if gap >= 8 and not draw_live:
            story("knockout_fav", f"Knockout — {fav} should advance but extra time looms.", [
                BettingAngle("draw_no_bet", fav_side,
                             f"{fav} have the quality; draw refunds if it's tight at 90.",
                             " Knockout DNB", "knockout", 8),
            ])
        if draw_live:
            story("knockout_tight", f"Knockout coin-flip — nerves favour safety.", [
                BettingAngle("double_chance", "home_draw" if fav == home else "draw_away",
                             f"Extra time is live — cover the draw in {home} vs {away}.",
                             " KO safety", "knockout", 8),
            ])

    # ── Fade the crowd on a hyped favourite ─────────────────────────────────
    if ctx.get("fade_public") and ctx.get("trending_on"):
        hyped = ctx["trending_on"]
        under = away if hyped == home else home
        story("fade_public", f"Public money loves {hyped} — price may be stretched.", [
            BettingAngle("draw_no_bet", dog_side,
                         f"Fade the {hyped} hype; {under} with draw cover is the angle.",
                         " Contrarian", "fade_public", 8),
            BettingAngle("asian_handicap", dog_side,
                         f"{under} +1.5 while the crowd hammers {hyped}.",
                         " Dog cover", "fade_public", 7, line=1.0 if dog_side == "away" else -1.0),
        ])

    # ── Fragile favourite under pressure (England-type) ───────────────────────
    if fav_intel["mentality"] == "fragile" and (ctx.get("is_knockout") or draw_live):
        story("fragile_fav", f"{fav} talent but {fav_intel['note']}", [
            BettingAngle("double_chance", "draw_away" if fav == home else "home_draw",
                         f"{fav} can tighten up — cover the draw vs {dog}.",
                         " Fragile fav", "fragile_fav", 7),
            BettingAngle("over_under_goals", "under",
                         f"{fav_intel['weakness']} — cagey affair likely.", " Low event",
                         "fragile_fav", 6, line=2.5),
        ])

    # ── Open / chaotic (both attack-minded) ─────────────────────────────────
    if _is_high(hi) and _is_high(ai):
        story("open_game", f"{home} and {away} both play on the front foot.", [
            BettingAngle("over_under_goals", "over",
                         f"{hi['style']} vs {ai['style']} — end to end.", " Open",
                         "open_game", 7, line=2.5),
            BettingAngle("btts", "yes",
                         f"Both {hi['threat']} and {ai['threat']} carry threat.",
                         " BTTS", "open_game", 6),
        ])

    # ── Cagey low-tempo ───────────────────────────────────────────────────────
    if _is_low(hi) and _is_low(ai) and style in ("low_scoring", "tight"):
        story("cagey", f"Two cautious sides — {hi['note']}", [
            BettingAngle("over_under_goals", "under",
                         f"{home} vs {away} profiles low-event.", " Under",
                         "cagey", 7, line=2.5),
            BettingAngle("half_time", "draw",
                         f"Slow burn — 0-0 or 1-0 at the break fits.", " HT draw",
                         "cagey", 6),
        ])

    # ── Emotional / streaky team (Brazil-type) ────────────────────────────────
    for team, intel, side in ((home, hi, "home"), (away, ai, "away")):
        if intel["mentality"] == "streaky":
            star = _star_for_threat(team, intel["threat"])
            angles = [
                BettingAngle("btts", "yes",
                             f"{team} are streaky — goals at both ends when it clicks.",
                             " Volatile", "streaky", 6),
            ]
            if star:
                angles.append(BettingAngle("player_goal", star,
                                          f"{team} live or die by {star} — high-variance scorer bet.",
                                          " Star swing", "streaky", 7, player=star))
            story(f"streaky_{side}", f"{team}: {intel['note']}", angles)

    # ── Fan read (unique per match from standings math) ───────────────────────
    if fan_take and len(fan_take) > 25:
        if "draw" in fan_take.lower() and draw_live:
            story("fan_draw", fan_take, [
                BettingAngle("match_winner", "draw",
                             fan_take, " Fan read", "fan_read", 7),
            ])
        elif ctx.get("home_must_win") or ctx.get("away_must_win"):
            story("fan_must_win", fan_take, [
                BettingAngle("btts", "yes", fan_take, " Fan read", "fan_read", 6),
            ])

    # ── Prove-it / redemption (narrative keywords) ────────────────────────────
    for sentence in [s.strip() for s in narrative.split(".") if s.strip()]:
        low = sentence.lower()
        if "didn't go well" in low or "desperate" in low:
            team = home if home in sentence else (away if away in sentence else None)
            if team:
                side = "home" if team == home else "away"
                story(f"redemption_{side}", sentence, [
                    BettingAngle("over_under_goals", "over",
                                 f"{sentence} — they attack, goals follow.", " Prove it",
                                 "redemption", 8, line=2.5),
                ])

    if "more quality" in narrative.lower() or "stronger team" in narrative.lower():
        for sentence in narrative.split("."):
            if "quality" in sentence.lower() or "stronger" in sentence.lower():
                team = home if home in sentence else (away if away in sentence else None)
                if team:
                    side = "home" if team == home else "away"
                    story("quality_edge", sentence.strip(), [
                        BettingAngle("match_winner", side,
                                     f"{sentence.strip()} — back the quality edge.",
                                     " Quality", "quality_edge", 7),
                        BettingAngle("draw_no_bet", side,
                                     f"{team} should edge it; draw refunds if tight.",
                                     " DNB", "quality_edge", 6),
                    ])
                break

    # Sort by top angle priority
    stories.sort(key=lambda s: -(max((a.priority for a in s.angles), default=0)))
    return stories


def all_angles_from_stories(stories: list[MatchStory]) -> list[BettingAngle]:
    """Flatten stories to angles, preserving story order for diversity."""
    out: list[BettingAngle] = []
    seen: set[tuple] = set()
    for st in stories:
        for a in sorted(st.angles, key=lambda x: -x.priority):
            k = (a.market, a.selection, a.line, a.player)
            if k in seen:
                continue
            seen.add(k)
            out.append(a)
    return out
