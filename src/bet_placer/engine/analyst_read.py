"""Turn editorial football intel + the match profile into (a) a human read and
(b) a prioritised list of betting ANGLES for THIS specific matchup.

An "angle" is a direction (e.g. cards over, the favourite -1, Haaland anytime).
bet_builder.py resolves each angle against the real Stake market board so our
recommendations and the user's bet slip are always the same underlying bets.

Everything here is an analyst's OPINION layered on top — the EV/payout math stays
grounded in the real odds elsewhere.
"""

from __future__ import annotations

from bet_placer.data.football_intel import get_rivalry, get_team_intel
from bet_placer.data.team_stars import get_attackers


def _is_low(intel: dict) -> bool:
    return intel["tempo"] == "low" or intel["style"] in ("defensive",)


def _is_high(intel: dict) -> bool:
    return intel["tempo"] == "high" or intel["style"] in ("high_press", "counter")


def _card_prone(intel: dict) -> bool:
    return intel["discipline"] in ("hot", "physical")


def analyst_read(home: str, away: str, profile: dict) -> dict:
    hi = get_team_intel(home)
    ai = get_team_intel(away)
    rivalry = get_rivalry(home, away)
    style = profile.get("style", "balanced")
    fav = profile.get("favorite", home)
    dog = away if fav == home else home
    gap = profile.get("rating_gap", 0)

    tags: list[str] = []
    angles: list[dict] = []

    def add(market, selection, why, tag, line=None, player=None, priority=5):
        angles.append({
            "market": market, "selection": selection, "line": line,
            "player": player, "why": why, "tag": tag, "priority": priority,
        })

    # ---- Cards: derbies & physical sides ----
    derby = rivalry is not None
    physical = _card_prone(hi) and _card_prone(ai)
    if derby or physical:
        tag = "🔥 Grudge match" if derby else "🥊 Physical battle"
        if tag not in tags:
            tags.append(tag)
        why = (rivalry["note"] if derby else
               f"Both {home} and {away} play with a hard edge — referee likely busy.")
        add("cards", "over", why, "🟨 Cards", priority=8 if derby else 6)

    # ---- Low-event games: two cautious/low-tempo sides ----
    if _is_low(hi) and _is_low(ai) or style == "low_scoring":
        tags.append("🧊 Low-tempo")
        add("over_under_goals", "under", "Two cautious, low-tempo sides — goals at a premium.", "⚽ Goals", line=2.5, priority=7)
        add("btts", "no", "At least one of these defences should keep it tight.", "🥅 BTTS", priority=6)

    # ---- Open games: two attacking/high-tempo sides ----
    if (_is_high(hi) and _is_high(ai)) or style == "high_scoring":
        tags.append("⚡ Open game")
        add("over_under_goals", "over", "Both teams attack with pace — end-to-end expected.", "⚽ Goals", line=2.5, priority=7)
        add("btts", "yes", "Both should carry a scoring threat.", "🥅 BTTS", priority=6)

    # ---- Corner pressure: possession side vs a low block ----
    if hi["style"] == "possession" and _is_low(ai):
        tags.append("🚩 Corner pressure")
        add("corners", "over", f"{home} will dominate the ball vs a deep {away} block — corners pile up.", "🚩 Corners", priority=6)
    elif ai["style"] == "possession" and _is_low(hi):
        tags.append("🚩 Corner pressure")
        add("corners", "over", f"{away} will dominate the ball vs a deep {home} block — corners pile up.", "🚩 Corners", priority=6)

    # ---- Class gap: ruthless favourite ----
    if gap >= 15 and style == "dominant_favorite":
        fav_intel = hi if fav == home else ai
        if fav_intel["mentality"] == "ruthless":
            tags.append("💪 Class gap")
            add("asian_handicap", "home" if fav == home else "away",
                f"{fav} are a class above and tend to kill games off — back them to win comfortably.",
                "💪 Handicap", line=-1.0 if fav == home else 1.0, priority=7)
        else:
            add("draw_no_bet", "home" if fav == home else "away",
                f"{fav} should have too much, but take the draw-refund safety net.", "🛡️ DNB", priority=6)

    # ---- Danger man: a feared striker vs a shaky defence ----
    fav_intel = hi if fav == home else ai
    dog_intel = ai if fav == home else hi
    if "leaky" in dog_intel["weakness"] or "lapses" in dog_intel["weakness"] or gap >= 12:
        star = get_attackers(fav, 1)
        if star:
            tags.append("🎯 Danger man")
            add("player_goal", star[0],
                f"{star[0]} vs a vulnerable {dog} back line — prime anytime-scorer spot.",
                "🎯 Scorer", player=star[0], priority=6)

    # ---- Tight game: protect with double chance ----
    if style in ("tight", "balanced") and gap < 10:
        tags.append("⚖️ Even contest")
        better = fav
        add("double_chance", "home_draw" if better == home else "draw_away",
            f"Coin-flip game — {better} or the draw is the safer way in than picking a winner.",
            "🛡️ Safety", priority=5)

    # ---- Build the prose read ----
    bits = []
    bits.append(f"{home}: {hi['note']} {ai['note'] if False else ''}".strip())
    summary = (
        f"{home} ({hi['style'].replace('_', ' ')}, {hi['mentality'].replace('_', ' ')}) vs "
        f"{away} ({ai['style'].replace('_', ' ')}, {ai['mentality'].replace('_', ' ')}). "
        f"{hi['note']} {ai['note']} "
    )
    if rivalry:
        summary += rivalry["note"] + " "
    summary += f"Danger: {hi['threat']} for {home}; {ai['threat']} for {away}."

    # Sort angles by priority (desc), dedupe by (market, selection, player).
    seen = set()
    uniq = []
    for a in sorted(angles, key=lambda x: -x["priority"]):
        k = (a["market"], a["selection"], a["player"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)

    return {
        "summary": summary.strip(),
        "tags": tags[:4],
        "angles": uniq,
        "home_intel": {"team": home, **{k: hi[k] for k in ("style", "tempo", "discipline", "mentality", "threat", "weakness")}},
        "away_intel": {"team": away, **{k: ai[k] for k in ("style", "tempo", "discipline", "mentality", "threat", "weakness")}},
        "disclaimer": "Analyst read — our football opinion, not live data. The payouts and value math use real odds.",
    }
