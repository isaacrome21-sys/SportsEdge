"""PR #2274 remediation battery: the audit's required negative tests.

The integrator audit (PR #2274 comments 6179001286 / 6179031188 /
6179065239) held the participation branch on three source-integrity
defects.  Each test below is adversarial by construction: it builds the
strongest version of the attack the audit described and asserts the
stamp NEVER lifts and the refusal is named.

  B1  Inactive-snapshot completeness: a truncated / malformed /
      wrong-game / wrong-team / future-dated / stale / mixed snapshot
      must never confirm an unlisted player.  Loose rows are positive
      evidence only.  Refusal name: INACTIVES_COMPLETENESS_UNVERIFIED.
  B2  Untrusted inline bundle: a fully forged payload bundle with
      perfect-looking CONFIRMED content but no external anchor records
      UNVERIFIED_BUNDLE and lifts nothing; a tampered anchored bundle
      fails its content hash; only an anchored, pin-verified bundle
      lifts (the positive control lives in the wiring battery).
  B3  ESPN<->GSIS binding: explicit IDs, bundle-wide uniqueness --
      same-name collisions, duplicated or cross-namespace mappings,
      and missing IDs all refuse by name.

Fixtures are reused from the wiring battery (same fictional CHI/GB
universe); everything here is synthetic.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from sportsedge.nfl_participation_bridge import (
    NFLParticipationError,
    assess_qb_participation,
    assess_skill_participation,
    require_confirmed_qb_role,
    require_confirmed_skill_role,
)
from sportsedge.nfl_phone_player_pricing import phone_nfl_player_rows

from test_nfl_participation_wiring_20261014 import (
    GAME_ID,
    GAMEDAY,
    KICKOFF,
    _bundle,
    _complete_ids,
    _getter,
    _over,
    _phone_pair,
    _write_archive,
    depth_rows,
    inactive_rows,
)

STAMP = "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
NOW = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)


def _snapshot(ids, *, team="CHI", game_id=GAME_ID,
              published="2026-10-04T15:30:00Z"):
    return {"game_id": game_id, "team": team, "published_at": published,
            "player_ids": list(ids)}


def _qb_verdict(**overrides):
    kwargs = dict(
        team="CHI", depth_rows=depth_rows(), game_id=GAME_ID,
        target_season=2026, target_week=4, kickoff=KICKOFF, as_of=GAMEDAY,
        expected_player_id="qb1")
    kwargs.update(overrides)
    return assess_qb_participation(**kwargs)


def _assert_completeness_refusal(verdict, gate):
    assert verdict["state"] == "UNKNOWN"
    assert verdict["subclass"] == "INACTIVES_COMPLETENESS_UNVERIFIED"
    assert verdict["inactives_completeness"] == "UNVERIFIED"
    assert verdict["inactives_published"] is False
    with pytest.raises(NFLParticipationError,
                       match="INACTIVES_COMPLETENESS_UNVERIFIED"):
        gate(verdict)


# ------------------------------------------------------------ B1: QB

def test_b1_truncated_one_row_snapshot_never_confirms_qb():
    # The audit's headline counterexample: a one-row "snapshot" for the
    # game/team exists and qb1 is not on it.  Pre-fix this confirmed
    # every charted player; now completeness is unprovable.
    verdict = _qb_verdict(inactive_rows=inactive_rows(("rb2",)))
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_truncated_snapshot_object_below_floor_never_confirms():
    verdict = _qb_verdict(
        inactive_snapshots=[_snapshot(["rb2", "chi-x1", "chi-x2"])])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_empty_complete_list_never_confirms():
    verdict = _qb_verdict(inactive_snapshots=[_snapshot([])])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_malformed_rows_never_confirm():
    rows = [
        {"game_id": GAME_ID, "team": "CHI", "gsis_id": "rb2",
         "status": "INACTIVE", "published_at": "not-a-timestamp"},
        {"game_id": GAME_ID, "team": "CHI", "gsis_id": "wr1",
         "status": "INACTIVE"},  # no published_at at all
        {"game_id": GAME_ID, "team": "CHI", "gsis_id": "wr2",
         "status": "INACTIVE", "published_at": "2026-10-04T15:30:00"},
    ]
    verdict = _qb_verdict(inactive_rows=rows)
    assert verdict["state"] != "CONFIRMED_STARTER"
    with pytest.raises(NFLParticipationError):
        require_confirmed_qb_role(
            verdict, depth_rows=depth_rows(), as_of=GAMEDAY)


def test_b1_wrong_game_snapshot_never_confirms():
    # A complete snapshot for a DIFFERENT game is not evidence for
    # this fixture at all: inactives are unpublished here, the verdict
    # is the projected tier, and the gate refuses by that name.
    verdict = _qb_verdict(inactive_snapshots=[
        _snapshot(_complete_ids("CHI", ("rb2",)), game_id="other-game")])
    assert verdict["state"] == "PROJECTED_STARTER"
    assert verdict["inactives_completeness"] == "NOT_PUBLISHED"
    assert verdict["inactives_published"] is False
    with pytest.raises(NFLParticipationError,
                       match="NFL_QB_ROLE_NOT_CONFIRMED:PROJECTED_STARTER"):
        require_confirmed_qb_role(
            verdict, depth_rows=depth_rows(), as_of=GAMEDAY)


def test_b1_wrong_team_snapshot_never_confirms():
    # Same for the other team's complete list: it binds to GB only.
    verdict = _qb_verdict(inactive_snapshots=[
        _snapshot(_complete_ids("GB", ("gwr2",)), team="GB")])
    assert verdict["state"] == "PROJECTED_STARTER"
    assert verdict["inactives_completeness"] == "NOT_PUBLISHED"
    assert verdict["inactives_published"] is False
    with pytest.raises(NFLParticipationError,
                       match="NFL_QB_ROLE_NOT_CONFIRMED:PROJECTED_STARTER"):
        require_confirmed_qb_role(
            verdict, depth_rows=depth_rows(), as_of=GAMEDAY)


def test_b1_future_dated_snapshot_never_confirms():
    verdict = _qb_verdict(inactive_snapshots=[
        _snapshot(_complete_ids("CHI", ("rb2",)),
                  published="2026-10-04T16:30:00Z")])  # after the cutoff
    assert verdict["state"] != "CONFIRMED_STARTER"
    with pytest.raises(NFLParticipationError):
        require_confirmed_qb_role(
            verdict, depth_rows=depth_rows(), as_of=GAMEDAY)


def test_b1_stale_snapshot_never_confirms():
    # A complete list published two days before kickoff is not a
    # credible game-day publication for this fixture.
    verdict = _qb_verdict(inactive_snapshots=[
        _snapshot(_complete_ids("CHI", ("rb2",)),
                  published="2026-10-02T12:00:00Z")])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_mixed_partial_snapshots_never_confirm():
    # Two partial lists from different instants: combined they name
    # seven players, but neither is a complete snapshot, and partial
    # lists are never merged into completeness.
    rows = inactive_rows(("rb2",), published="2026-10-04T15:00:00Z") + \
        inactive_rows(("wr1",), published="2026-10-04T15:45:00Z")
    verdict = _qb_verdict(inactive_rows=rows)
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_conflicting_same_instant_snapshots_never_confirm():
    a = _snapshot(_complete_ids("CHI", ("rb2",)))
    b = _snapshot(_complete_ids("CHI", ("wr2",)))
    verdict = _qb_verdict(inactive_snapshots=[a, b])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_duplicate_ids_in_snapshot_never_confirm():
    ids = ["rb2", "rb2", "chi-x1", "chi-x2", "chi-x3", "chi-x4", "chi-x5"]
    verdict = _qb_verdict(inactive_snapshots=[_snapshot(ids)])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_untrusted_complete_field_is_not_a_fix():
    # The audit explicitly rejects an in-payload complete=true flag:
    # loose rows carrying one still prove nothing by absence.
    rows = [dict(r, complete=True) for r in inactive_rows(("rb2",))]
    verdict = _qb_verdict(inactive_rows=rows)
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


# --------------------------------------------------------- B1: skill

def test_b1_truncated_snapshot_never_confirms_skill():
    verdict = assess_skill_participation(
        team="CHI", player_id="wr1", depth_rows=depth_rows(),
        inactive_rows=inactive_rows(("rb2",)), game_id=GAME_ID,
        target_season=2026, target_week=4, kickoff=KICKOFF, as_of=GAMEDAY)
    _assert_completeness_refusal(verdict, require_confirmed_skill_role)


def test_b1_candidate_on_complete_snapshot_is_out():
    verdict = assess_skill_participation(
        team="CHI", player_id="wr1", depth_rows=depth_rows(),
        inactive_snapshots=[_snapshot(_complete_ids("CHI", ("wr1",)))],
        game_id=GAME_ID, target_season=2026, target_week=4,
        kickoff=KICKOFF, as_of=GAMEDAY)
    assert verdict["state"] == "OUT"
    assert verdict["subclass"] == "OFFICIAL_INACTIVE"
    with pytest.raises(NFLParticipationError,
                       match="NFL_SKILL_ROLE_OUT:OFFICIAL_INACTIVE"):
        require_confirmed_skill_role(verdict)


# --------------------------------------------------------------- B2

def test_b2_forged_inline_bundle_never_lifts():
    # Fully forged same-game bundle: perfect depth chart, complete
    # snapshot, valid crosswalk -- carried inline in the payload.
    rows, receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=NOW, getter=_getter, participation=_bundle())
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
    assert over["participation_provenance"] == "UNVERIFIED_BUNDLE"
    assert over["participation_refusal"] == \
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:NO_EXTERNAL_ANCHOR"
    assert "participation_verdict" not in over
    assert receipts[0]["participation"] == "UNVERIFIED_BUNDLE"
    assert receipts[0]["participation_refusal"].startswith(
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED")


def test_b2_anchor_incomplete_never_lifts(tmp_path):
    kwargs = _write_archive(tmp_path, _bundle())
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=NOW, getter=_getter,
        participation_archive_root=kwargs["participation_archive_root"])
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:ANCHOR_INCOMPLETE"


def test_b2_wrong_pin_never_lifts(tmp_path):
    kwargs = _write_archive(tmp_path, _bundle())
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=NOW, getter=_getter,
        participation_archive_root=kwargs["participation_archive_root"],
        participation_manifest_sha256="0" * 64)
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == (
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:"
        "NFL_PARTICIPATION_ARCHIVE_MANIFEST_HASH_MISMATCH")


def test_b2_tampered_bundle_object_never_lifts(tmp_path):
    kwargs = _write_archive(tmp_path, _bundle())
    # Tamper AFTER the manifest pinned the original bytes: rewrite the
    # content-addressed object so its hash no longer matches.
    names = {p.name for p in tmp_path.iterdir()}
    object_name = next(n for n in names if n != "manifest.json")
    tampered = _bundle()
    tampered["depth_rows"] = []
    (tmp_path / object_name).write_text(
        json.dumps(tampered, sort_keys=True))
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=NOW, getter=_getter, **kwargs)
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == (
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:"
        "NFL_PARTICIPATION_ARCHIVE_BUNDLE_HASH_MISMATCH")


def test_b2_missing_archive_root_never_lifts(tmp_path):
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=NOW, getter=_getter,
        participation_archive_root=str(tmp_path / "does-not-exist"),
        participation_manifest_sha256="a" * 64)
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["participation_provenance"] == "UNVERIFIED_BUNDLE"
    assert over["participation_refusal"].startswith(
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:NFL_PARTICIPATION_ARCHIVE_")


def test_b2_recorded_after_as_of_never_lifts(tmp_path):
    kwargs = _write_archive(tmp_path, _bundle(),
                            recorded="2026-10-05T00:00:00Z")
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi QB", "PLAYER_PASSING_YARDS", 269.5),
        now=NOW, getter=_getter, **kwargs)
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == (
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:"
        "NFL_PARTICIPATION_ARCHIVE_RECEIPT_NOT_AVAILABLE")


def test_b2_inline_rows_disregarded_when_anchor_present(tmp_path):
    # Anchored bundle says wr1's evidence is stale; the inline payload
    # bundle claims a fresh chart.  The anchored bytes govern -- the
    # inline claim must not rescue the lift.
    kwargs = _write_archive(tmp_path, _bundle(depth=depth_rows(
        snapshot="2026-09-20T12:00:00Z")))
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=NOW, getter=_getter, participation=_bundle(), **kwargs)
    over = _over(rows)
    assert over["participation_status"] == STAMP
    assert over["participation_provenance"] == "VERIFIED_ANCHORED"
    assert over["participation_refusal"] == \
        "NFL_PARTICIPATION_EVIDENCE_STALE"


# --------------------------------------------------------------- B3

def _phone_wr(tmp_path, bundle):
    rows, _receipts = phone_nfl_player_rows(
        _phone_pair("Chi WR One", "PLAYER_RECEIVING_YARDS", 84.5),
        now=NOW, getter=_getter, **_write_archive(tmp_path, bundle))
    return _over(rows)


def test_b3_same_name_collision_refuses(tmp_path):
    bindings = [
        {"player_name": "Chi WR One", "team": "CHI",
         "espn_player_id": "900102", "gsis_id": "wr1", "position": "WR"},
        {"player_name": "Chi WR One", "team": "GB",
         "espn_player_id": "900999", "gsis_id": "wr9", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"].startswith(
        "PARTICIPATION_BINDING_NAME_COLLISION")


def test_b3_one_espn_id_two_gsis_ids_refuses(tmp_path):
    bindings = [
        {"player_name": "Chi WR One", "team": "CHI",
         "espn_player_id": "900102", "gsis_id": "wr1", "position": "WR"},
        {"player_name": "Chi WR One Alt", "team": "CHI",
         "espn_player_id": "900102", "gsis_id": "wr2", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_BINDING_DUPLICATE:900102"


def test_b3_one_gsis_id_two_espn_ids_refuses(tmp_path):
    bindings = [
        {"player_name": "Chi WR One", "team": "CHI",
         "espn_player_id": "900102", "gsis_id": "wr1", "position": "WR"},
        {"player_name": "Chi WR Uno", "team": "CHI",
         "espn_player_id": "900103", "gsis_id": "wr1", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_BINDING_DUPLICATE:wr1"


def test_b3_missing_gsis_id_refuses(tmp_path):
    bindings = [
        {"player_name": "Chi WR One", "team": "CHI",
         "espn_player_id": "900102", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_PLAYER_BINDING_INCOMPLETE"


def test_b3_missing_espn_id_refuses(tmp_path):
    bindings = [
        {"player_name": "Chi WR One", "team": "CHI",
         "gsis_id": "wr1", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_PLAYER_BINDING_INCOMPLETE"


def test_b3_name_match_with_wrong_espn_id_never_binds(tmp_path):
    # The name matches the priced player perfectly, but the binding's
    # ESPN ID is a DIFFERENT athlete.  Name-only promotion is exactly
    # what B3 forbids: no binding exists for the resolved ESPN ID.
    bindings = [
        {"player_name": "Chi WR One", "team": "CHI",
         "espn_player_id": "900555", "gsis_id": "wr1", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_PLAYER_BINDING_MISSING"


def test_b3_binding_name_mismatch_refuses(tmp_path):
    # Correct ESPN ID, but the crosswalk's name disagrees with the
    # ESPN-resolved name: the additional cross-check refuses.
    bindings = [
        {"player_name": "Chi WR Uno", "team": "CHI",
         "espn_player_id": "900102", "gsis_id": "wr1", "position": "WR"},
    ]
    over = _phone_wr(tmp_path, _bundle(bindings=bindings))
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_BINDING_NAME_MISMATCH:900102"


def test_b3_unversioned_crosswalk_refuses(tmp_path):
    # The loader enforces the crosswalk version before the phone
    # validator ever sees the bundle (the phone layer carries the same
    # refusal name for in-process bundles; pinned by the unit test
    # below).  Either layer refuses by name; nothing lifts.
    bundle = _bundle()
    del bundle["player_bindings_version"]
    over = _phone_wr(tmp_path, bundle)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == (
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:"
        "NFL_PARTICIPATION_ARCHIVE_BINDINGS_VERSION_UNSUPPORTED")


def test_b3_phone_validator_names_unversioned_and_malformed():
    from sportsedge.nfl_phone_player_pricing import (
        _validate_participation_bundle)
    bundle = _bundle()
    del bundle["player_bindings_version"]
    _games, _by_espn, refusal = _validate_participation_bundle(bundle)
    assert refusal == "PARTICIPATION_BINDINGS_VERSION_UNSUPPORTED"
    bundle = _bundle()
    bundle["games"] = "CHI vs GB"
    _games, _by_espn, refusal = _validate_participation_bundle(bundle)
    assert refusal == "PARTICIPATION_GAMES_MALFORMED"
    bundle = _bundle()
    bundle["player_bindings"] = {"player_name": "Chi WR One"}
    _games, _by_espn, refusal = _validate_participation_bundle(bundle)
    assert refusal == "PARTICIPATION_BINDINGS_MALFORMED"


# ------------------------------------------- audit addendum: fixture

def test_addendum_ctx_kickoff_missing_never_joins(tmp_path):
    bundle = _bundle()
    bundle["games"] = [dict(bundle["games"][0], kickoff=None)]
    over = _phone_wr(tmp_path, bundle)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_GAME_KICKOFF_UNVERIFIED"


def test_addendum_ctx_kickoff_malformed_never_joins(tmp_path):
    bundle = _bundle()
    bundle["games"] = [dict(bundle["games"][0], kickoff="game day!")]
    over = _phone_wr(tmp_path, bundle)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == \
        "PARTICIPATION_GAME_KICKOFF_UNVERIFIED"


def test_addendum_malformed_games_refuse(tmp_path):
    # Malformed games never reach a name-based join: the anchored
    # loader's schema check refuses the bundle outright (the phone
    # validator's PARTICIPATION_GAMES_MALFORMED is the same refusal at
    # the in-process layer, pinned in test_b3_phone_validator...).
    bundle = _bundle()
    bundle["games"] = "CHI vs GB"
    over = _phone_wr(tmp_path, bundle)
    assert over["participation_status"] == STAMP
    assert over["participation_refusal"] == (
        "NFL_PARTICIPATION_BUNDLE_UNVERIFIED:"
        "NFL_PARTICIPATION_ARCHIVE_BUNDLE_SCHEMA_INVALID")


def test_b1_exactly_five_unique_ids_cannot_prove_qb_active():
    """Five valid rows can be a truncated official inactive list (5 of 7)."""
    verdict = _qb_verdict(inactive_snapshots=[_snapshot([
        "rb2", "chi-inactive-1", "chi-inactive-2",
        "chi-inactive-3", "chi-inactive-4",
    ])])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_inline_complete_flag_cannot_prove_five_id_snapshot():
    """A source-supplied boolean is not an independent completeness proof."""
    snapshot = _snapshot([
        "rb2", "chi-inactive-1", "chi-inactive-2",
        "chi-inactive-3", "chi-inactive-4",
    ])
    snapshot["complete"] = True
    verdict = _qb_verdict(inactive_snapshots=[snapshot])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_seven_unique_ids_still_not_independent_completeness():
    """Seven unique IDs can also be a truncated or mixed source list."""
    snapshot = _snapshot([
        "rb2", "chi-inactive-1", "chi-inactive-2",
        "chi-inactive-3", "chi-inactive-4",
        "chi-inactive-5", "chi-inactive-6",
    ])
    verdict = _qb_verdict(inactive_snapshots=[snapshot])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_b1_inline_complete_and_source_verified_flags_are_not_receipts():
    """Caller-controlled booleans must never authenticate negative evidence."""
    snapshot = _snapshot([
        "rb2", "chi-inactive-1", "chi-inactive-2",
        "chi-inactive-3", "chi-inactive-4",
        "chi-inactive-5", "chi-inactive-6",
    ])
    snapshot.update(complete=True, source_verified=True,
                    independently_verified=True)
    verdict = _qb_verdict(inactive_snapshots=[snapshot])
    _assert_completeness_refusal(
        verdict, lambda v: require_confirmed_qb_role(
            v, depth_rows=depth_rows(), as_of=GAMEDAY))


def test_receipt_verifier_refuses_untrusted_and_mismatched_identity():
    from sportsedge.nfl_participation_bridge import (
        _complete_inactive_snapshot_receipt as verify)
    snap = _snapshot(["rb2", "chi-inactive-1", "chi-inactive-2",
                      "chi-inactive-3", "chi-inactive-4"])
    receipt = {"source_complete": True, "game_id": GAME_ID,
               "team": "CHI", "published_at": snap["published_at"],
               "player_ids": sorted(snap["player_ids"])}
    args = {"game_id": GAME_ID, "team_id": "CHI",
            "cutoff": GAMEDAY}
    assert not verify(snap, receipt, **args)
    assert not verify(snap, dict(receipt, game_id="wrong"),
                      trusted_issuer_verifier=lambda *_: True, **args)
    assert not verify(snap, dict(receipt, player_ids=["rb2"]),
                      trusted_issuer_verifier=lambda *_: True, **args)
    assert not verify(snap, dict(receipt, source_complete=False),
                      trusted_issuer_verifier=lambda *_: True, **args)
    assert not verify(snap, receipt,
                      trusted_issuer_verifier=lambda *_: False, **args)
    # Synthetic trusted-verifier positive control tests the contract only;
    # production intake has no verifier wired and remains fail closed.
    assert verify(snap, receipt,
                  trusted_issuer_verifier=lambda *_: True, **args)
