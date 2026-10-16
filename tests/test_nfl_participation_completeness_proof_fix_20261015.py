"""#2274 completeness proof (t207u): only pinned-archive provenance plus a
verifiable official game-day roster partition proves completeness; anything
else is UNKNOWN. Never a row count, never a caller flag."""
from sportsedge.nfl_participation_archive import PROVENANCE_KEY
from sportsedge.nfl_participation_bridge import require_confirmed_qb_role
from test_nfl_participation_remediation_20261014 import (
    _qb_verdict, _snapshot, _assert_completeness_refusal, GAMEDAY, depth_rows)
from test_nfl_participation_wiring_20261014 import _proven

IDS = ["rb2", "x1", "x2", "x3", "x4", "x5", "x6"]


def _refused(snap):
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap]),
        lambda v: require_confirmed_qb_role(v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_partition_without_archive_provenance_is_unknown():
    _refused(_proven(_snapshot(IDS), attach_token=False))


def test_forged_json_provenance_value_is_unknown():
    snap = _proven(_snapshot(IDS), attach_token=False)
    snap[PROVENANCE_KEY] = {"manifest_sha256": "0" * 64, "bundle_sha256": "1" * 64}
    _refused(snap)


def test_provenance_with_roster_gap_is_unknown():
    snap = _proven(_snapshot(IDS))
    snap["gameday_roster_player_ids"] = snap["gameday_roster_player_ids"] + ["missing"]
    _refused(snap)


def test_provenance_with_overlapping_partition_is_unknown():
    snap = _proven(_snapshot(IDS))
    snap["active_player_ids"] = snap["active_player_ids"] + ["rb2"]
    _refused(snap)


def test_candidate_absent_from_verified_roster_is_unknown():
    snap = _proven(_snapshot(IDS))
    snap["active_player_ids"] = [p for p in snap["active_player_ids"] if p != "qb1"]
    snap["gameday_roster_player_ids"] = [p for p in snap["gameday_roster_player_ids"] if p != "qb1"]
    _refused(snap)


def test_proven_partition_confirms_qb():
    v = _qb_verdict(inactive_snapshots=[_proven(_snapshot(IDS))])
    assert v["state"] == "CONFIRMED_STARTER"
    assert v["inactives_completeness"] == "VERIFIED_COMPLETE"
