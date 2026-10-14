"""Red-team property: membership in a partial inactive list is not completeness.

A content-addressed archived payload can be internally authentic yet incomplete
relative to the upstream official release. These are synthetic counterexamples.
No betting authority or actual 2026 roster facts are inferred.
"""
from sportsedge.nfl_participation_bridge import (
    assess_qb_participation,
    assess_skill_participation,
    require_confirmed_qb_role,
    require_confirmed_skill_role,
    NFLParticipationError,
)

from test_nfl_participation_wiring_20261014 import (
    GAME_ID, GAMEDAY, KICKOFF, depth_rows, _complete_ids,
)

import pytest


def _snapshot(ids):
    return {
        "game_id": GAME_ID,
        "team": "CHI",
        "published_at": "2026-10-04T15:30:00Z",
        "player_ids": ids,
    }


def _partial_but_plausible(full):
    # A realistic failure mode: upstream published 7, capture archived a
    # well-formed 5-name *subset* with the real target omitted. Neither a
    # SHA pin nor a cardinality floor proves this was the full official list.
    assert len(full) == 7
    return [v for v in full if v != full[0]][:5]


def test_five_of_seven_upstream_qb_inactive_absence_is_not_confirmation():
    original = _complete_ids("CHI", ("qb1",))
    subset = _partial_but_plausible(original)
    assert len(subset) == 5 and "qb1" not in subset
    verdict = assess_qb_participation(
        team="CHI", expected_player_id="qb1",
        depth_rows=depth_rows(), inactive_snapshots=[_snapshot(subset)],
        game_id=GAME_ID, target_season=2026, target_week=4,
        kickoff=KICKOFF, as_of=GAMEDAY)
    assert verdict["state"] == "UNKNOWN"
    assert verdict["subclass"] == "INACTIVES_COMPLETENESS_UNVERIFIED"
    with pytest.raises(NFLParticipationError):
        require_confirmed_qb_role(
            verdict, depth_rows=depth_rows(), as_of=GAMEDAY)


def test_five_of_seven_upstream_skill_inactive_absence_is_not_confirmation():
    original = _complete_ids("CHI", ("wr1",))
    subset = _partial_but_plausible(original)
    assert len(subset) == 5 and "wr1" not in subset
    verdict = assess_skill_participation(
        team="CHI", player_id="wr1", position="WR",
        depth_rows=depth_rows(), inactive_snapshots=[_snapshot(subset)],
        game_id=GAME_ID, target_season=2026, target_week=4,
        kickoff=KICKOFF, as_of=GAMEDAY)
    assert verdict["state"] == "UNKNOWN"
    assert verdict["subclass"] == "INACTIVES_COMPLETENESS_UNVERIFIED"
    with pytest.raises(NFLParticipationError):
        require_confirmed_skill_role(verdict)
