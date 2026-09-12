"""Point-in-time-safe drive outcome extraction for the NFL V2E diagnostic.

The extractor consumes frozen nflverse PBP bytes plus schedule identities. It
creates realized drive outcomes for *training targets only*. No sportsbook field
is accepted or emitted. Defensive scores are explicitly separated from
possession-team offensive scores so a pick-six is never mislabeled as an
offensive touchdown.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

V2E_DRIVE_SOURCE_CONTRACT = "NFL_V2E_NFLVERSE_DRIVE_OUTCOME_V1"
V2E_TEAM_ALIAS_POLICY = "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1"
# Source-proven in the hash-bound 2016-2025 V2G corpus. Keep this explicit and
# minimal: no fuzzy matching and no inferred franchise aliases are permitted.
_SCHEDULE_TO_PBP_TEAM_ALIAS = {"OAK": "LV", "SD": "LAC"}

_PROHIBITED = {
    "spread", "spread_line", "total", "total_line", "moneyline", "odds",
    "price", "closing_spread", "closing_total", "implied_probability",
    "tickets", "handle", "consensus",
}


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    text = str(value or "").strip().lower()
    return text in {"1", "1.0", "true", "t", "yes"}


def _assert_market_blind(row: Mapping[str, Any]) -> None:
    for key in row:
        if str(key).strip().lower() in _PROHIBITED:
            raise ValueError(f"NFL_V2E_DRIVE_MARKET_DATA_PROHIBITED:{key}")


def _drive_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    game_id = str(row.get("game_id") or "").strip()
    posteam = str(row.get("posteam") or "").strip()
    drive = str(row.get("drive") or "").strip()
    if not game_id or not posteam or not drive:
        raise ValueError("NFL_V2E_DRIVE_IDENTITY_MISSING")
    return game_id, posteam, drive


def _schedule_index(schedule_rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[int, str, str]]:
    out: dict[str, tuple[int, str, str]] = {}
    for raw in schedule_rows:
        row = dict(raw)
        _assert_market_blind(row)
        game_id = str(row.get("game_id") or "").strip()
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        try:
            season = int(row.get("season"))
        except (TypeError, ValueError) as exc:
            raise ValueError("NFL_V2E_DRIVE_SEASON_INVALID") from exc
        if not game_id or not home or not away or home == away:
            raise ValueError("NFL_V2E_DRIVE_SCHEDULE_IDENTITY_INVALID")
        if game_id in out:
            raise ValueError(f"NFL_V2E_DRIVE_DUPLICATE_GAME:{game_id}")
        out[game_id] = (season, home, away)
    return out


def _canonical_schedule_team_for_pbp(posteam: str, *, home: str, away: str) -> tuple[str, bool]:
    """Map only source-proven current nflverse PBP codes back to schedule identity.

    The schedule remains the identity authority. A PBP code is translated only
    when one of the two expected schedule teams has the exact frozen alias whose
    value equals the observed ``posteam``. This prevents LV from being rewritten
    in modern LV schedule games and prevents any fuzzy/inferred mapping.
    """
    if posteam in {home, away}:
        return posteam, False
    matches = [
        schedule_team
        for schedule_team in (home, away)
        if _SCHEDULE_TO_PBP_TEAM_ALIAS.get(schedule_team) == posteam
    ]
    if len(matches) == 1:
        return matches[0], True
    return posteam, False


def _classify_drive(plays: list[dict[str, Any]], posteam: str) -> str:
    """Classify one possession into a mutually-exclusive terminal outcome.

    Priority follows scoring ownership rather than row order. A defensive TD on
    the possession is an allowed defensive score, not an offensive TD. Safety is
    likewise credited to the defense by the generator.
    """
    defensive_td = False
    offensive_td = False
    extra_good = False
    two_good = False
    field_goal = False
    safety_allowed = False

    for row in plays:
        td_team = str(row.get("td_team") or "").strip()
        if _truthy(row.get("touchdown")):
            canonical_td_team, _ = _canonical_schedule_team_for_pbp(
                td_team,
                home=str(row.get("_v2e_home_team") or "").strip(),
                away=str(row.get("_v2e_away_team") or "").strip(),
            )
            if canonical_td_team and canonical_td_team != posteam:
                defensive_td = True
            elif canonical_td_team == posteam:
                offensive_td = True
        if str(row.get("extra_point_result") or "").strip().lower() == "good":
            extra_good = True
        if str(row.get("two_point_conv_result") or "").strip().lower() in {"success", "good"}:
            two_good = True
        if str(row.get("field_goal_result") or "").strip().lower() == "made":
            field_goal = True
        if _truthy(row.get("safety")):
            safety_allowed = True

    if defensive_td:
        # PAT/2PT can be logged after the turnover play under a different
        # possession identity. First-slice V2E uses a conservative seven-point
        # defensive-TD event and keeps the approximation explicit in the label.
        return "def_td_7_allowed"
    if safety_allowed:
        return "safety_allowed"
    if offensive_td:
        if two_good:
            return "td_2pt"
        if extra_good:
            return "td_xp"
        return "td_no_try"
    if field_goal:
        return "fg"
    return "no_score"


def build_v2e_drive_training_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate frozen PBP into per-game drive target counts.

    Rows are deterministic and sorted by game_id. Games missing one side's drive
    evidence fail closed rather than receiving imputed possession counts.
    """
    schedule = _schedule_index(schedule_rows)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    alias_counts: dict[str, int] = defaultdict(int)
    for raw in pbp_rows:
        row = dict(raw)
        _assert_market_blind(row)
        game_id = str(row.get("game_id") or "").strip()
        if not game_id or game_id not in schedule:
            continue
        if row.get("posteam") in (None, "") or row.get("drive") in (None, ""):
            continue
        _, home, away = schedule[game_id]
        observed_posteam = str(row.get("posteam") or "").strip()
        canonical_posteam, aliased = _canonical_schedule_team_for_pbp(
            observed_posteam, home=home, away=away
        )
        row["posteam"] = canonical_posteam
        row["_v2e_home_team"] = home
        row["_v2e_away_team"] = away
        if row.get("td_team") not in (None, ""):
            canonical_td_team, td_aliased = _canonical_schedule_team_for_pbp(
                str(row.get("td_team") or "").strip(), home=home, away=away
            )
            row["td_team"] = canonical_td_team
            aliased = aliased or td_aliased
        if aliased:
            alias_counts[game_id] += 1
        grouped[_drive_key(row)].append(row)

    by_game: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for (game_id, posteam, drive), plays in sorted(grouped.items()):
        del drive
        by_game[game_id][posteam].append(_classify_drive(plays, posteam))

    outcomes = (
        "td_xp", "td_2pt", "td_no_try", "fg", "def_td_7_allowed",
        "safety_allowed", "no_score",
    )
    result: list[dict[str, Any]] = []
    for game_id in sorted(schedule):
        season, home, away = schedule[game_id]
        observed = by_game.get(game_id, {})
        home_events = observed.get(home, [])
        away_events = observed.get(away, [])
        if not home_events or not away_events:
            observed_summary = ",".join(
                f"{team}={len(events)}" for team, events in sorted(observed.items())
            ) or "NONE"
            raise ValueError(
                "NFL_V2E_DRIVE_SIDE_EVIDENCE_MISSING:"
                f"{game_id}:expected_home={home}:expected_away={away}:observed={observed_summary}"
            )
        row: dict[str, Any] = {
            "source_contract": V2E_DRIVE_SOURCE_CONTRACT,
            "team_alias_policy": V2E_TEAM_ALIAS_POLICY,
            "team_alias_application_count": alias_counts.get(game_id, 0),
            "game_id": game_id,
            "season": season,
            "home_team": home,
            "away_team": away,
            "home_drives": len(home_events),
            "away_drives": len(away_events),
        }
        for side, events in (("home", home_events), ("away", away_events)):
            for outcome in outcomes:
                row[f"{side}_{outcome}"] = events.count(outcome)
        result.append(row)
    return result
