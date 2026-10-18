"""Schema, availability classes, and fail-closed reason taxonomy for the
NFL participation evidence foundation.

This module is DATA INFRASTRUCTURE ONLY. It defines record types for the
participation archive described in
``phase2_v2_design/participation_data_foundation.md``. It contains no model
code, no pricing logic, and no evaluation logic.

Governing rule (owner, 2026-10-12): a record's event date or publication
claim cannot substitute for proof that its contents were accessible at the
prediction cutoff. Where accessibility timing is inferred from source
cadence rather than a per-record timestamp, the record is classified
conservatively and the basis is named on the record itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = "PARTICIPATION_V1"

# ---------------------------------------------------------------------------
# Signal types (foundation doc sections 2-3 and 6.2)
# ---------------------------------------------------------------------------
SIGNAL_INJURY_DESIGNATION = "INJURY_DESIGNATION"      # S3 final report status
SIGNAL_PRACTICE_STATUS = "PRACTICE_STATUS"            # S4 (restricted)
SIGNAL_ROSTER_STATUS = "ROSTER_STATUS"                # S5 weekly roster / reserve
SIGNAL_DEPTH_CHART = "DEPTH_CHART"                    # S6 (restricted, QB rows)
SIGNAL_SNAP_ACTUAL = "SNAP_ACTUAL"                    # S2/S9 post-game actuals
SIGNAL_STARTER_ACTUAL = "STARTER_ACTUAL"              # S1 derived starter identity
SIGNAL_INACTIVE = "INACTIVE"                          # S7 forward-capture only
SIGNAL_REPORT_REVISION = "REPORT_REVISION"            # S8 forward-capture only

ALL_SIGNALS = (
    SIGNAL_INJURY_DESIGNATION,
    SIGNAL_PRACTICE_STATUS,
    SIGNAL_ROSTER_STATUS,
    SIGNAL_DEPTH_CHART,
    SIGNAL_SNAP_ACTUAL,
    SIGNAL_STARTER_ACTUAL,
    SIGNAL_INACTIVE,
    SIGNAL_REPORT_REVISION,
)

#: Signals that have NO honest historical reconstruction (foundation S7/S8).
#: They may exist in the archive only as forward captures whose
#: captured_at_utc is a real capture timestamp at or before the game's
#: kickoff. Any attempt to ingest them as historical/PIT-reconstructible
#: records is a hard validation error.
FORWARD_ONLY_SIGNALS = (SIGNAL_INACTIVE, SIGNAL_REPORT_REVISION)

# ---------------------------------------------------------------------------
# Availability classification (owner's four-way scheme, 2026-10-12)
# ---------------------------------------------------------------------------
#: Records with defensible pregame accessibility under a named rule
#: (final-report rule, prior-week lag rule) -- legitimate historical
#: pregame features where the timing evidence supports it.
AVAIL_HISTORICAL = "AVAILABLE_HISTORICALLY"
#: Post-game actuals. Useful as training targets / validation labels.
#: A record for game G is never a legitimate pregame feature for G.
AVAIL_RETROSPECTIVE = "AVAILABLE_ONLY_RETROSPECTIVELY"
#: No reliable historical availability evidence; capturable only from the
#: day forward capture runs.
AVAIL_FORWARD_ONLY = "FORWARD_CAPTURE_ONLY"
#: Missing, ambiguous, conflicting, or identity-unresolved: fail closed.
AVAIL_UNAVAILABLE = "UNAVAILABLE_OR_AMBIGUOUS"

AVAILABILITY_CLASSES = (
    AVAIL_HISTORICAL,
    AVAIL_RETROSPECTIVE,
    AVAIL_FORWARD_ONLY,
    AVAIL_UNAVAILABLE,
)

# Availability bases: HOW the available_from bound was derived. CADENCE_*
# bases are inferences from league/source cadence, never per-record proof.
BASIS_FINAL_REPORT_RULE = "FINAL_REPORT_RULE_CADENCE_INFERRED"
BASIS_PRIOR_WEEK_LAG = "PRIOR_WEEK_SNAPSHOT_LAG_CADENCE_INFERRED"
BASIS_COMPLETION_WINDOW = "POST_GAME_COMPLETION_WINDOW_SAFEGUARD"
BASIS_CAPTURE_TIMESTAMP = "FORWARD_CAPTURE_TIMESTAMP"
BASIS_NONE = "NO_DEFENSIBLE_BOUND"

TIMING_PER_RECORD = "PER_RECORD_TIMESTAMP"
TIMING_CADENCE = "CADENCE_INFERRED"
TIMING_NONE = "NONE"

# Permitted-use classes (foundation doc section 1)
USE_PREGAME_FEATURE = "PREGAME_FEATURE"
USE_TRAINING_TARGET = "TRAINING_TARGET"
USE_VALIDATION_LABEL = "VALIDATION_LABEL"
USE_EXCLUDED = "EXCLUDED"

# ---------------------------------------------------------------------------
# Fail-closed rejection reason taxonomy
# ---------------------------------------------------------------------------
REJ_MISSING_GSIS_ID = "IDENTITY_UNRESOLVED_MISSING_GSIS_ID"
REJ_MISSING_TEAM_WEEK = "MISSING_TEAM_OR_WEEK"
REJ_SOURCE_FILE_EMPTY = "SOURCE_FILE_EMPTY"
REJ_SCHEMA_COLUMN_MISSING = "SCHEMA_COLUMN_MISSING"
REJ_GAME_BINDING_UNRESOLVED = "GAME_BINDING_UNRESOLVED"
REJ_DUPLICATE_CONFLICTING = "DUPLICATE_CONFLICTING_VALUES"
REJ_SNAPS_SHARE_RANGE = "SNAPS_SANITY_SHARE_OUT_OF_RANGE"
REJ_SNAPS_TEAM_TOTAL = "SNAPS_SANITY_TEAM_TOTAL_IMPLAUSIBLE"
REJ_STARTER_AMBIGUOUS = "STARTER_AMBIGUOUS_TIE"
REJ_FORWARD_ONLY_HISTORICAL = "FORWARD_ONLY_SIGNAL_HISTORICAL_INGEST_REFUSED"
REJ_CAPTURE_AFTER_KICKOFF = "FORWARD_CAPTURE_AFTER_KICKOFF"
REJ_SAME_GAME_SNAPS_FEATURE = "PIT_SAME_GAME_SNAPS_REFUSED_AS_FEATURE"
REJ_NOT_YET_AVAILABLE = "NOT_AVAILABLE_AT_AS_OF_UNDER_LAG_RULE"
REJ_TEAM_WEEK_ABSENT = "TEAM_WEEK_ABSENT_FROM_SOURCE"

DESIGNATIONS = ("Out", "Doubtful", "Questionable")
RESERVE_STATUSES = ("RES", "PUP")  # weekly-roster status codes (coarse bucket)

_GSIS_RE = re.compile(r"^\d{2}-\d{7}$")


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ParticipationRecord:
    """One archived participation observation.

    The archive is append-only: a correction is a NEW record whose
    ``supersedes_record_id`` points at the record it replaces. Records are
    never edited or deleted.
    """

    signal_type: str
    source_signal: str  # S1..S9 label from the foundation doc
    season: int
    week: int | None
    team: str
    captured_at_utc: str  # OUR capture/fetch time (the archive anchor)
    available_from_utc: str | None  # conservative accessibility bound
    availability_class: str
    availability_basis: str
    timing_evidence: str
    permitted_uses: list[str]
    source_name: str
    source_url: str | None = None
    source_published_at_utc: str | None = None  # publisher ts if carried, else None
    source_modified_at_utc: str | None = None  # source bookkeeping ts (UNTRUSTED)
    raw_payload_sha256: str | None = None
    game_id: str | None = None
    kickoff_utc: str | None = None
    gsis_id: str | None = None
    player_name: str | None = None
    position: str | None = None
    payload: dict = field(default_factory=dict)
    record_id: str | None = None  # assigned by the archive on append
    supersedes_record_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "schema_version": self.schema_version,
            "signal_type": self.signal_type,
            "source_signal": self.source_signal,
            "season": self.season,
            "week": self.week,
            "team": self.team,
            "game_id": self.game_id,
            "kickoff_utc": self.kickoff_utc,
            "gsis_id": self.gsis_id,
            "player_name": self.player_name,
            "position": self.position,
            "payload": self.payload,
            "captured_at_utc": self.captured_at_utc,
            "available_from_utc": self.available_from_utc,
            "availability_class": self.availability_class,
            "availability_basis": self.availability_basis,
            "timing_evidence": self.timing_evidence,
            "permitted_uses": list(self.permitted_uses),
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_published_at_utc": self.source_published_at_utc,
            "source_modified_at_utc": self.source_modified_at_utc,
            "raw_payload_sha256": self.raw_payload_sha256,
            "supersedes_record_id": self.supersedes_record_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ParticipationRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


class RecordValidationError(ValueError):
    """Raised when a record violates the foundation's honesty rules."""


