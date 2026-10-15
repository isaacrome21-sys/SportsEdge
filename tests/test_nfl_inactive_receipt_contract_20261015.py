"""Fail-closed contract tests for NFL inactive completeness receipt verification.

Synthetic test data only. The verifier callback represents an independently
authenticated publisher at a trusted intake boundary; no production verifier
is supplied by these tests.
"""
from datetime import datetime, timezone

import pytest

from sportsedge.nfl_participation_bridge import (
    _complete_inactive_snapshot_receipt,
)

GAME = "synthetic-game"
TEAM = "CHI"
PUBLISHED = "2026-10-04T15:30:00Z"
CUTOFF = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)


def snapshot():
    return {
        "game_id": GAME, "team": TEAM, "published_at": PUBLISHED,
        "player_ids": ["inactive-a", "inactive-b", "inactive-c", "inactive-d", "inactive-e", "inactive-f", "inactive-g"],
    }


def receipt():
    return {
        "game_id": GAME, "team": TEAM, "published_at": PUBLISHED,
        "player_ids": ["inactive-a", "inactive-b", "inactive-c", "inactive-d", "inactive-e", "inactive-f", "inactive-g"],
        "source_complete": True,
    }


def verify(*, verifier=None, snap=None, rec=None, cutoff=CUTOFF,
           game=GAME, team=TEAM):
    return _complete_inactive_snapshot_receipt(
        snapshot() if snap is None else snap,
        receipt() if rec is None else rec,
        game_id=game, team_id=team, cutoff=cutoff,
        trusted_issuer_verifier=verifier,
    )


def test_no_trusted_verifier_never_confirms():
    assert verify() is False
    assert verify(verifier=True) is False


def test_trusted_verifier_must_explicitly_return_true():
    assert verify(verifier=lambda *_: None) is False
    assert verify(verifier=lambda *_: 1) is False
    assert verify(verifier=lambda *_: False) is False
    assert verify(verifier=lambda *_: True) is True


def test_source_completeness_is_required_even_with_verifier():
    rec = receipt()
    rec["source_complete"] = False
    assert verify(rec=rec, verifier=lambda *_: True) is False


@pytest.mark.parametrize("field,value", [
    ("game_id", "different-game"),
    ("team", "GB"),
    ("published_at", "2026-10-04T15:45:00Z"),
    ("player_ids", ["inactive-a"]),
    ("player_ids", ["inactive-b", "inactive-a"]),
])
def test_receipt_identity_or_content_mismatch_fails(field, value):
    rec = receipt()
    rec[field] = value
    assert verify(rec=rec, verifier=lambda *_: True) is False


def test_future_publication_fails_even_with_trusted_verifier():
    assert verify(verifier=lambda *_: True,
                  cutoff=datetime(2026, 10, 4, 15, 0,
                                  tzinfo=timezone.utc)) is False


def test_verifier_exception_fails_closed():
    def broken(*_):
        raise RuntimeError("issuer unavailable")
    assert verify(verifier=broken) is False


def test_inline_authentication_flags_cannot_substitute_for_verifier():
    rec = receipt()
    rec.update({"issuer_authenticated": True, "complete": True,
                "independently_verified": True})
    assert verify(rec=rec) is False


def test_internal_scan_accepts_only_separately_verified_receipt():
    from sportsedge.nfl_participation_bridge import _inactive_scan
    kickoff = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    kwargs = dict(game_id=GAME, team_id=TEAM,
                  candidate_id="active-qb", kickoff=kickoff, cutoff=CUTOFF)
    unverified = _inactive_scan([], [snapshot()], **kwargs)
    assert unverified["complete_published"] is False
    verified = _inactive_scan(
        [], [snapshot()], trusted_receipts=[receipt()],
        trusted_issuer_verifier=lambda *_: True, **kwargs)
    assert verified["complete_published"] is True
    wrong = receipt()
    wrong["player_ids"] = ["inactive-a"]
    rejected = _inactive_scan(
        [], [snapshot()], trusted_receipts=[wrong],
        trusted_issuer_verifier=lambda *_: True, **kwargs)
    assert rejected["complete_published"] is False


def test_conflicting_same_instant_lists_never_confirm():
    from sportsedge.nfl_participation_bridge import _inactive_scan
    kickoff = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    conflict = snapshot()
    conflict["player_ids"] = ["inactive-a", "inactive-b", "inactive-c", "inactive-d", "inactive-e", "inactive-f", "inactive-h"]
    out = _inactive_scan(
        [], [snapshot(), conflict], game_id=GAME, team_id=TEAM,
        candidate_id="active-qb", kickoff=kickoff, cutoff=CUTOFF,
        trusted_receipts=[receipt()],
        trusted_issuer_verifier=lambda *_: True)
    assert out["complete_published"] is False


