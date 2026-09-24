"""PIT-safe NHL historical training records and deterministic provenance."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib, json

def _utc(value: str) -> datetime:
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None: raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)

@dataclass(frozen=True)
class NHLHistoricalGame:
    game_id: str
    season: str
    puck_drop: str
    captured_at: str
    home_team: str
    away_team: str
    source: str
    source_version: str
    features: dict[str,float]
    home_regulation_goals: int|None=None
    away_regulation_goals: int|None=None
    settled_at: str|None=None
    def __post_init__(self):
        puck,captured=_utc(self.puck_drop),_utc(self.captured_at)
        if not captured < puck: raise ValueError("PIT violation: features must be captured before puck drop")
        if not self.game_id or not self.source or not self.source_version: raise ValueError("provenance required")
        observed=self.home_regulation_goals is not None or self.away_regulation_goals is not None
        if observed:
            if self.home_regulation_goals is None or self.away_regulation_goals is None or self.settled_at is None:
                raise ValueError("targets require both scores and settled_at")
            if _utc(self.settled_at) <= puck: raise ValueError("settlement must be after puck drop")
            if min(self.home_regulation_goals,self.away_regulation_goals)<0: raise ValueError("goals must be nonnegative")
        elif self.settled_at is not None:
            raise ValueError("settled_at without targets")

def training_rows(records:list[NHLHistoricalGame], cutoff:str)->list[NHLHistoricalGame]:
    cut=_utc(cutoff)
    return [r for r in records if r.settled_at is not None and _utc(r.settled_at)<cut and _utc(r.captured_at)<_utc(r.puck_drop)]

def dataset_sha256(records:list[NHLHistoricalGame])->str:
    payload=[asdict(r) for r in sorted(records,key=lambda x:(x.puck_drop,x.game_id))]
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class NHLTrainingProvenance:
    model_version:str
    feature_schema_version:str
    training_cutoff:str
    dataset_sha256:str
    code_version:str
    calibration_method:str
    def __post_init__(self):
        _utc(self.training_cutoff)
        if not all((self.model_version,self.feature_schema_version,self.dataset_sha256,self.code_version,self.calibration_method)):
            raise ValueError("complete deterministic training provenance required")
