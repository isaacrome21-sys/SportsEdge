"""NFL participation receipts: kickoff starters are not snap leaders.

An owner-format receipt specialization (see ``receipt_format.py``)
for NFL participation evidence. It encodes, at the type level, the
Item E/F lesson of October 12, 2026: the foundation's "starter"
field was the player with the most offensive snaps, and that is
**not** the kickoff starter (Bridgewater 2019 W2, Minshew 2019 W1
were mislabeled by that construction; the games.csv QB field
proved to be a stale, block-updated designation). Snap counts are
post-game facts about usage; a kickoff starter is a fact about the
opening play, established by lineage evidence. The two must never
be populated from each other.

Record types are therefore **distinct constructors with disjoint
required fields**, and validation enforces the separation both
ways:

- ``kickoff_starter_record(...)`` — requires an evidence source
  class from the confirmed set (``GAMEBOOK``,
  ``BOXSCORE_STARTER_RECORD``, ``GAME_ACCOUNT`` — the Item F
  corroboration hierarchy) plus an evidence reference. A record
  whose evidence class is ``ANNOUNCED`` is rejected here: a
  pregame announcement establishes the **announced** starter
  only, never confirmed participation (Item F errata).
- ``announced_starter_record(...)`` — announcement evidence,
  stored in its own list, its records labeled
  ``participation_status: "ANNOUNCED"`` forever; an announced
  record can never validate inside the starters list.
- ``snap_leader_record(...)`` — post-game snap facts (snaps /
  snap share). The constructor emits **no** evidence-class field
  at all; a snap-leader record that claims a starter evidence
  class fails validation, and copying snap-leader records into
  ``kickoff_starters`` fails on both the record-kind check and
  the missing starter evidence.

Validation also binds every record's team to one of the fixture's
two teams, and derives the envelope's ``participants`` from the
three lists with role tags, so identity flows from the section
that attests it.

Honesty contract: this module attests evidence lineage only. It
does not decide who started, promote any label, or feed any model
— the starter-reference rule remains a proposal pending the
owner's ratification, and PR #2084 remains under its audit hold.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import receipt_format as rf

PARTICIPATION_RECEIPT_SCHEMA = "NFL_PARTICIPATION_RECEIPT_V1"
EXTENSION_KEY = "participation"

# Item F corroboration hierarchy: the source classes that can
# CONFIRM a kickoff starter. Announcements are not corroboration.
CONFIRMED_STARTER_SOURCE_CLASSES = frozenset({
    "GAMEBOOK", "BOXSCORE_STARTER_RECORD", "GAME_ACCOUNT"})
ANNOUNCEMENT_SOURCE_CLASS = "ANNOUNCED"

KIND_KICKOFF_STARTER = "KICKOFF_STARTER"
KIND_ANNOUNCED_STARTER = "ANNOUNCED_STARTER"
KIND_SNAP_LEADER = "SNAP_LEADER"


class ParticipationReceiptError(rf.OwnerReceiptError):
    pass


def _require_text(value, code):
    if not isinstance(value, str) or not value.strip():
        raise ParticipationReceiptError(code)
    return value


def kickoff_starter_record(player_id, team_id, position, *,
                           evidence_source_class, evidence_ref):
    """One CONFIRMED kickoff starter, with its lineage evidence.

    ``evidence_source_class`` must be a confirming class
    (GAMEBOOK / BOXSCORE_STARTER_RECORD / GAME_ACCOUNT).
    ANNOUNCED is refused at construction: an announcement names
    an announced starter, not a confirmed participant.
    """
    if evidence_source_class == ANNOUNCEMENT_SOURCE_CLASS:
        raise ParticipationReceiptError(
            "PARTICIPATION_ANNOUNCED_NOT_A_STARTER_SOURCE: a "
            "pregame announcement establishes the ANNOUNCED starter "
            "only; use announced_starter_record and keep it out of "
            "kickoff_starters")
    if evidence_source_class not in CONFIRMED_STARTER_SOURCE_CLASSES:
        raise ParticipationReceiptError(
            "PARTICIPATION_STARTER_SOURCE_CLASS_INVALID:"
            + str(evidence_source_class))
    return {
        "record_kind": KIND_KICKOFF_STARTER,
        "player_id": _require_text(
            player_id, "PARTICIPATION_PLAYER_ID_MISSING"),
        "team_id": _require_text(
            team_id, "PARTICIPATION_TEAM_ID_MISSING"),
        "position": _require_text(
            position, "PARTICIPATION_POSITION_MISSING"),
        "evidence_source_class": evidence_source_class,
        "evidence_ref": _require_text(
            evidence_ref, "PARTICIPATION_STARTER_EVIDENCE_REF_MISSING"),
        "participation_status": "CONFIRMED_KICKOFF_STARTER",
    }


def announced_starter_record(player_id, team_id, position, *,
                             evidence_ref):
    """One ANNOUNCED starter: announcement evidence, labeled as
    such. Never a confirmed participant."""
    return {
        "record_kind": KIND_ANNOUNCED_STARTER,
        "player_id": _require_text(
            player_id, "PARTICIPATION_PLAYER_ID_MISSING"),
        "team_id": _require_text(
            team_id, "PARTICIPATION_TEAM_ID_MISSING"),
        "position": _require_text(
            position, "PARTICIPATION_POSITION_MISSING"),
        "evidence_source_class": ANNOUNCEMENT_SOURCE_CLASS,
        "evidence_ref": _require_text(
            evidence_ref, "PARTICIPATION_ANNOUNCEMENT_REF_MISSING"),
        "participation_status": "ANNOUNCED",
    }


def snap_leader_record(player_id, team_id, *, snaps, snap_share=None):
    """One post-game snap fact. Carries NO starter-evidence fields
    by construction — there is nothing here a starter claim could
    be copied from."""
    if isinstance(snaps, bool) or not isinstance(snaps, int) \
            or snaps < 0:
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAPS_INVALID:" + str(snaps))
    record = {
        "record_kind": KIND_SNAP_LEADER,
        "player_id": _require_text(
            player_id, "PARTICIPATION_PLAYER_ID_MISSING"),
        "team_id": _require_text(
            team_id, "PARTICIPATION_TEAM_ID_MISSING"),
        "snaps": snaps,
    }
    if snap_share is not None:
        share = float(snap_share)
        if not 0.0 <= share <= 1.0:
            raise ParticipationReceiptError(
                "PARTICIPATION_SNAP_SHARE_INVALID:" + str(snap_share))
        record["snap_share"] = share
    return record


def _participants_for(section):
    """Envelope participants, derived from the section that
    attests each identity (starters, announced, snap leaders)."""
    participants = []
    seen = set()
    for role, key in (("KICKOFF_STARTER", "kickoff_starters"),
                      ("ANNOUNCED_STARTER", "announced_starters"),
                      ("SNAP_LEADER", "snap_leaders")):
        for record in section.get(key) or []:
            pid = record.get("player_id")
            if (pid, role) in seen:
                continue
            seen.add((pid, role))
            participants.append({"participant_id": pid, "role": role})
    return participants


def build_participation_receipt(raw_payload, *, fixture_id,
                                home_team_id, away_team_id,
                                kickoff_utc, kickoff_starters,
                                snap_leaders, announced_starters=None,
                                observed_at, effective_at,
                                effective_at_basis,
                                effective_at_basis_field=None,
                                provenance, corrections=None,
                                now=None):
    """Assemble a participation owner receipt (envelope + section).

    ``raw_payload`` is the immutable source payload bytes the
    section's claims rest on (e.g. the archived gamebook extract
    or roster/snap payload), hash-bound by the envelope.
    """
    section = {
        "participation_schema": PARTICIPATION_RECEIPT_SCHEMA,
        "fixture_id": fixture_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "kickoff_utc": kickoff_utc,
        "kickoff_starters": [dict(r) for r in kickoff_starters],
        "announced_starters": [dict(r)
                                for r in (announced_starters or [])],
        "snap_leaders": [dict(r) for r in snap_leaders],
    }
    envelope = rf.build_owner_receipt(
        raw_payload, fixture_id=fixture_id,
        participants=_participants_for(section),
        observed_at=observed_at, effective_at=effective_at,
        effective_at_basis=effective_at_basis,
        effective_at_basis_field=effective_at_basis_field,
        provenance=provenance, corrections=corrections,
        extensions={EXTENSION_KEY: section}, now=now)
    return validate_participation_receipt(envelope)


def participation_section(envelope):
    section = (envelope.get("extensions") or {}).get(EXTENSION_KEY)
    if not isinstance(section, dict):
        raise ParticipationReceiptError(
            "PARTICIPATION_SECTION_MISSING")
    return section


def _check_team(record, teams):
    if record.get("team_id") not in teams:
        raise ParticipationReceiptError(
            "PARTICIPATION_TEAM_NOT_IN_FIXTURE:"
            + str(record.get("team_id")))


def _validate_starter(record, teams):
    if not isinstance(record, dict):
        raise ParticipationReceiptError(
            "PARTICIPATION_STARTER_NOT_AN_OBJECT")
    if record.get("record_kind") == KIND_SNAP_LEADER:
        # The Item E/F defect, named: a snap leader in the starter
        # field is a mislabel, whatever its evidence fields claim.
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAP_LEADER_AS_STARTER: snap leadership "
            "is a post-game usage fact, not kickoff-starter "
            "evidence")
    if record.get("record_kind") != KIND_KICKOFF_STARTER:
        raise ParticipationReceiptError(
            "PARTICIPATION_STARTER_KIND_INVALID:"
            + str(record.get("record_kind")))
    source_class = record.get("evidence_source_class")
    if source_class is None:
        raise ParticipationReceiptError(
            "PARTICIPATION_STARTER_EVIDENCE_MISSING: a kickoff "
            "starter requires lineage evidence (source class + "
            "reference); snap counts are not evidence of starting")
    if source_class == ANNOUNCEMENT_SOURCE_CLASS:
        raise ParticipationReceiptError(
            "PARTICIPATION_ANNOUNCEMENT_NOT_CONFIRMED_STARTER: "
            "announcement evidence labels the ANNOUNCED starter "
            "only and cannot populate kickoff_starters")
    if source_class not in CONFIRMED_STARTER_SOURCE_CLASSES:
        raise ParticipationReceiptError(
            "PARTICIPATION_STARTER_SOURCE_CLASS_INVALID:"
            + str(source_class))
    _require_text(record.get("evidence_ref"),
                  "PARTICIPATION_STARTER_EVIDENCE_REF_MISSING")
    _require_text(record.get("player_id"),
                  "PARTICIPATION_PLAYER_ID_MISSING")
    _check_team(record, teams)


def _validate_announced(record, teams):
    if not isinstance(record, dict):
        raise ParticipationReceiptError(
            "PARTICIPATION_ANNOUNCED_NOT_AN_OBJECT")
    if record.get("record_kind") != KIND_ANNOUNCED_STARTER:
        raise ParticipationReceiptError(
            "PARTICIPATION_ANNOUNCED_KIND_INVALID:"
            + str(record.get("record_kind")))
    if record.get("evidence_source_class") != \
            ANNOUNCEMENT_SOURCE_CLASS:
        raise ParticipationReceiptError(
            "PARTICIPATION_ANNOUNCED_CLASS_INVALID:"
            + str(record.get("evidence_source_class")))
    if record.get("participation_status") != "ANNOUNCED":
        raise ParticipationReceiptError(
            "PARTICIPATION_ANNOUNCED_STATUS_INVALID: announcement "
            "evidence must stay labeled ANNOUNCED")
    _require_text(record.get("player_id"),
                  "PARTICIPATION_PLAYER_ID_MISSING")
    _check_team(record, teams)


def _validate_snap_leader(record, teams):
    if not isinstance(record, dict):
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAP_LEADER_NOT_AN_OBJECT")
    if record.get("record_kind") != KIND_SNAP_LEADER:
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAP_LEADER_KIND_INVALID:"
            + str(record.get("record_kind")))
    if "evidence_source_class" in record \
            or "evidence_ref" in record:
        # A snap fact claiming starter lineage is the same
        # mislabel from the other direction.
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAP_LEADER_CLAIMS_STARTER_EVIDENCE: "
            "snap records carry usage facts only")
    snaps = record.get("snaps")
    if isinstance(snaps, bool) or not isinstance(snaps, int) \
            or snaps < 0:
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAPS_INVALID:" + str(snaps))
    _require_text(record.get("player_id"),
                  "PARTICIPATION_PLAYER_ID_MISSING")
    _check_team(record, teams)


def validate_participation_receipt(envelope):
    """Owner validation + the participation separation rules."""
    rf.validate_owner_receipt(envelope)
    section = participation_section(envelope)
    if section.get("participation_schema") != \
            PARTICIPATION_RECEIPT_SCHEMA:
        raise ParticipationReceiptError(
            "PARTICIPATION_SCHEMA_MISMATCH:"
            + str(section.get("participation_schema")))
    if section.get("fixture_id") != envelope.get("fixture_id"):
        raise ParticipationReceiptError(
            "PARTICIPATION_FIXTURE_MISMATCH")
    teams = {section.get("home_team_id"), section.get("away_team_id")}
    if None in teams or "" in teams:
        raise ParticipationReceiptError(
            "PARTICIPATION_FIXTURE_TEAMS_MISSING")
    starters = section.get("kickoff_starters")
    if not isinstance(starters, list) or not starters:
        raise ParticipationReceiptError(
            "PARTICIPATION_KICKOFF_STARTERS_MISSING")
    for record in starters:
        _validate_starter(record, teams)
    for record in section.get("announced_starters") or []:
        _validate_announced(record, teams)
    leaders = section.get("snap_leaders")
    if not isinstance(leaders, list):
        raise ParticipationReceiptError(
            "PARTICIPATION_SNAP_LEADERS_INVALID")
    for record in leaders:
        _validate_snap_leader(record, teams)
    # Participants must be exactly what the section attests: an
    # identity smuggled into the envelope header that no section
    # record supports is an unattested participant.
    derived = {(p["participant_id"], p["role"])
               for p in _participants_for(section)}
    claimed = {(p.get("participant_id"), p.get("role"))
               for p in envelope.get("participants") or []}
    if derived != claimed:
        raise ParticipationReceiptError(
            "PARTICIPATION_PARTICIPANTS_MISMATCH: envelope "
            "participants must be derived from the participation "
            "section, record for record")
    return envelope


def kickoff_utc_of(envelope):
    """The fixture's kickoff instant (section field, parsed)."""
    section = participation_section(envelope)
    stamp = datetime.fromisoformat(
        str(section["kickoff_utc"]).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ParticipationReceiptError(
            "PARTICIPATION_KICKOFF_NOT_UTC_AWARE")
    return stamp.astimezone(timezone.utc)
