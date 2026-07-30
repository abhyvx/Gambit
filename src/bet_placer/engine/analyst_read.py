"""Per-match analyst read — delegates story discovery to match_signals."""

from __future__ import annotations

from bet_placer.data.football_intel import get_rivalry, get_team_intel
from bet_placer.engine.match_signals import all_angles_from_stories, discover_match_stories


def analyst_read(home: str, away: str, profile: dict, human_context: dict | None = None) -> dict:
    ctx = human_context or {}
    hi = get_team_intel(home)
    ai = get_team_intel(away)
    rivalry = get_rivalry(home, away)

    stories = discover_match_stories(home, away, profile, ctx)
    situational = [a for a in all_angles_from_stories(stories) if a.situational]

    tags: list[str] = []
    for st in stories[:6]:
        if st.signal.startswith("must_win"):
            tags.append(" Must win")
        elif st.signal == "rivalry":
            tags.append(" Grudge")
        elif st.signal.startswith("momentum"):
            tags.append(" Form")
        elif st.signal == "class_gap":
            tags.append(" Class gap")
        elif st.signal.startswith("striker") or st.signal.startswith("star"):
            tags.append(" Scorer")
        elif "card" in st.signal:
            tags.append(" Cards")
        elif st.signal == "knockout_fav" or st.signal == "knockout_tight":
            tags.append(" Knockout")
        elif st.signal == "fade_public":
            tags.append(" Fade hype")

    summary_parts = [
        f"{home} ({hi['style'].replace('_', ' ')}) vs {away} ({ai['style'].replace('_', ' ')}).",
        hi["note"],
        ai["note"],
    ]
    if rivalry:
        summary_parts.append(rivalry["note"])
    if ctx.get("narrative"):
        summary_parts.append(ctx["narrative"])
    if ctx.get("fan_take"):
        summary_parts.append(ctx["fan_take"])
    summary_parts.append(f"Danger: {hi['threat']} / {ai['threat']}.")

    story_summaries = [{"signal": s.signal, "headline": s.headline} for s in stories[:8]]

    return {
        "summary": " ".join(summary_parts).strip(),
        "tags": list(dict.fromkeys(tags))[:6],
        "angles": [
            {
                "market": a.market,
                "selection": a.selection,
                "line": a.line,
                "player": a.player,
                "why": a.why,
                "tag": a.tag,
                "priority": a.priority,
                "signal": a.signal,
                "situational": a.situational,
            }
            for a in situational
        ],
        "situational_angles": [
            {
                "market": a.market,
                "selection": a.selection,
                "line": a.line,
                "player": a.player,
                "why": a.why,
                "tag": a.tag,
                "priority": a.priority,
                "signal": a.signal,
                "situational": True,
            }
            for a in situational
        ],
        "stories": story_summaries,
        "general_angles": [],
        "fade_public": ctx.get("fade_public"),
        "trending_on": ctx.get("trending_on"),
        "fan_take": ctx.get("fan_take"),
        "narrative": ctx.get("narrative"),
        "home_intel": {"team": home, **{k: hi[k] for k in ("style", "tempo", "discipline", "mentality", "threat", "weakness", "note")}},
        "away_intel": {"team": away, **{k: ai[k] for k in ("style", "tempo", "discipline", "mentality", "threat", "weakness", "note")}},
        "disclaimer": "Each pick ties to a story about THIS game — not a generic template.",
    }