def validate_record(rec: ParticipationRecord) -> None:
    """Fail-closed schema validation. Raises RecordValidationError."""
    if rec.signal_type not in ALL_SIGNALS:
        raise RecordValidationError(f"unknown signal_type {rec.signal_type!r}")
    if rec.availability_class not in AVAILABILITY_CLASSES:
        raise RecordValidationError(
            f"unknown availability_class {rec.availability_class!r}"
        )
    if not rec.team:
        raise RecordValidationError(REJ_MISSING_TEAM_WEEK)
    if rec.captured_at_utc is None or _parse_ts(rec.captured_at_utc) is None:
        raise RecordValidationError("captured_at_utc missing or unparseable")
    if rec.gsis_id is not None and not _GSIS_RE.match(str(rec.gsis_id)):
        raise RecordValidationError(REJ_MISSING_GSIS_ID)

    if rec.signal_type in FORWARD_ONLY_SIGNALS:
        # S7/S8: forward capture only. Never historical, never retrospective.
        if rec.availability_class != AVAIL_FORWARD_ONLY:
            raise RecordValidationError(REJ_FORWARD_ONLY_HISTORICAL)
        if rec.availability_basis != BASIS_CAPTURE_TIMESTAMP:
            raise RecordValidationError(REJ_FORWARD_ONLY_HISTORICAL)
        if not rec.game_id or not rec.kickoff_utc:
            raise RecordValidationError("FORWARD_CAPTURE_REQUIRES_GAME_AND_KICKOFF")
        captured = _parse_ts(rec.captured_at_utc)
        kickoff = _parse_ts(rec.kickoff_utc)
        if kickoff is None or captured >= kickoff:
            raise RecordValidationError(REJ_CAPTURE_AFTER_KICKOFF)
        # The capture timestamp IS the availability bound for these signals.
        if rec.available_from_utc != rec.captured_at_utc:
            raise RecordValidationError(
                "forward-capture records must set available_from_utc == captured_at_utc"
            )

    if rec.signal_type in (SIGNAL_SNAP_ACTUAL, SIGNAL_STARTER_ACTUAL):
        # Post-game actuals: retrospective only, never own-game features.
        if rec.availability_class != AVAIL_RETROSPECTIVE:
            raise RecordValidationError(
                "snap/starter actuals must be AVAILABLE_ONLY_RETROSPECTIVELY"
            )
        if USE_PREGAME_FEATURE in rec.permitted_uses:
            raise RecordValidationError(
                "snap/starter actual records may not claim PREGAME_FEATURE use; "
                "later-game feature use is a reader-level derivation under the "
                "completion rule, not a property of this record"
            )
        if rec.available_from_utc is None:
            raise RecordValidationError(
                "snap/starter actuals require a completion-window bound"
            )

    if rec.availability_class == AVAIL_HISTORICAL:
        if rec.available_from_utc is None:
            raise RecordValidationError(
                "AVAILABLE_HISTORICALLY requires a defensible available_from_utc bound"
            )
        if rec.timing_evidence == TIMING_NONE:
            raise RecordValidationError(
                "AVAILABLE_HISTORICALLY requires named timing evidence"
            )
