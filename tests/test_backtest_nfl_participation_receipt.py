"""Offline contracts for NFL participation receipts.

The Item E/F lesson (Oct 12 2026): a snap leader is not a kickoff
starter, and an announcement is not participation. These tests
prove the type-level separation in
sportsedge/backtest/nfl_participation_receipt.py:

  * kickoff_starters require lineage evidence from a confirming
    source class (GAMEBOOK / BOXSCORE_STARTER_RECORD /
    GAME_ACCOUNT) — a record without it is invalid;
  * snap-leader records copied into kickoff_starters fail, by
    kind and by missing evidence, whichever is checked first;
  * announcement evidence is refused as a starter source at
    construction, is invalid inside kickoff_starters however it
    is built, and lives — labeled ANNOUNCED — only in its own
    list;
  * a snap record claiming starter evidence fails from the other
    direction;
  * every record's team must belong to the fixture, and the
    envelope's participants must be exactly what the section
    attests.

Nothing here decides who actually started any game; the starter-
reference rule is still a proposal and PR #2084 is still held.
"""
import copy
import json

import pytest

from sportsedge.backtest import nfl_participation_receipt as pr
from sportsedge.backtest import receipt_format as rf

GAMEBOOK_URL = ("https://static.www.nfl.com/image/upload/"
                "v1733744097/gamecenter/"
                "45c14486-1313-11ef-afd1-646009f18b2e.pdf")
SOURCE_STAMP = "2024-12-08T21:00:00Z"
OBSERVED = "2024-12-09T02:00:00Z"


def make_payload():
    return json.dumps({
        "gamebook": "CAR@PHI 2024 W14 official gamebook extract",
        "source_timestamp_utc": SOURCE_STAMP,
    }, sort_keys=True).encode("utf-8")


def starter(player="player:young-b", team="CAR", **kw):
    return pr.kickoff_starter_record(
        player, team, "QB",
        evidence_source_class=kw.get("evidence_source_class",
                                     "GAMEBOOK"),
        evidence_ref=kw.get("evidence_ref", GAMEBOOK_URL))


def leader(player="player:young-b", team="CAR", snaps=62):
    return pr.snap_leader_record(player, team, snaps=snaps,
                                 snap_share=0.98)


def build(starters=None, leaders=None, announced=None, **overrides):
    kwargs = {
        "fixture_id": "nfl:2024-14:CAR:PHI",
        "home_team_id": "PHI", "away_team_id": "CAR",
        "kickoff_utc": "2024-12-08T18:00:00Z",
        "kickoff_starters": (
            starters if starters is not None else [starter()]),
        "snap_leaders": (
            leaders if leaders is not None else [leader()]),
        "announced_starters": announced or [],
        "observed_at": OBSERVED,
        "effective_at": SOURCE_STAMP,
        "effective_at_basis": rf.BASIS_SOURCE_TIMESTAMP,
        "effective_at_basis_field": "source_timestamp_utc",
        "provenance": {"source_name": "NFL_GAMEBOOK",
                       "retrieval_path": "static.www.nfl.com "
                                         "gamecenter (archived)"},
    }
    kwargs.update(overrides)
    return pr.build_participation_receipt(make_payload(), **kwargs)


def test_valid_participation_receipt_builds():
    env = build(announced=[
        pr.announced_starter_record(
            "player:dalton-a", "CAR", "QB",
            evidence_ref="team announcement, 2024-12-04")])
    section = pr.participation_section(env)
    assert section["kickoff_starters"][0][
        "participation_status"] == "CONFIRMED_KICKOFF_STARTER"
    assert section["announced_starters"][0][
        "participation_status"] == "ANNOUNCED"
    roles = {(p["participant_id"], p["role"])
             for p in env["participants"]}
    assert ("player:young-b", "KICKOFF_STARTER") in roles
    assert ("player:young-b", "SNAP_LEADER") in roles
    assert ("player:dalton-a", "ANNOUNCED_STARTER") in roles
    assert pr.validate_participation_receipt(env) is env


def test_announcement_refused_as_starter_source_at_construction():
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        pr.kickoff_starter_record(
            "player:x", "CAR", "QB",
            evidence_source_class="ANNOUNCED",
            evidence_ref="press conference")
    assert "PARTICIPATION_ANNOUNCED_NOT_A_STARTER_SOURCE" in \
        str(excinfo.value)


def test_snap_leader_copied_into_starters_fails():
    """The Item E/F defect itself: the snap leader IS the player
    with the most snaps — copying that record into the starter
    field must fail validation, not merely look odd."""
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(starters=[leader()])
    assert "PARTICIPATION_SNAP_LEADER_AS_STARTER" in \
        str(excinfo.value)


