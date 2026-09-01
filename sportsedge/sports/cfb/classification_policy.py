"""Fail-closed competition-classification policy for SportsEdge CFB.

SportsEdge CFB is currently validated only for FBS-vs-FBS games. A game is
admissible only when both canonical CFBD school names are present in a frozen
FBS membership snapshot from ``/teams/fbs``. Merely receiving a game from an
endpoint queried with ``classification=fbs`` is not sufficient because provider
classification semantics can include games involving a non-FBS opponent.

This module is governance only. It does not add predictive features or alter
model probabilities, pricing, Truth Gate floors, or promotion eligibility.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .source import CFBGame

CFB_COMPETITION_POLICY_VERSION = "CFB_FBS_ONLY_V1"
SUPPORTED_CLASSIFICATION = "FBS"


class CFBClassificationError(ValueError):
    pass


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def frozen_fbs_membership(team_rows: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    schools: set[str] = set()
    for row in team_rows:
        if not isinstance(row, Mapping):
            raise CFBClassificationError("CFB_FBS_MEMBERSHIP_ROW_INVALID")
        school = _norm(row.get("school"))
        if not school:
            raise CFBClassificationError("CFB_FBS_MEMBERSHIP_SCHOOL_MISSING")
        schools.add(school)
    if not schools:
        raise CFBClassificationError("CFB_FBS_MEMBERSHIP_EMPTY")
    return frozenset(schools)


def assert_fbs_only_games(
    games: Sequence[CFBGame],
    *,
    fbs_team_rows: Iterable[Mapping[str, Any]],
) -> None:
    """Require both teams in every game to belong to the frozen FBS roster."""
    membership = frozen_fbs_membership(fbs_team_rows)
    for game in games:
        if not isinstance(game, CFBGame):
            raise CFBClassificationError("CFB_GAME_CLASSIFICATION_OBJECT_INVALID")
        missing = [
            team for team in (game.home_team, game.away_team)
            if _norm(team) not in membership
        ]
        if missing:
            raise CFBClassificationError(
                f"CFB_FBS_ONLY_POLICY:{game.game_id}:" + ",".join(missing)
            )
