"""Build V2E possession outcomes on top of the frozen PIT M2 history rows."""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any, Iterable, Mapping

from .m2 import _validated_feature_vector


def _truthy(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return float(value) == 1.0
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"true", "t", "yes", "y"}


def _drive_key(row: Mapping[str, Any]) -> tuple[str, str]:
    gid = str(row.get("game_id") or row.get("nflverse_game_id") or "").strip()
    drive = str(row.get("drive") or "").strip()
    return gid, drive


def _score_drive(plays: list[dict[str, Any]], offense: str, defense: str) -> str:
    for row in plays:
        td_team = str(row.get("td_team") or "").strip()
        if _truthy(row.get("touchdown")) or _truthy(row.get("return_touchdown")):
            if td_team == defense:
                return "def_td_7_allowed"
            if td_team == offense or not td_team:
                # First V2E slice treats an offensive TD as the dominant 7-point
                # branch. XP/2PT refinement requires a separate frozen hypothesis.
                return "td_xp"
    for row in plays:
        if str(row.get("field_goal_result") or "").strip().lower() == "made":
            return "fg"
    for row in plays:
        if _truthy(row.get("safety")):
            return "safety_allowed"
    return "no_score"


def build_v2e_possession_rows(
    history_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach realized drive terminal outcomes to already-PIT-safe feature rows.

    Current-game PBP is used only for the realized training/evaluation target.
    Pregame state comes exclusively from the existing M2 history row.
    """
    history = {str(row.get("game_id") or ""): dict(row) for row in history_rows}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in pbp_rows:
        row = dict(raw)
        gid, drive = _drive_key(row)
        if gid not in history or not drive:
            continue
        posteam = str(row.get("posteam") or "").strip()
        if not posteam:
            continue
        grouped[(gid, drive)].append(row)

    per_game: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for (gid, _), plays in grouped.items():
        plays.sort(key=lambda row: float(row.get("play_id") or 0.0))
        offense = str(plays[0].get("posteam") or "").strip()
        defense = str(plays[0].get("defteam") or "").strip()
        if not offense or not defense:
            continue
        per_game[gid][offense].append(_score_drive(plays, offense, defense))

    output: list[dict[str, Any]] = []
    for gid, base in history.items():
        home = str(base.get("home_team") or "").strip()
        away = str(base.get("away_team") or "").strip()
        home_outcomes = per_game.get(gid, {}).get(home, [])
        away_outcomes = per_game.get(gid, {}).get(away, [])
        if not home_outcomes or not away_outcomes:
            continue
        row: dict[str, Any] = {
            "game_id": gid,
            "season": int(base["season"]),
            "week": base.get("week"),
            "home_team": home,
            "away_team": away,
            "home_score": base.get("home_score"),
            "away_score": base.get("away_score"),
            "home_state": _validated_feature_vector(dict(base["home_features"]), "home"),
            "away_state": _validated_feature_vector(dict(base["away_features"]), "away"),
            "home_drives": len(home_outcomes),
            "away_drives": len(away_outcomes),
            # Market data remains evaluation-only and is never supplied to fit.
            "spread_line": base.get("spread_line"),
            "home_spread_odds": base.get("home_spread_odds"),
            "away_spread_odds": base.get("away_spread_odds"),
            "total_line": base.get("total_line"),
            "over_odds": base.get("over_odds"),
            "under_odds": base.get("under_odds"),
        }
        for side, outcomes in (("home", home_outcomes), ("away", away_outcomes)):
            for outcome in ("td_xp", "td_2pt", "td_no_try", "fg", "def_td_7_allowed", "safety_allowed", "no_score"):
                row[f"{side}_{outcome}"] = outcomes.count(outcome)
        if any(not isfinite(float(row[key])) for key in ("home_score", "away_score")):
            continue
        output.append(row)
    return output