def test_starter_without_lineage_evidence_fails():
    bare = {"record_kind": "KICKOFF_STARTER",
            "player_id": "player:young-b", "team_id": "CAR",
            "position": "QB"}
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(starters=[bare])
    assert "PARTICIPATION_STARTER_EVIDENCE_MISSING" in \
        str(excinfo.value)


def test_announced_record_inside_starters_fails_however_built():
    hand_built = {
        "record_kind": "KICKOFF_STARTER",
        "player_id": "player:young-b", "team_id": "CAR",
        "position": "QB", "evidence_source_class": "ANNOUNCED",
        "evidence_ref": "coach press conference",
        "participation_status": "CONFIRMED_KICKOFF_STARTER",
    }
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(starters=[hand_built])
    assert "PARTICIPATION_ANNOUNCEMENT_NOT_CONFIRMED_STARTER" in \
        str(excinfo.value)


def test_snap_leader_claiming_starter_evidence_fails():
    forged = leader()
    forged["evidence_source_class"] = "GAMEBOOK"
    forged["evidence_ref"] = GAMEBOOK_URL
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(leaders=[forged])
    assert "PARTICIPATION_SNAP_LEADER_CLAIMS_STARTER_EVIDENCE" in \
        str(excinfo.value)


def test_confirmed_classes_accepted_announced_stays_labeled():
    for source_class in ("GAMEBOOK", "BOXSCORE_STARTER_RECORD",
                         "GAME_ACCOUNT"):
        env = build(starters=[starter(
            evidence_source_class=source_class)])
        assert pr.participation_section(env)["kickoff_starters"][0][
            "evidence_source_class"] == source_class
    # An announced record whose label is upgraded after the fact
    # is invalid: ANNOUNCED is terminal, not a draft of CONFIRMED.
    announced = pr.announced_starter_record(
        "player:dalton-a", "CAR", "QB", evidence_ref="team release")
    announced["participation_status"] = "CONFIRMED_KICKOFF_STARTER"
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(announced=[announced])
    assert "PARTICIPATION_ANNOUNCED_STATUS_INVALID" in \
        str(excinfo.value)


def test_team_must_belong_to_fixture():
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(starters=[starter(team="DAL")])
    assert "PARTICIPATION_TEAM_NOT_IN_FIXTURE" in str(excinfo.value)
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(leaders=[leader(team="DAL")])
    assert "PARTICIPATION_TEAM_NOT_IN_FIXTURE" in str(excinfo.value)


def test_starters_required_and_participants_must_match_section():
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        build(starters=[])
    assert "PARTICIPATION_KICKOFF_STARTERS_MISSING" in \
        str(excinfo.value)
    # An envelope whose header claims a participant no section
    # record attests: owner-valid on its own, participation-invalid.
    section = {
        "participation_schema": pr.PARTICIPATION_RECEIPT_SCHEMA,
        "fixture_id": "nfl:2024-14:CAR:PHI",
        "home_team_id": "PHI", "away_team_id": "CAR",
        "kickoff_utc": "2024-12-08T18:00:00Z",
        "kickoff_starters": [starter()],
        "announced_starters": [],
        "snap_leaders": [leader()],
    }
    env = rf.build_owner_receipt(
        make_payload(), fixture_id="nfl:2024-14:CAR:PHI",
        participants=[{"participant_id": "player:ghost",
                       "role": "KICKOFF_STARTER"}],
        observed_at=OBSERVED, effective_at=SOURCE_STAMP,
        effective_at_basis=rf.BASIS_SOURCE_TIMESTAMP,
        effective_at_basis_field="source_timestamp_utc",
        provenance={"source_name": "NFL_GAMEBOOK",
                    "retrieval_path": "archived"},
        extensions={pr.EXTENSION_KEY: section})
    with pytest.raises(pr.ParticipationReceiptError) as excinfo:
        pr.validate_participation_receipt(env)
    assert "PARTICIPATION_PARTICIPANTS_MISMATCH" in \
        str(excinfo.value)


def test_section_tamper_breaks_envelope_identity():
    env = build()
    forged = copy.deepcopy(env)
    forged["extensions"]["participation"]["kickoff_starters"][0][
        "evidence_source_class"] = "GAME_ACCOUNT"
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        pr.validate_participation_receipt(forged)
    assert "OWNER_ENVELOPE_ID_MISMATCH" in str(excinfo.value)
