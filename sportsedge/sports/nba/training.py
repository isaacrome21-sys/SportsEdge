"""PIT-safe NBA training contracts and deterministic chronological splits.

Rows carry only information known at feature_as_of. Outcomes may occur later but
must never be used as features. Fitting code consumes these validated rows rather
than raw provider payloads.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Iterable


@dataclass(frozen=True)
class NBATrainingRow:
    game_id: str
    tipoff: datetime
    feature_as_of: datetime
    home_team_id: str
    away_team_id: str
    expected_possessions: float
    home_offensive_rating: float
    home_defensive_rating: float
    away_offensive_rating: float
    away_defensive_rating: float
    home_points: int
    away_points: int
    source_version: str

    def validate(self) -> None:
        if not all((self.game_id,self.home_team_id,self.away_team_id,self.source_version)):
            raise ValueError("training row identity/source version are required")
        if self.home_team_id == self.away_team_id:
            raise ValueError("home and away teams must differ")
        for name,value in (("tipoff",self.tipoff),("feature_as_of",self.feature_as_of)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.feature_as_of >= self.tipoff:
            raise ValueError("feature_as_of must be strictly before tipoff")
        vals=(self.expected_possessions,self.home_offensive_rating,self.home_defensive_rating,
              self.away_offensive_rating,self.away_defensive_rating)
        if any(not math.isfinite(v) or v <= 0 for v in vals):
            raise ValueError("pace/efficiency features must be finite and positive")
        if self.home_points < 0 or self.away_points < 0:
            raise ValueError("final scores must be non-negative")


def chronological_split(rows: Iterable[NBATrainingRow], *, validation_start: datetime):
    if validation_start.tzinfo is None or validation_start.utcoffset() is None:
        raise ValueError("validation_start must be timezone-aware")
    ordered=tuple(sorted(rows,key=lambda r:(r.tipoff,r.game_id)))
    if not ordered:
        raise ValueError("training rows are required")
    for row in ordered: row.validate()
    train=tuple(r for r in ordered if r.tipoff < validation_start)
    validation=tuple(r for r in ordered if r.tipoff >= validation_start)
    if not train or not validation:
        raise ValueError("chronological split requires non-empty train and validation sets")
    return train,validation


def training_digest(rows: Iterable[NBATrainingRow]) -> str:
    ordered=tuple(sorted(rows,key=lambda r:(r.tipoff,r.game_id)))
    for row in ordered: row.validate()
    payload=[{
        "game_id":r.game_id,"tipoff":r.tipoff.isoformat(),"feature_as_of":r.feature_as_of.isoformat(),
        "home":r.home_team_id,"away":r.away_team_id,"pace":r.expected_possessions,
        "hor":r.home_offensive_rating,"hdr":r.home_defensive_rating,
        "aor":r.away_offensive_rating,"adr":r.away_defensive_rating,
        "hp":r.home_points,"ap":r.away_points,"source_version":r.source_version,
    } for r in ordered]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
