"""Synthetic-only research regression tests: never represent live evidence."""
import pytest
from research.source_evidence_reconciler import reconcile

ARGS = dict(game_id="g1", subject_id="p1", fact_type="STARTER",
            as_of="2026-10-15T12:00:00Z", event_time="2026-10-15T23:00:00Z",
            pre_event_cutoff="2026-10-15T22:59:00Z")


def claim(**updates):
    row = dict(game_id="g1", subject_id="p1", fact_type="STARTER",
               fact_value="ACTIVE", source_kind="OFFICIAL_TEAM",
               source_url="https://example.org/team/announcement",
               published_at="2026-10-15T10:00:00Z",
               observed_at="2026-10-15T10:01:00Z")
    row.update(updates)
    return row


def test_credible_claim_never_authenticated():
    r = reconcile([claim()], **ARGS)
    assert r["status"] == "PROVISIONAL_UNAUTHENTICATED"
    assert not r["source_authenticity_verified"]
    assert not r["pricing_eligible"] and not r["play_authorized"]


def test_empty_unknown():
    assert reconcile([], **ARGS)["status"] == "BLOCKED_NO_CREDIBLE_EVIDENCE"


def test_x_only_blocked():
    r = reconcile([claim(source_kind="X_UNVERIFIED")], **ARGS)
    assert r["status"] == "BLOCKED_NO_CREDIBLE_EVIDENCE"
    assert r["x_unverified_claims"] == 1


def test_conflicting_claims_blocked():
    r = reconcile([claim(), claim(fact_value="OUT", source_kind="VERIFIED_REPORTER")], **ARGS)
    assert r["status"] == "BLOCKED_CONFLICT" and r["claimed_value"] is None


@pytest.mark.parametrize("update,reason", [
    ({"game_id": "wrong"}, "IDENTITY_MISMATCH"),
    ({"source_url": "http://example.org"}, "INVALID_SOURCE_OR_VALUE"),
    ({"published_at": "2026-10-15T13:00:00Z"}, "LATE_OR_FUTURE_EVIDENCE"),
    ({"observed_at": "2026-10-15T12:01:00Z"}, "LATE_OR_FUTURE_EVIDENCE"),
    ({"observed_at": "2026-10-15T01:00:00Z",
      "published_at": "2026-10-15T00:00:00Z"}, "STALE_EVIDENCE"),
    ({"source_kind": "UNVERIFIED"}, "UNVERIFIED_SOURCE_KIND"),
    ({"observed_at": None}, "INVALID_TIMESTAMP"),
])
def test_bad_claim_blocks(update, reason):
    r = reconcile([claim(**update)], **ARGS)
    assert r["status"].startswith("BLOCKED")
    assert reason in [x[1] for x in r["refusals"]]


def test_valid_plus_x_remains_blocked():
    r = reconcile([claim(), claim(source_kind="X_UNVERIFIED", fact_value="OUT")], **ARGS)
    assert r["status"] == "BLOCKED_UNRESOLVED_EVIDENCE"


def test_future_cutoff_refused():
    with pytest.raises(ValueError, match="INVALID_CUTOFF"):
        reconcile([claim()], **dict(ARGS, pre_event_cutoff="2026-10-16T00:00:00Z"))


def test_weak_staleness_policy_refused():
    with pytest.raises(ValueError, match="INVALID_MAX_AGE"):
        reconcile([claim()], **ARGS, max_age_seconds=100000)


def test_boolean_age_refused():
    with pytest.raises(ValueError, match="INVALID_MAX_AGE"):
        reconcile([claim()], **ARGS, max_age_seconds=True)


def test_out_of_order_publication_blocked():
    r = reconcile([claim(published_at="2026-10-15T11:00:00Z")], **ARGS)
    assert r["status"] == "BLOCKED_NO_CREDIBLE_EVIDENCE"
    assert "LATE_OR_FUTURE_EVIDENCE" in [reason for _, reason in r["refusals"]]


def test_unknown_source_kind_never_assumed_official():
    r = reconcile([claim(source_kind=None)], **ARGS)
    assert r["status"] == "BLOCKED_NO_CREDIBLE_EVIDENCE"
    assert not r["pricing_eligible"]
