"""World Cup 2026 tournament stage / matchday model.

Matchdays 1–3 = group stage (six games per group, two per matchday).
Matchdays 4–9 = knockout rounds (one id per round).

ESPN publishes group games through ~27 Jun 2026, then knockout fixtures
with real team names. Placeholder bracket slots (e.g. "Round of 32 8 Winner")
appear later in the feed — both are ingested when present.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# Group stage matchdays
STAGE_GROUP_MD1 = 1
STAGE_GROUP_MD2 = 2
STAGE_GROUP_MD3 = 3

# Knockout matchdays (also used as API filter ids)
STAGE_R32 = 4
STAGE_R16 = 5
STAGE_QF = 6
STAGE_SF = 7
STAGE_FINAL = 8
STAGE_THIRD = 9

STAGE_MIN = 1
STAGE_MAX = STAGE_THIRD
FILTER_ALL = 0  # show every stage

GROUP_STAGE_END = date(2026, 6, 27)

STAGE_LABELS: dict[int, str] = {
    STAGE_GROUP_MD1: "Group MD1",
    STAGE_GROUP_MD2: "Group MD2",
    STAGE_GROUP_MD3: "Group MD3",
    STAGE_R32: "Round of 32",
    STAGE_R16: "Round of 16",
    STAGE_QF: "Quarter-finals",
    STAGE_SF: "Semi-finals",
    STAGE_FINAL: "Final",
    STAGE_THIRD: "3rd-place play-off",
}

STAGE_SHORT: dict[int, str] = {
    STAGE_R32: "R32",
    STAGE_R16: "R16",
    STAGE_QF: "QF",
    STAGE_SF: "SF",
    STAGE_FINAL: "F",
    STAGE_THIRD: "3P",
}

KNOCKOUT_SHORT_CODES = frozenset(STAGE_SHORT.values())

# ESPN `season.type` on scoreboard events — authoritative for group vs knockout.
# (Name/date heuristics mis-label late group MD3 games as R32.)
ESPN_TYPE_GROUP = 13802
ESPN_TYPE_R32 = 13801
ESPN_TYPE_R16 = 13800
ESPN_TYPE_R16_PLACEHOLDER = 13799
ESPN_TYPE_QF_PLACEHOLDER = 13798

ESPN_KNOCKOUT_TYPE_TO_STAGE: dict[int, tuple[int, str]] = {
    ESPN_TYPE_R32: (STAGE_R32, "R32"),
    ESPN_TYPE_R16: (STAGE_R16, "R16"),
    ESPN_TYPE_R16_PLACEHOLDER: (STAGE_R16, "R16"),
    ESPN_TYPE_QF_PLACEHOLDER: (STAGE_QF, "QF"),
}


def stage_from_espn_type(season_type: int | None) -> tuple[int, str, bool] | None:
    """Map ESPN season.type → (matchday, short_code, is_knockout). None if unknown."""
    if season_type == ESPN_TYPE_GROUP:
        return 0, "", False
    mapped = ESPN_KNOCKOUT_TYPE_TO_STAGE.get(int(season_type)) if season_type is not None else None
    if mapped:
        md, code = mapped
        return md, code, True
    return None

# ESPN bracket slots before teams are known (e.g. "Round of 32 8 Winner").
_PLACEHOLDER_TEAM_RE = re.compile(
    r"(round of (?:32|16)\s+\d+\s+winner|"
    r"quarterfinal\s+\d+\s+winner|"
    r"semifinal\s+\d+\s+winner|"
    r"semi-final\s+\d+\s+winner|"
    r"final\s+\d+\s+winner|"
    r"\btbd\b)",
    re.IGNORECASE,
)


def is_bracket_placeholder(home: str, away: str) -> bool:
    """True when either side is an ESPN bracket slot, not a real national team."""
    for name in (home or "", away or ""):
        low = name.strip().lower()
        if not low:
            return True
        if _PLACEHOLDER_TEAM_RE.search(low):
            return True
        if "winner" in low and any(
            k in low for k in ("round of 32", "round of 16", "quarterfinal", "semifinal", "semi-final")
        ):
            return True
    return False


def is_displayable_fixture(match) -> bool:
    """Group games always show; knockout only when both teams are confirmed."""
    if not getattr(match, "is_knockout", False):
        return True
    home = getattr(match, "home", None) or getattr(match, "home_team", "")
    away = getattr(match, "away", None) or getattr(match, "away_team", "")
    return not is_bracket_placeholder(home, away)

STAGE_TABS: list[tuple[int | None, str, str | None]] = [
    (None, "Today", "Live"),
    (STAGE_GROUP_MD1, "MD 1", None),
    (STAGE_GROUP_MD2, "MD 2", None),
    (STAGE_GROUP_MD3, "MD 3", None),
    (STAGE_R32, "R32", None),
    (STAGE_R16, "R16", None),
    (STAGE_QF, "QF", None),
    (STAGE_SF, "SF", None),
    (STAGE_FINAL, "Final", None),
    (STAGE_THIRD, "3rd", None),
    (FILTER_ALL, "All games", None),
]


def build_stage_tabs(all_matches, active_matchday: int | None = None) -> list[dict]:
    """UI tabs.

    Group tabs disappear once the knockout phase is underway.
    Knockout tabs appear as soon as ESPN posts the round, even if the feed still
    uses placeholder winner slots and there are no confirmed team names yet.
    """
    counts: dict[int, int] = {}
    visible_counts: dict[int, int] = {}
    for m in all_matches:
        md = getattr(m, "matchday", None)
        if md is None:
            continue
        counts[md] = counts.get(md, 0) + 1
        if is_displayable_fixture(m):
            visible_counts[md] = visible_counts.get(md, 0) + 1

    knockout_live = any(counts.get(md, 0) > 0 for md in range(STAGE_R32, STAGE_THIRD + 1))
    hide_group_tabs = bool(active_matchday and active_matchday >= STAGE_R32) or knockout_live

    tabs: list[dict] = []
    for tab_id, label, sub in STAGE_TABS:
        if tab_id is None or tab_id == FILTER_ALL:
            tabs.append({"id": tab_id, "label": label, "sub": sub})
            continue
        if hide_group_tabs and tab_id in (STAGE_GROUP_MD1, STAGE_GROUP_MD2, STAGE_GROUP_MD3):
            continue
        n = counts.get(tab_id, 0) if tab_id >= STAGE_R32 else visible_counts.get(tab_id, 0)
        if n > 0:
            entry: dict = {"id": tab_id, "label": label, "count": n}
            if sub:
                entry["sub"] = sub
            if tab_id >= STAGE_R32 and visible_counts.get(tab_id, 0) == 0:
                entry["sub"] = "Awaiting teams"
            tabs.append(entry)
    return tabs


def is_knockout_matchday(matchday: int | None) -> bool:
    return matchday is not None and matchday >= STAGE_R32


def is_knockout_code(code: str | None) -> bool:
    return bool(code and code in KNOCKOUT_SHORT_CODES)


def stage_label(matchday: int | None) -> str:
    if matchday is None:
        return ""
    return STAGE_LABELS.get(matchday, f"Stage {matchday}")


def stage_short(matchday: int | None) -> str:
    if matchday is None:
        return ""
    if matchday <= STAGE_GROUP_MD3:
        return f"MD{matchday}"
    return STAGE_SHORT.get(matchday, f"S{matchday}")


def _stage_from_date(kd: date) -> tuple[int, str]:
    """Infer knockout round from kickoff when ESPN uses real team names."""
    if kd <= GROUP_STAGE_END:
        return 0, ""
    if kd <= date(2026, 7, 3):
        return STAGE_R32, "R32"
    if kd <= date(2026, 7, 8):
        return STAGE_R16, "R16"
    if kd <= date(2026, 7, 11):
        return STAGE_QF, "QF"
    if kd <= date(2026, 7, 15):
        return STAGE_SF, "SF"
    if kd == date(2026, 7, 18):
        return STAGE_THIRD, "3P"
    return STAGE_FINAL, "F"


def infer_stage_from_placeholder_teams(home: str, away: str, kickoff: datetime) -> tuple[int, str] | None:
    """Infer the actual round from bracket-slot team names.

    Example: "Quarterfinal 1 Winner vs Quarterfinal 2 Winner" is a semi-final,
    not a quarter-final.
    """
    names = f"{home} {away}".lower()
    if "round of 32" in names:
        return STAGE_R16, "R16"
    if "round of 16" in names:
        return STAGE_QF, "QF"
    if "quarterfinal" in names or "quarter-final" in names or "quarter final" in names:
        return STAGE_SF, "SF"
    if "semifinal" in names or "semi-final" in names or "semi final" in names:
        return _stage_from_date(kickoff.date())
    return None


def stage_from_espn_event(name: str, kickoff: datetime) -> tuple[int, str, bool]:
    """Return (matchday, short_stage_code, is_knockout). matchday=0 means group (set later).

    Name keywords are authoritative. Date-only inference is not used here — late MD3
    group games kick off after GROUP_STAGE_END and must stay in the group stage.
    """
    n = name.lower()

    if "round of 32" in n:
        return STAGE_R32, "R32", True
    if "round of 16" in n:
        return STAGE_R16, "R16", True
    if "quarterfinal" in n or "quarter-final" in n or "quarter final" in n:
        return STAGE_QF, "QF", True
    if "semifinal" in n or "semi-final" in n or "semi final" in n:
        return STAGE_SF, "SF", True
    if "3rd" in n or "third place" in n or "bronze" in n:
        return STAGE_THIRD, "3P", True
    if re.search(r"\bfinal\b", n) and "semi" not in n and "quarter" not in n:
        return STAGE_FINAL, "F", True

    # Bracket placeholders (e.g. "Round of 32 8 Winner") — stage from slot text.
    if _PLACEHOLDER_TEAM_RE.search(n):
        if "round of 32" in n or "r32" in n:
            return STAGE_R32, "R32", True
        if "round of 16" in n or "r16" in n:
            return STAGE_R16, "R16", True
        if "quarterfinal" in n or "quarter-final" in n:
            return STAGE_QF, "QF", True
        if "semifinal" in n or "semi-final" in n:
            return STAGE_SF, "SF", True

    return 0, "", False