def test_qb_assessment_receipt_can_confirm_only_via_trusted_verifier():
    from sportsedge.nfl_participation_bridge import assess_qb_participation
    # nflverse-shaped rank-one QB depth row, within the age cutoff.
    depth = [{"dt": "2026-10-04T12:00:00Z", "team": TEAM,
              "gsis_id": "active-qb", "player_name": "Synthetic QB",
              "pos_abb": "QB", "pos_rank": 1}]
    kwargs = dict(
        team=TEAM, depth_rows=depth, game_id=GAME,
        target_season=2026, target_week=4,
        kickoff="2026-10-04T17:00:00Z",
        as_of="2026-10-04T16:00:00Z",
        inactive_snapshots=[snapshot()],
    )
    no_receipt = assess_qb_participation(**kwargs)
    assert no_receipt["state"] != "CONFIRMED_STARTER"
    confirmed = assess_qb_participation(
        **kwargs, trusted_inactive_receipts=[receipt()],
        trusted_issuer_verifier=lambda *_: True)
    assert confirmed["state"] == "CONFIRMED_STARTER"
    untrusted = assess_qb_participation(
        **kwargs, trusted_inactive_receipts=[receipt()])
    assert untrusted["state"] != "CONFIRMED_STARTER"


def test_older_authenticated_list_cannot_override_newer_revision():
    from sportsedge.nfl_participation_bridge import _inactive_scan
    kickoff = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    revised = snapshot()
    revised["published_at"] = "2026-10-04T15:45:00Z"
    revised["player_ids"] = [
        "inactive-a", "inactive-b", "inactive-c", "inactive-d",
        "inactive-e", "inactive-f", "inactive-new",
    ]
    out = _inactive_scan(
        [], [snapshot(), revised], game_id=GAME, team_id=TEAM,
        candidate_id="active-qb", kickoff=kickoff, cutoff=CUTOFF,
        trusted_receipts=[receipt()],
        trusted_issuer_verifier=lambda *_: True,
    )
    assert out["evidence_present"] is True
    assert out["complete_published"] is False


def test_later_truncated_revision_blocks_older_trusted_absence_proof():
    from sportsedge.nfl_participation_bridge import _inactive_scan
    kickoff = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    later = snapshot()
    later["published_at"] = "2026-10-04T15:45:00Z"
    later["player_ids"] = ["inactive-a"]  # visibly incomplete revision
    out = _inactive_scan(
        [], [snapshot(), later], game_id=GAME, team_id=TEAM,
        candidate_id="active-qb", kickoff=kickoff, cutoff=CUTOFF,
        trusted_receipts=[receipt()],
        trusted_issuer_verifier=lambda *_: True,
    )
    assert out["evidence_present"] is True
    assert out["complete_published"] is False


def test_receipt_cannot_authenticate_different_snapshot_identity():
    wrong_game = snapshot()
    wrong_game["game_id"] = "different-game"
    wrong_team = snapshot()
    wrong_team["team"] = "GB"
    issuer = lambda *_: True
    assert verify(snap=wrong_game, verifier=issuer) is False
    assert verify(snap=wrong_team, verifier=issuer) is False


def test_completeness_refuses_coerced_or_noncanonical_player_ids():
    from sportsedge.nfl_participation_bridge import _snapshot_player_ids
    for bad in (None, 42, True, {"id": "inactive-g"}, " inactive-g ", ""):
        altered = snapshot()
        altered["player_ids"][-1] = bad
        assert _snapshot_player_ids(altered) is None
        assert verify(snap=altered, verifier=lambda *_: True) is False


def test_same_instant_malformed_revision_blocks_complete_inference():
    from sportsedge.nfl_participation_bridge import _inactive_scan
    kickoff = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    malformed = snapshot()
    malformed["player_ids"] = ["inactive-a"]
    out = _inactive_scan(
        [], [snapshot(), malformed], game_id=GAME, team_id=TEAM,
        candidate_id="active-qb", kickoff=kickoff, cutoff=CUTOFF,
        trusted_receipts=[receipt()],
        trusted_issuer_verifier=lambda *_: True,
    )
    assert out["complete_published"] is False


@pytest.mark.parametrize("limit", [0, -1, 97, float("nan"), float("inf")])
def test_qb_and_skill_reject_unsafe_depth_age_limit(limit):
    from sportsedge.nfl_participation_bridge import (
        NFLParticipationError, assess_qb_participation, assess_skill_participation,
    )
    kwargs = dict(team=TEAM, depth_rows=[], target_season=2026,
                  target_week=4, kickoff="2026-10-04T17:00:00Z",
                  as_of="2026-10-04T16:00:00Z", max_depth_age_hours=limit)
    for fn, extra in ((assess_qb_participation, {}),
                      (assess_skill_participation, {"player_id": "synthetic-p"})):
        with pytest.raises(NFLParticipationError,
                           match="NFL_PARTICIPATION_DEPTH_AGE_LIMIT_INVALID"):
            fn(**kwargs, **extra)
