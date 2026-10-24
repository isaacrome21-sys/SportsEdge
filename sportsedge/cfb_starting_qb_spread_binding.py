"""Research-only attachment of starting-QB evidence to CFB spread assessments.

Does not authenticate model promotion, issue PLAY, override Illinois exclusion,
or treat self-labeled sources as verified fact. Callers must supply dated rows
with source_url for any claim above MODERATE. Contradictory high-confidence
starter names for the same team/game force the result to LOW.
Returned QB records always have promotion_authority=False and play_authority=False.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from sportsedge.cfb_spread_price_gate import SpreadAssessment, assess_spread
from sportsedge.cfb_starting_qb_evidence import StartingQBEvidence, merge_evidence
from sportsedge.cfb_starting_qb_intake import from_source_rows


@dataclass(frozen=True)
class BoundSpreadAssessment:
    assessment: SpreadAssessment
    home_qb: StartingQBEvidence | None
    away_qb: StartingQBEvidence | None
    matchup_identity_confidence: float
    matchup_identity_label: str
    binding_notes: str
    play_authority: bool = False
    promotion_authority: bool = False


def _force_zero_authority(evidence: StartingQBEvidence | None) -> StartingQBEvidence | None:
    if evidence is None:
        return None
    if evidence.promotion_authority or evidence.play_authority:
        return replace(evidence, promotion_authority=False, play_authority=False)
    return evidence


def _require_url_for_high(evidence: StartingQBEvidence | None) -> StartingQBEvidence | None:
    if evidence is None:
        return None
    if evidence.confidence >= 0.70 and not (evidence.source_url or "").strip():
        return replace(
            evidence,
            confidence=0.55,
            confidence_label="MODERATE",
            notes=(evidence.notes + " [URL_REQUIRED_FOR_HIGH]").strip(),
        )
    return evidence


def _contradiction_penalty(candidates: list[StartingQBEvidence]) -> StartingQBEvidence | None:
    if not candidates:
        return None
    high = [c for c in candidates if c.confidence >= 0.70 and c.starter_name]
    names = {c.starter_name for c in high}
    if len(names) > 1:
        best = merge_evidence(candidates)
        if best is None:
            return None
        return replace(
            best,
            confidence=0.25,
            confidence_label="LOW",
            notes=(best.notes + " [CONTRADICTORY_HIGH_CONFIDENCE_STARTERS]").strip(),
        )
    return merge_evidence(candidates)


def bind_starting_qbs_to_spread(
    *,
    source_rows: list[Mapping[str, Any]],
    home_team: str,
    away_team: str,
    game_id: str | None = None,
    season: int | None = None,
    week: int | None = None,
    assess_kwargs: Mapping[str, Any],
) -> BoundSpreadAssessment:
    """Attach best available starting-QB evidence to a spread assessment.

    Research-only. Illinois teams remain excluded by assess_spread.
    High-confidence labels require a source_url. Contradictory high-confidence
    names for the same scoped team force LOW. Empty team names yield no QB.
    """
    home = str(home_team or "").strip()
    away = str(away_team or "").strip()
    if not home or not away:
        assessment = assess_spread(**assess_kwargs)
        return BoundSpreadAssessment(
            assessment=assessment,
            home_qb=None,
            away_qb=None,
            matchup_identity_confidence=0.0,
            matchup_identity_label="UNKNOWN",
            binding_notes="empty_team_name",
            play_authority=False,
            promotion_authority=False,
        )

    scored = from_source_rows(source_rows)

    def _match(row: StartingQBEvidence, team: str) -> bool:
        if row.team.casefold() != team.casefold():
            return False
        if game_id and row.game_id and str(row.game_id) != str(game_id):
            return False
        if season is not None and row.season is not None and int(row.season) != int(season):
            return False
        if week is not None and row.week is not None and int(row.week) != int(week):
            return False
        return True

    home_candidates = [r for r in scored if _match(r, home)]
    away_candidates = [r for r in scored if _match(r, away)]
    home_qb = _force_zero_authority(_require_url_for_high(_contradiction_penalty(home_candidates)))
    away_qb = _force_zero_authority(_require_url_for_high(_contradiction_penalty(away_candidates)))

    assessment = assess_spread(**assess_kwargs)

    confidences = [qb.confidence for qb in (home_qb, away_qb) if qb is not None]
    matchup_conf = min(confidences) if confidences else 0.0
    if matchup_conf >= 0.90:
        label = "CONFIRMED"
    elif matchup_conf >= 0.70:
        label = "HIGH"
    elif matchup_conf >= 0.50:
        label = "MODERATE"
    elif matchup_conf >= 0.25:
        label = "LOW"
    else:
        label = "UNKNOWN"

    notes = []
    if home_qb is None:
        notes.append("home_qb_missing")
    if away_qb is None:
        notes.append("away_qb_missing")
    if matchup_conf < 0.50:
        notes.append("matchup_identity_below_moderate")
    if any("CONTRADICTORY" in (qb.notes or "") for qb in (home_qb, away_qb) if qb):
        notes.append("contradictory_high_confidence_detected")

    return BoundSpreadAssessment(
        assessment=assessment,
        home_qb=home_qb,
        away_qb=away_qb,
        matchup_identity_confidence=round(matchup_conf, 3),
        matchup_identity_label=label,
        binding_notes="; ".join(notes),
        play_authority=False,
        promotion_authority=False,
    )


__all__ = ["BoundSpreadAssessment", "bind_starting_qbs_to_spread"]
