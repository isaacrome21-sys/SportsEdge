"""Deterministic invalidation for MLB Model_P when authoritative evidence changes.

A previously generated probability may not survive a starting-pitcher, confirmed-lineup,
or game-identity change. The caller must recompute affected features/model outputs or
block the candidate before issuing a new decision.
"""
from __future__ import annotations

from dataclasses import dataclass


class MLBEvidenceInvalidationError(ValueError):
    pass


@dataclass(frozen=True)
class MLBEvidenceFingerprint:
    game_id: str
    game_number: int
    doubleheader_code: str
    away_probable_pitcher_id: int | None
    home_probable_pitcher_id: int | None
    away_lineup_hash: str | None
    home_lineup_hash: str | None
    evidence_asof: str

    def validate(self) -> "MLBEvidenceFingerprint":
        if not self.game_id or not self.evidence_asof:
            raise MLBEvidenceInvalidationError("GAME_ID_AND_ASOF_REQUIRED")
        if isinstance(self.game_number, bool) or int(self.game_number) < 1:
            raise MLBEvidenceInvalidationError("GAME_NUMBER_INVALID")
        return self


@dataclass(frozen=True)
class MLBMarketDependencies:
    starting_pitchers: bool = True
    confirmed_lineups: bool = True
    game_identity: bool = True


@dataclass(frozen=True)
class MLBInvalidationResult:
    invalidated: bool
    reasons: tuple[str, ...]
    required_action: str


def evaluate_mlb_evidence_change(
    previous: MLBEvidenceFingerprint,
    current: MLBEvidenceFingerprint,
    *,
    dependencies: MLBMarketDependencies = MLBMarketDependencies(),
) -> MLBInvalidationResult:
    old = previous.validate()
    new = current.validate()
    reasons: list[str] = []
    if dependencies.game_identity and (
        old.game_id != new.game_id
        or int(old.game_number) != int(new.game_number)
        or old.doubleheader_code != new.doubleheader_code
    ):
        reasons.append("GAME_IDENTITY_CHANGED")
    if dependencies.starting_pitchers and (
        old.away_probable_pitcher_id != new.away_probable_pitcher_id
        or old.home_probable_pitcher_id != new.home_probable_pitcher_id
    ):
        reasons.append("STARTING_PITCHER_CHANGED")
    if dependencies.confirmed_lineups and (
        old.away_lineup_hash != new.away_lineup_hash
        or old.home_lineup_hash != new.home_lineup_hash
    ):
        reasons.append("CONFIRMED_LINEUP_CHANGED")
    invalidated = bool(reasons)
    return MLBInvalidationResult(
        invalidated=invalidated,
        reasons=tuple(reasons),
        required_action="RECOMPUTE_OR_BLOCK" if invalidated else "NO_CHANGE",
    )
