"""RED / expected-failing security battery against NFL participation #2274.

Five or more entries are not proof of the COMPLETE official game-day inactive
list. A truncated five- or seven-row list can omit a player and incorrectly
mark him active; a content-addressed archive preserves bytes, not publisher
completeness. Do not weaken these tests to reestablish green.
"""
import pytest
from sportsedge.nfl_participation_bridge import (
    NFLParticipationError, require_confirmed_qb_role, require_confirmed_skill_role,
    assess_skill_participation,
)
from test_nfl_participation_remediation_20261014 import (
    _qb_verdict, _snapshot, _assert_completeness_refusal, GAME_ID, KICKOFF, GAMEDAY, depth_rows,
)


@pytest.mark.parametrize("count", (5, 6, 7, 10))
def test_truncated_n_row_list_cannot_prove_qb_is_active(count):
    ids = ["rb2"] + [f"truncated-{i}" for i in range(count - 1)]
    verdict = _qb_verdict(inactive_snapshots=[_snapshot(ids)])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_forged_complete_flag_and_seven_ids_do_not_prove_active_skill():
    snapshot = _snapshot(["rb2", "x1", "x2", "x3", "x4", "x5", "x6"])
    snapshot["complete"] = True  # unauthenticated caller assertion, NOT proof
    verdict = assess_skill_participation(
        team="CHI", player_id="wr1", depth_rows=depth_rows(),
        inactive_snapshots=[snapshot], game_id=GAME_ID, target_season=2026,
        target_week=4, kickoff=KICKOFF, as_of=GAMEDAY)
    _assert_completeness_refusal(verdict, require_confirmed_skill_role)
