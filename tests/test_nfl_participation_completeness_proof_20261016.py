"""Adversarial tests for the inactive-list completeness PROOF mechanism.

Owner ruling (PR #2274 / #2363): a row count is not completeness, a
payload's ``complete`` flag is not completeness, and a content digest
is not completeness.  Completeness exists only when the official
inactive list reconciles exactly against two independent
enumerations (roster = actives + inactives) under
``sportsedge.nfl_participation_completeness``.  Each test here attacks
one way that proof could be faked, truncated, or misapplied; every
attack must end UNPROVEN at the verifier and fail-closed
(``UNKNOWN / INACTIVES_COMPLETENESS_UNVERIFIED``) at the bridge gate.

Synthetic fixture universe, same as the bridge battery: fictional
CHI vs GB, 2026 week 4.  No real player is referenced.
"""
from __future__ import annotations

import pytest

from sportsedge.nfl_participation_bridge import (
    NFLParticipationError,
    assess_qb_participation,
    require_confirmed_qb_role,
)
from sportsedge.nfl_participation_completeness import (
    verify_inactives_completeness,
)
from datetime import datetime, timezone

from test_nfl_participation_bridge_20261014 import (
    GAME_ID,
    KICKOFF,
    _complete_ids,
    depth_rows,
    inactive_snapshots,
)

GAMEDAY = "2026-10-04T16:00:00Z"
PRE_INACTIVES = "2026-10-02T18:00:00Z"
_KICK = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
_CUT = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
_CHARTED = ("qb1", "rb1", "wr1", "wr2")
_INACTIVES = _complete_ids("CHI", ("wr2",))


def _claim(inactives=_INACTIVES, *, official_kind="LEAGUE_OFFICIAL",
           official_source="NFL_OFFICIAL_INACTIVES_REPORT",
           roster_source="NFLVERSE_ROSTER_ENUMERATION",
           actives_source="TEAM_OFFICIAL_GAMEDAY_ACTIVES",
           published="2026-10-04T15:30:00Z",
           roster_published="2026-10-03T12:00:00Z",
           drop_actives=(), extra_actives=(),
           include_roster=True, include_actives=True, **extra):
    roster = list(dict.fromkeys([*_CHARTED, *inactives]))
    i = 1
    while len(roster) < 53:
        filler = f"chi-active-{i}"
        if filler not in roster:
            roster.append(filler)
        i += 1
    inactive_set = set(inactives)
    dropped = set(drop_actives)
    actives = [p for p in roster
               if p not in inactive_set and p not in dropped]
    actives += [p for p in extra_actives if p not in actives]
    claim = {
        "game_id": GAME_ID, "team": "CHI",
        "official_inactives": {
            "source_id": official_source, "source_kind": official_kind,
            "published_at": published, "player_ids": list(inactives)},
    }
    if include_roster:
        claim["roster"] = {
            "source_id": roster_source, "source_kind": "ROSTER_ENUMERATION",
            "published_at": roster_published, "player_ids": roster}
    if include_actives:
        claim["actives"] = {
            "source_id": actives_source,
            "source_kind": "TEAM_ACTIVES_PUBLICATION",
            "published_at": published, "player_ids": actives}
    claim.update(extra)
    return claim


def _verify(claim):
    return verify_inactives_completeness(claim, kickoff=_KICK, cutoff=_CUT)


def _qb(claims=(), snapshots=None, rows=(), as_of=GAMEDAY):
    return assess_qb_participation(
        team="CHI", depth_rows=depth_rows(), inactive_rows=list(rows),
        inactive_snapshots=inactive_snapshots() if snapshots is None
        else snapshots,
        completeness_claims=list(claims), game_id=GAME_ID,
        target_season=2026, target_week=4, kickoff=KICKOFF, as_of=as_of,
        expected_player_id="qb1")


def _assert_unproven_refusal(verdict):
    assert verdict["state"] == "UNKNOWN"
    assert verdict["subclass"] == "INACTIVES_COMPLETENESS_UNVERIFIED"
    assert verdict["inactives_completeness"] == "UNVERIFIED"
    assert verdict["inactives_published"] is False
    with pytest.raises(NFLParticipationError,
                       match="INACTIVES_COMPLETENESS_UNVERIFIED"):
        require_confirmed_qb_role(
            verdict, depth_rows=depth_rows(), as_of=GAMEDAY)


# ---------------------------------------------------------- control

def test_fully_reconciled_claim_proves_and_confirms():
    record = _verify(_claim())
    assert record["status"] == "PROVEN"
    assert record["reasons"] == []
    assert record["verified_inactive_ids"] == sorted(_INACTIVES)
    assert record["counts"] == {
        "roster": 53, "actives": 46, "inactives": 7}
    assert [s["role"] for s in record["sources"]] == [
        "OFFICIAL", "ROSTER", "ACTIVES"]
    assert len(record["proof_sha256"]) == 64
    # The proof hash is a deterministic audit binding, recomputed.
    assert _verify(_claim())["proof_sha256"] == record["proof_sha256"]

    verdict = _qb(claims=[_claim()])
    assert verdict["state"] == "CONFIRMED_STARTER"
    assert verdict["subclass"] == "GAMEDAY_ACTIVE"
    assert verdict["inactives_completeness"] == "VERIFIED_COMPLETE"
    assert verdict["inactives_completeness_proof"]["status"] == "PROVEN"
    assert require_confirmed_qb_role(
        verdict, depth_rows=depth_rows(), as_of=GAMEDAY)["state"] \
        == "CONFIRMED_STARTER"


# ---------------------------------------------------------- attacks

