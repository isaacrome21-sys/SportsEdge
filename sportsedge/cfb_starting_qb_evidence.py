"""CFB starting-quarterback evidence for matchup identity.

Research-only. Does not authenticate model promotion, issue PLAY, or
override Illinois-college exclusion. Callers supply dated source rows;
this module normalizes them into a confidence-scored starter record.

Sources (in decreasing verification strength):
  1. Official team athletics site or conference availability report
  2. Press-box / 247Sports team-page depth chart with explicit starter
  3. CFBDepth.com or Ourlads.com two-deep listing
  4. Prior-week starter with no contradicting injury/availability report
  5. Unconfirmed projection or OR-listed depth chart
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "SPORTSEDGE_CFB_STARTING_QB_EVIDENCE_V1"
LANE = "CFB_STARTING_QB_EVIDENCE"

# Evidence strength weights (higher = more verified)
SOURCE_WEIGHTS = {
    "OFFICIAL_TEAM_OR_CONFERENCE": 1.00,
    "PRESS_BOX_OR_247_DEPTH_CHART": 0.85,
    "CFBDEPTH_OR_OURLADS": 0.70,
    "PRIOR_WEEK_STARTER_UNCONTRADICTED": 0.55,
    "PROJECTED_OR_OR_LISTED": 0.25,
    "UNKNOWN": 0.0,
}

CONFIDENCE_LABELS = (
    (0.90, "CONFIRMED"),
    (0.70, "HIGH"),
    (0.50, "MODERATE"),
    (0.25, "LOW"),
    (0.0, "UNKNOWN"),
)


@dataclass(frozen=True)
class StartingQBEvidence:
    schema_version: str
    lane: str
    sport: str
    team: str
    opponent: str | None
    game_id: str | None
    season: int | None
    week: int | None
    starter_name: str | None
    starter_jersey: str | None
    backup_name: str | None
    source: str
    source_url: str | None
    observed_at_utc: str | None
    confidence: float
    confidence_label: str
    notes: str
    illinois_college_team: bool = False
    promotion_authority: bool = False
    play_authority: bool = False


def _aware(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        out = value
    else:
        try:
            out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if out.tzinfo is None:
        return None
    return out.astimezone(timezone.utc)


def _label(confidence: float) -> str:
    for threshold, label in CONFIDENCE_LABELS:
        if confidence >= threshold:
            return label
    return "UNKNOWN"


def score_starting_qb(
    *,
    team: str,
    source: str,
    starter_name: str | None = None,
    starter_jersey: str | None = None,
    backup_name: str | None = None,
    opponent: str | None = None,
    game_id: str | None = None,
    season: int | None = None,
    week: int | None = None,
    source_url: str | None = None,
    observed_at: datetime | str | None = None,
    notes: str = "",
    illinois_college_team: bool = False,
) -> StartingQBEvidence:
    """Normalize a single starting-QB observation into scored evidence.

    source must be one of the SOURCE_WEIGHTS keys. Missing or unknown
    source yields UNKNOWN confidence. Illinois college teams are flagged
    but not filtered here (caller enforces exclusion).
    """
    key = str(source or "").strip().upper()
    weight = SOURCE_WEIGHTS.get(key, 0.0)
    name = (starter_name or "").strip() or None
    confidence = weight if name else 0.0
    observed = _aware(observed_at)
    return StartingQBEvidence(
        schema_version=SCHEMA_VERSION,
        lane=LANE,
        sport="CFB",
        team=str(team or "").strip(),
        opponent=opponent,
        game_id=game_id,
        season=season,
        week=week,
        starter_name=name,
        starter_jersey=(starter_jersey or "").strip() or None,
        backup_name=(backup_name or "").strip() or None,
        source=key if key in SOURCE_WEIGHTS else "UNKNOWN",
        source_url=source_url,
        observed_at_utc=observed.isoformat() if observed else None,
        confidence=round(confidence, 3),
        confidence_label=_label(confidence),
        notes=str(notes or "").strip(),
        illinois_college_team=bool(illinois_college_team),
        promotion_authority=False,
        play_authority=False,
    )


def merge_evidence(rows: list[StartingQBEvidence]) -> StartingQBEvidence | None:
    """Return the highest-confidence non-Illinois record for a team/game.

    Ties are broken by source weight, then by presence of an observed_at.
    Returns None when no usable evidence exists.
    """
    usable = [r for r in rows if not r.illinois_college_team and r.starter_name]
    if not usable:
        return None
    usable.sort(
        key=lambda r: (
            r.confidence,
            1 if r.observed_at_utc else 0,
        ),
        reverse=True,
    )
    return usable[0]


__all__ = [
    "SCHEMA_VERSION",
    "SOURCE_WEIGHTS",
    "StartingQBEvidence",
    "score_starting_qb",
    "merge_evidence",
]
