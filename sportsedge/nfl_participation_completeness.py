"""Independently verifiable completeness proof for NFL inactive lists.

Implements the specification in
``research/nfl_participation_completeness/SPEC.md`` (the PR #2274
owner ruling, pinned by the PR #2363 RED battery): a row count is not
completeness, and neither is a caller-asserted ``complete`` flag or a
content digest.  An official inactive list is provably complete only
when three independently sourced enumerations reconcile exactly:

* the official game-day inactive report (an official source kind),
* the team's full game-day-eligible roster enumeration (a second
  source, current for this game),
* the game-day actives publication (a third source),

with ``inactives`` and ``actives`` disjoint and their union equal to
the roster enumeration.  Only then does the participation bridge
permit the negative inference "not listed => dressed".

Every claim carries source identity and publication timestamps (the
Oct 13 source-verification rule: no source is ever the only source,
and missing or conflicting evidence stays unverified).  The verifier
never raises on malformed evidence and never accepts an assertion of
completeness: it returns a proof record whose ``status`` is
``PROVEN`` or ``UNPROVEN`` with named reasons, so consumers fail
closed and a re-audit can inspect exactly what was checked.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

PROOF_SCHEMA = "NFL_INACTIVES_COMPLETENESS_PROOF_V1"
CLAIM_SCHEMA = "NFL_INACTIVES_COMPLETENESS_CLAIM_V1"

# Source kinds accepted for the official game-day inactive report.
OFFICIAL_SOURCE_KINDS = frozenset({"LEAGUE_OFFICIAL", "TEAM_OFFICIAL"})

# Sanity floors.  Real game-day publications are never tiny; these are
# plausibility bounds checked INSIDE a proof.  A floor alone proves
# nothing -- the rejected shortcut was a floor (5 rows) used AS the
# proof, and this module exists to replace that use.
MIN_OFFICIAL_INACTIVES = 5
MIN_ROSTER_ENUMERATION = 40
MIN_ACTIVES_PUBLICATION = 40

# Game-day publications (official inactives, actives) land shortly
# before kickoff.  A list published outside this window before kickoff
# is not this game's game-day publication (a prior game's list cannot
# be re-bound to this fixture).
GAMEDAY_PUBLICATION_MAX_LEAD_HOURS = 24.0
# The roster enumeration must be current: rosters churn weekly, so an
# enumeration older than this at kickoff cannot reconcile this game.
ROSTER_ENUMERATION_MAX_AGE_HOURS = 8.0 * 24.0

_PARTS = (
    ("official_inactives", "OFFICIAL"),
    ("roster", "ROSTER"),
    ("actives", "ACTIVES"),
)


def _parse_time(value: Any) -> datetime | None:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if out.tzinfo is None or out.utcoffset() is None:
        return None
    return out.astimezone(timezone.utc)


def _id_set(part: Mapping[str, Any]) -> set[str] | None:
    ids = part.get("player_ids")
    if not isinstance(ids, (list, tuple)):
        return None
    out = [str(v).strip() for v in ids]
    if any(not v for v in out) or len(set(out)) != len(out):
        return None
    return set(out)


def _proof_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_inactives_completeness(
    claim: Any,
    *,
    kickoff: datetime,
    cutoff: datetime,
) -> dict[str, Any]:
    """Verify one completeness claim for one (game, team).

    ``claim`` is a mapping with ``game_id`` / ``team`` and the three
    parts ``official_inactives`` / ``roster`` / ``actives``, each a
    mapping with ``source_id``, ``source_kind``, ``published_at`` (the
    roster part may use ``as_of``) and ``player_ids``.  Returns the
    proof record described in the SPEC; ``record["visible"]`` is
    False when any part is published after ``cutoff`` (the claim is
    invisible at that cutoff, not merely unproven).
    """
    record: dict[str, Any] = {
        "schema": PROOF_SCHEMA,
        "status": "UNPROVEN",
        "game_id": None,
        "team": None,
        "visible": True,
        "reasons": [],
        "verified_inactive_ids": None,
        "counts": None,
        "sources": [],
        "proof_sha256": None,
        "refusal": None,
    }
    reasons: list[str] = record["reasons"]
    if not isinstance(claim, Mapping):
        reasons.append("CLAIM_MALFORMED")
        record["refusal"] = "INACTIVES_COMPLETENESS_UNPROVEN:CLAIM_MALFORMED"
        return record
    record["game_id"] = claim.get("game_id")
    record["team"] = claim.get("team")

    parts: dict[str, dict[str, Any]] = {}
    for key, role in _PARTS:
        raw = claim.get(key)
        if not isinstance(raw, Mapping):
            reasons.append(f"MISSING_{key.upper()}")
            continue
        source_id = str(raw.get("source_id") or "").strip()
        if not source_id:
            reasons.append(f"SOURCE_ID_MISSING:{role}")
        published = _parse_time(
            raw.get("published_at", raw.get("as_of")))
        if published is None:
            reasons.append(f"TIMESTAMP_INVALID:{role}")
        ids = _id_set(raw)
        if ids is None:
            reasons.append(f"ID_LIST_INVALID:{role}")
        parts[role] = {
            "key": key,
            "source_id": source_id,
            "source_kind": str(raw.get("source_kind") or "").strip().upper(),
            "published": published,
            "ids": ids,
        }
        record["sources"].append({
            "role": role,
            "source_id": source_id or None,
            "source_kind": str(raw.get("source_kind") or "").strip().upper()
            or None,
            "published_at": published.isoformat() if published else None,
        })

    # Point-in-time discipline: a claim with any part after the cutoff
    # is invisible at that cutoff (excluded evidence), never a proof
    # and never a contradiction.
    for role in ("OFFICIAL", "ROSTER", "ACTIVES"):
        part = parts.get(role)
        if part and part["published"] is not None and \
                part["published"] > cutoff:
            record["visible"] = False
            reasons.append(f"EVIDENCE_AFTER_CUTOFF:{role}")
    if not record["visible"]:
        record["refusal"] = \
            "INACTIVES_COMPLETENESS_UNPROVEN:EVIDENCE_AFTER_CUTOFF"
        return record

    official = parts.get("OFFICIAL")
    roster = parts.get("ROSTER")
    actives = parts.get("ACTIVES")

    if official is not None and official["source_kind"] not in \
            OFFICIAL_SOURCE_KINDS:
        reasons.append("OFFICIAL_SOURCE_KIND_UNRECOGNIZED")

    # Source independence: no enumeration may share a source identity
    # with another; a single source is never the only source.
    present = [p for p in (official, roster, actives) if p is not None]
    for i, first in enumerate(present):
        for second in present[i + 1:]:
            if first["source_id"] and \
                    first["source_id"] == second["source_id"]:
                reasons.append(
                    "SOURCE_NOT_INDEPENDENT:"
                    f"{first['key']}:{second['key']}")

    # Game-day timing windows.
    def _lead_hours(part):
        return (kickoff - part["published"]).total_seconds() / 3600.0

    if official is not None and official["published"] is not None:
        lead = _lead_hours(official)
        if lead < 0.0:
            reasons.append("OFFICIAL_PUBLISHED_AFTER_KICKOFF")
        elif lead > GAMEDAY_PUBLICATION_MAX_LEAD_HOURS:
            reasons.append("OFFICIAL_PUBLICATION_STALE")
    if actives is not None and actives["published"] is not None:
        lead = _lead_hours(actives)
        if lead < 0.0:
            reasons.append("ACTIVES_PUBLISHED_AFTER_KICKOFF")
        elif lead > GAMEDAY_PUBLICATION_MAX_LEAD_HOURS:
            reasons.append("ACTIVES_PUBLICATION_STALE")
    if roster is not None and roster["published"] is not None:
        age = _lead_hours(roster)
        if age < 0.0:
            reasons.append("ROSTER_ENUMERATION_AFTER_KICKOFF")
        elif age > ROSTER_ENUMERATION_MAX_AGE_HOURS:
            reasons.append("ROSTER_ENUMERATION_STALE")

    # Sanity floors (inside the proof; never the proof itself).
    if official is not None and official["ids"] is not None and \
            len(official["ids"]) < MIN_OFFICIAL_INACTIVES:
        reasons.append("OFFICIAL_LIST_BELOW_SANITY_FLOOR")
    if roster is not None and roster["ids"] is not None and \
            len(roster["ids"]) < MIN_ROSTER_ENUMERATION:
        reasons.append("ROSTER_ENUMERATION_BELOW_SANITY_FLOOR")
    if actives is not None and actives["ids"] is not None and \
            len(actives["ids"]) < MIN_ACTIVES_PUBLICATION:
        reasons.append("ACTIVES_BELOW_SANITY_FLOOR")

    # Roster arithmetic: the reconciliation itself.
    if all(p is not None and p["ids"] is not None
           for p in (official, roster, actives)):
        inactives = official["ids"]  # type: ignore[union-attr]
        roster_ids = roster["ids"]  # type: ignore[union-attr]
        active_ids = actives["ids"]  # type: ignore[union-attr]
        record["counts"] = {
            "roster": len(roster_ids),
            "actives": len(active_ids),
            "inactives": len(inactives),
        }
        overlap = inactives & active_ids
        if overlap:
            reasons.append(
                f"ACTIVES_INACTIVES_OVERLAP:{len(overlap)}")
        if (inactives | active_ids) != roster_ids:
            reasons.append("ROSTER_RECONCILIATION_MISMATCH")

    if reasons:
        record["refusal"] = \
            f"INACTIVES_COMPLETENESS_UNPROVEN:{reasons[0]}"
        return record

    verified = sorted(official["ids"])  # type: ignore[union-attr]
    record["status"] = "PROVEN"
    record["verified_inactive_ids"] = verified
    record["proof_sha256"] = _proof_hash({
        "schema": PROOF_SCHEMA,
        "game_id": record["game_id"],
        "team": record["team"],
        "verified_inactive_ids": verified,
        "counts": record["counts"],
        "sources": record["sources"],
    })
    return record


__all__ = [
    "CLAIM_SCHEMA",
    "GAMEDAY_PUBLICATION_MAX_LEAD_HOURS",
    "MIN_ACTIVES_PUBLICATION",
    "MIN_OFFICIAL_INACTIVES",
    "MIN_ROSTER_ENUMERATION",
    "OFFICIAL_SOURCE_KINDS",
    "PROOF_SCHEMA",
    "ROSTER_ENUMERATION_MAX_AGE_HOURS",
    "verify_inactives_completeness",
]