def test_truncated_five_row_claim_cannot_prove():
    # The five-row shape as a CLAIM: only the official part, five ids,
    # no independent enumerations to reconcile against.
    claim = _claim(inactives=_INACTIVES[:5],
                   include_roster=False, include_actives=False)
    record = _verify(claim)
    assert record["status"] == "UNPROVEN"
    assert "MISSING_ROSTER" in record["reasons"]
    assert "MISSING_ACTIVES" in record["reasons"]
    # Even presented alongside the usual snapshots, the bridge refuses.
    _assert_unproven_refusal(_qb(claims=[claim]))


def test_unofficial_source_only_cannot_prove():
    claim = _claim(official_kind="FAN_BLOG_AGGREGATOR",
                   official_source="some-blog.example/inactives")
    record = _verify(claim)
    assert record["status"] == "UNPROVEN"
    assert "OFFICIAL_SOURCE_KIND_UNRECOGNIZED" in record["reasons"]
    _assert_unproven_refusal(_qb(claims=[claim]))


def test_single_source_for_all_parts_cannot_prove():
    claim = _claim(roster_source="NFL_OFFICIAL_INACTIVES_REPORT",
                   actives_source="NFL_OFFICIAL_INACTIVES_REPORT")
    record = _verify(claim)
    assert record["status"] == "UNPROVEN"
    assert any(r.startswith("SOURCE_NOT_INDEPENDENT")
               for r in record["reasons"])
    _assert_unproven_refusal(_qb(claims=[claim]))


def test_roster_arithmetic_mismatch_cannot_prove():
    # One rostered player is in NEITHER list: union != roster, so the
    # inactive list's completeness is exactly what cannot be shown.
    claim = _claim(drop_actives=("chi-active-1",))
    record = _verify(claim)
    assert record["status"] == "UNPROVEN"
    assert "ROSTER_RECONCILIATION_MISMATCH" in record["reasons"]
    _assert_unproven_refusal(_qb(claims=[claim]))


def test_contradictory_second_source_cannot_prove():
    # The actives publication names a "proven inactive" as active:
    # the two enumerations contradict each other.
    claim = _claim(extra_actives=("wr2",))
    record = _verify(claim)
    assert record["status"] == "UNPROVEN"
    assert any(r.startswith("ACTIVES_INACTIVES_OVERLAP")
               for r in record["reasons"])
    _assert_unproven_refusal(_qb(claims=[claim]))


def test_stale_prior_week_report_cannot_prove():
    claim = _claim(published="2026-09-27T15:30:00Z")  # prior Sunday
    record = _verify(claim)
    assert record["status"] == "UNPROVEN"
    assert "OFFICIAL_PUBLICATION_STALE" in record["reasons"]
    assert "ACTIVES_PUBLICATION_STALE" in record["reasons"]
    _assert_unproven_refusal(_qb(claims=[claim]))


def test_named_evidence_outside_proven_set_poisons_proof():
    # The claim reconciles internally, but a loose official row names
    # wr1 inactive while the claim counts wr1 active: the sources
    # disagree about the inactive set, so completeness fails closed
    # for everyone (wr1 himself is positively OUT on the row).
    rows = [{"game_id": GAME_ID, "team": "CHI", "gsis_id": "wr1",
             "status": "INACTIVE",
             "published_at": "2026-10-04T15:30:00Z"}]
    verdict = _qb(claims=[_claim()], rows=rows)
    _assert_unproven_refusal(verdict)
    proof = verdict["inactives_completeness_proof"]
    assert proof["reasons"] == ["NAMED_EVIDENCE_CONTRADICTS_PROOF"]
    assert proof["contradicting_named_ids"] == ["wr1"]


def test_conflicting_dual_proofs_cannot_prove():
    other = _claim(inactives=_complete_ids("CHI", ("rb1",)))
    verdict = _qb(claims=[_claim(), other], snapshots=())
    _assert_unproven_refusal(verdict)
    assert verdict["inactives_completeness_proof"]["reasons"] == [
        "CONFLICTING_PROOF_CLAIMS"]


def test_forged_prebaked_proof_record_is_not_a_claim():
    # A record that merely LOOKS proven, handed in as a claim, and a
    # ``complete`` self-assertion on an otherwise broken claim: the
    # verifier derives status from reconciliation, never reads it.
    forged = {"game_id": GAME_ID, "team": "CHI", "status": "PROVEN",
              "verified_inactive_ids": list(_INACTIVES),
              "inactives_completeness": "VERIFIED_COMPLETE"}
    record = _verify(forged)
    assert record["status"] == "UNPROVEN"
    assert "MISSING_OFFICIAL_INACTIVES" in record["reasons"]
    _assert_unproven_refusal(_qb(claims=[forged], snapshots=()))

    self_asserted = _claim(drop_actives=("chi-active-1",),
                             complete=True)
    assert _verify(self_asserted)["status"] == "UNPROVEN"
    _assert_unproven_refusal(_qb(claims=[self_asserted]))


def test_claim_published_after_cutoff_is_invisible_not_a_proof():
    verdict = _qb(claims=[_claim()], snapshots=(), as_of=PRE_INACTIVES)
    assert verdict["state"] == "PROJECTED_STARTER"
    assert verdict["inactives_completeness"] == "NOT_PUBLISHED"
    assert verdict["inactives_completeness_proof"] is None
    assert verdict["excluded_evidence"] >= 1


def test_malformed_claims_never_raise_and_never_prove():
    for bad in (None, [], "PROVEN", {"game_id": GAME_ID}, 42):
        record = _verify(bad)
        assert record["status"] == "UNPROVEN"
    verdict = _qb(claims=[None, {"status": "PROVEN"}], snapshots=())
    assert verdict["state"] == "PROJECTED_STARTER"
