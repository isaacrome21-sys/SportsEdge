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

# Without a source URL AND an aware observation time a row is unprovenanced
# and can score no higher than a projection, whatever source it claims.
UNPROVENANCED_CAP = SOURCE_WEIGHTS["PROJECTED_OR_OR_LISTED"]
# A self-labelled official row whose page content was not checked by the
# caller is capped below CONFIRMED (review flag 1 on PR #2528).
OFFICIAL_UNVERIFIED_CAP = SOURCE_WEIGHTS["PRESS_BOX_OR_247_DEPTH_CHART"]

# Derived Illinois exclusion (owner rule): never rely on the caller flag only.
ILLINOIS_COLLEGE_TEAMS = frozenset({
    "illinois", "illinois fighting illini", "northwestern",
    "northwestern wildcats", "northern illinois", "niu",
    "northern illinois huskies", "illinois state", "illinois state redbirds",
    "southern illinois", "siu", "southern illinois salukis",
    "eastern illinois", "eastern illinois panthers", "western illinois",
    "western illinois leathernecks",
})


def _team_key(name: str | None) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def is_illinois_college_team(name: str | None) -> bool:
    return _team_key(name) in ILLINOIS_COLLEGE_TEAMS


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
    content_verified: bool = False,
) -> StartingQBEvidence:
    """Normalize a single starting-QB observation into scored evidence.

    source must be one of the SOURCE_WEIGHTS keys. Missing or unknown
    source yields UNKNOWN confidence. Illinois college teams are flagged
    but not filtered here (caller enforces exclusion).
    """
    key = str(source or "").strip().upper()
    weight = SOURCE_WEIGHTS.get(key, 0.0)
    name = (starter_name or "").strip() or None
    observed = _aware(observed_at)
    url = str(source_url or "").strip()
    flags = []
    if not (url.lower().startswith(("https://", "http://")) and observed):
        weight = min(weight, UNPROVENANCED_CAP)
        flags.append("UNPROVENANCED_CAPPED")
    elif key == "OFFICIAL_TEAM_OR_CONFERENCE" and not content_verified:
        weight = min(weight, OFFICIAL_UNVERIFIED_CAP)
        flags.append("OFFICIAL_CONTENT_UNVERIFIED_CAPPED")
    confidence = weight if name else 0.0
    illinois = bool(illinois_college_team) or is_illinois_college_team(team) \
        or is_illinois_college_team(opponent)
    notes = " ".join([str(notes or "").strip()] + flags).strip()
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
        illinois_college_team=illinois,
        promotion_authority=False,
        play_authority=False,
    )


def merge_evidence(rows: list[StartingQBEvidence], *, team: str | None = None,
                   game_id: str | None = None) -> StartingQBEvidence | None:
    """Return the best non-Illinois starter record for ONE team in ONE game.

    Fail-closed (returns None) when: no usable row; rows span more than one
    team or more than one game_id (after optional team/game_id filters);
    or the top-confidence rows name different starters (a conflict is not
    resolved by guessing). Ties on confidence prefer the newest observation.
    """
    usable = [r for r in rows if not r.illinois_college_team and r.starter_name]
    if team is not None:
        usable = [r for r in usable if _team_key(r.team) == _team_key(team)]
    if game_id is not None:
        usable = [r for r in usable if r.game_id == game_id]
    if not usable:
        return None
    if len({_team_key(r.team) for r in usable}) != 1:
        return None
    if len({r.game_id for r in usable}) != 1:
        return None
    top = max(r.confidence for r in usable)
    best = [r for r in usable if r.confidence == top]
    if len({_team_key(r.starter_name) for r in best}) != 1:
        return None
    best.sort(key=lambda r: r.observed_at_utc or "", reverse=True)
    return best[0]


__all__ = [
    "SCHEMA_VERSION",
    "SOURCE_WEIGHTS",
    "StartingQBEvidence",
    "score_starting_qb",
    "merge_evidence",
    "is_illinois_college_team",
]
