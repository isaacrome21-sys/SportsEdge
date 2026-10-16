"""#2274 completeness (t207u + independent audit of fce702df).

Completeness of the official inactive list is proven only when the bridge
itself verifies (a) the inactive snapshot's canonical hash against an
externally pinned inactives manifest and (b) the partition against an
official game-day roster from an INDEPENDENT source with its OWN pinned
manifest. Any in-process token, caller flag, or row count proves nothing;
failure is UNKNOWN / INACTIVES_COMPLETENESS_UNVERIFIED.
"""
import copy
import hashlib
import json

from sportsedge.nfl_participation_bridge import require_confirmed_qb_role
from test_nfl_participation_remediation_20261014 import (
    _qb_verdict, _snapshot, _assert_completeness_refusal, GAMEDAY, depth_rows)
from nfl_completeness_evidence_fixture import (
    canonical_sha256, evidence, prove, roster_for)

IDS = ["rb2", "x1", "x2", "x3", "x4", "x5", "x6"]


def _gate(v):
    return require_confirmed_qb_role(v, depth_rows=depth_rows(), as_of=GAMEDAY)


def _proven():
    snap = _snapshot(IDS)
    ev = prove([snap], depth_rows())
    return snap, ev


def test_genuinely_proven_list_confirms_qb():
    snap, ev = _proven()
    v = _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev)
    assert v["state"] == "CONFIRMED_STARTER"
    assert v["inactives_completeness"] == "VERIFIED_COMPLETE"


def test_no_evidence_is_unknown_even_with_partition_fields():
    snap, _ = _proven()
    _assert_completeness_refusal(_qb_verdict(inactive_snapshots=[snap]), _gate)


def test_forged_in_process_token_fails():
    # Any object/flag attached in-process is ignored; without pinned
    # manifests the list is UNKNOWN.
    class ArchiveProvenance:  # attacker-minted look-alike
        manifest_sha256 = "0" * 64
        bundle_sha256 = "1" * 64
    snap, _ = _proven()
    snap["_archive_provenance"] = ArchiveProvenance()
    snap["complete"] = True
    _assert_completeness_refusal(_qb_verdict(inactive_snapshots=[snap]), _gate)


def test_post_load_edit_of_snapshot_invalidates_proof():
    snap, ev = _proven()
    snap["player_ids"] = snap["player_ids"][:-1]  # truncate after pinning
    snap["active_player_ids"] = snap["active_player_ids"] + ["x6"]
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev), _gate)


def test_manifest_bytes_not_matching_pin_fail():
    snap, ev = _proven()
    ev = dict(ev, inactives_manifest_sha256="f" * 64)
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev), _gate)


def test_roster_mismatching_independent_official_roster_fails():
    snap, _ = _proven()
    # Independent official roster has an extra player the partition omits.
    roster = roster_for(snap, snap["active_player_ids"] + ["omitted-player"])
    ev = evidence([snap], [roster])
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev), _gate)


def test_roster_edited_after_pinning_fails():
    snap, ev = _proven()
    ev = copy.deepcopy(ev)
    ev["official_rosters"][0]["player_ids"].append("injected")
    snap["active_player_ids"].append("injected")
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev), _gate)


def test_roster_not_independent_same_pin_or_source_fails():
    snap, _ = _proven()
    roster = roster_for(snap, snap["active_player_ids"])
    same_src = evidence([snap], [roster], inactives_source="X", roster_source="X")
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=same_src), _gate)
    ev = evidence([snap], [roster])
    same_pin = dict(ev, roster_manifest=ev["inactives_manifest"],
                    roster_manifest_sha256=ev["inactives_manifest_sha256"])
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=same_pin), _gate)


def test_missing_independent_roster_is_unknown():
    snap, ev = _proven()
    ev = dict(ev, official_rosters=[])
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev), _gate)
