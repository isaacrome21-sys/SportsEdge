"""#2274 completeness (t207u + audits of fce702df and 7fdebfc7).

Proof requires: manifest bytes whose SHA-256 is covered by an OPERATOR
flag pin or a committed-config published pin (never a pin from the
evidence payload); manifest sources on the committed allowlist; the
inactive snapshot's canonical hash listed; an independently sourced
official game-day roster (separate allowlisted source, separate pin);
an exact inactive/active partition of that roster.  Otherwise UNKNOWN.
"""
import copy
import hashlib

from sportsedge.nfl_participation_bridge import require_confirmed_qb_role
from test_nfl_participation_remediation_20261014 import (
    _qb_verdict, _snapshot, _assert_completeness_refusal, GAMEDAY, GAME_ID,
    depth_rows)
from nfl_completeness_evidence_fixture import (
    manifests, official_roster, operator_pins, prove, with_actives)

IDS = ["rb2"] + [f"chi-inactive-{i}" for i in range(1, 7)]


def _gate(v):
    return require_confirmed_qb_role(v, depth_rows=depth_rows(), as_of=GAMEDAY)


def _proven():
    snap = with_actives([_snapshot(IDS)])[0]
    ev, pins = prove([snap])
    return snap, ev, pins


def _refused(snap, ev, pins):
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev,
                    operator_manifest_pins=pins), _gate)


def test_genuinely_proven_list_confirms_qb():
    snap, ev, pins = _proven()
    v = _qb_verdict(inactive_snapshots=[snap], completeness_evidence=ev,
                    operator_manifest_pins=pins)
    assert v["state"] == "CONFIRMED_STARTER"
    assert v["inactives_completeness"] == "VERIFIED_COMPLETE"


def test_self_sealed_truncated_list_and_roster_is_unknown():
    # The audit's attack: a truncated inactive list (rb2 omitted -> it
    # would read as active) plus a matching truncated "roster", sealed by
    # the caller with its own pins inside the evidence, under made-up
    # sources.  No operator pin covers it -> UNKNOWN.
    snap = _snapshot([f"chi-inactive-{i}" for i in range(1, 6)])
    snap["active_player_ids"] = ["qb1", "rb1", "rb2", "wr1"]
    roster = official_roster(GAME_ID, "CHI", snap["published_at"],
                             player_ids=snap["player_ids"] + snap["active_player_ids"],
                             source="MADE_UP_ROSTER")
    ev = manifests([snap], [roster], inactives_source="MADE_UP_INACTIVES",
                   roster_source="MADE_UP_ROSTER")
    sealed = dict(ev, **{f"{k}_sha256": v[0] for k, v in
                         (("inactives_manifest", operator_pins(ev)["inactives"]),
                          ("roster_manifest", operator_pins(ev)["roster"]))})
    _refused(snap, sealed, None)
    # Even when the same self-sealed pins are smuggled into the operator
    # channel, the made-up sources are not on the committed allowlist.
    _refused(snap, sealed, operator_pins(ev))


def test_self_sealed_with_allowlisted_source_names_still_unknown():
    snap = _snapshot([f"chi-inactive-{i}" for i in range(1, 6)])
    snap["active_player_ids"] = ["qb1", "rb1", "rb2", "wr1"]
    roster = official_roster(GAME_ID, "CHI", snap["published_at"],
                             player_ids=snap["player_ids"] + snap["active_player_ids"])
    ev = manifests([snap], [roster])
    ev["inactives_manifest_sha256"] = hashlib.sha256(ev["inactives_manifest"]).hexdigest()
    ev["roster_manifest_sha256"] = hashlib.sha256(ev["roster_manifest"]).hexdigest()
    _refused(snap, ev, None)  # pins in the payload are ignored


def test_operator_pins_for_other_manifests_do_not_cover_caller_bytes():
    snap, ev, _ = _proven()
    _refused(snap, ev, {"inactives": ["a" * 64], "roster": ["b" * 64]})


def test_no_evidence_is_unknown_even_with_partition_fields():
    snap, _, pins = _proven()
    _assert_completeness_refusal(
        _qb_verdict(inactive_snapshots=[snap], operator_manifest_pins=pins), _gate)


def test_forged_in_process_token_fails():
    class ArchiveProvenance:
        manifest_sha256 = "0" * 64
        bundle_sha256 = "1" * 64
    snap, _, _ = _proven()
    snap["_archive_provenance"] = ArchiveProvenance()
    snap["complete"] = True
    _assert_completeness_refusal(_qb_verdict(inactive_snapshots=[snap]), _gate)


def test_post_load_edit_of_snapshot_invalidates_proof():
    snap, ev, pins = _proven()
    snap["player_ids"] = snap["player_ids"][:-1]
    snap["active_player_ids"] = snap["active_player_ids"] + ["chi-inactive-6"]
    _refused(snap, ev, pins)


def test_roster_mismatching_independent_official_roster_fails():
    snap, _, _ = _proven()
    roster = official_roster(GAME_ID, "CHI", snap["published_at"],
                             player_ids=snap["player_ids"] + snap["active_player_ids"]
                             + ["omitted-player"])
    ev = manifests([snap], [roster])
    _refused(snap, ev, operator_pins(ev))


def test_roster_edited_after_pinning_fails():
    snap, ev, pins = _proven()
    ev = copy.deepcopy(ev)
    ev["official_rosters"][0]["player_ids"].append("injected")
    snap["active_player_ids"].append("injected")
    _refused(snap, ev, pins)


def test_same_source_or_same_manifest_for_both_sides_fails():
    snap, _, _ = _proven()
    roster = official_roster(GAME_ID, "CHI", snap["published_at"])
    ev = manifests([snap], [roster], roster_source="NFL_GAMEDAY_INACTIVES")
    _refused(snap, ev, operator_pins(ev))
    ev = manifests([snap], [roster])
    same = dict(ev, roster_manifest=ev["inactives_manifest"])
    _refused(snap, same, operator_pins(same))


def test_missing_independent_roster_is_unknown():
    snap, ev, pins = _proven()
    _refused(snap, dict(ev, official_rosters=[]), pins)
