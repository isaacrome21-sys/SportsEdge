from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


@dataclass(frozen=True)
class ObjectiveWeights:
    version: str = "DFS_OBJECTIVE_V1"
    mean_weight: float = 1.0
    upside_weight: float = 0.34
    low_ownership_weight: float = 0.08
    chalk_penalty_weight: float = 0.05
    correlation_weight: float = 1.0

    def validate(self) -> None:
        values = (
            self.mean_weight,
            self.upside_weight,
            self.low_ownership_weight,
            self.chalk_penalty_weight,
            self.correlation_weight,
        )
        if any(not isinstance(v, (int, float)) or v < 0 or v > 5 for v in values):
            raise ValueError("DFS_OBJECTIVE_WEIGHT_OUT_OF_RANGE")
        if not self.version.strip():
            raise ValueError("DFS_OBJECTIVE_VERSION_REQUIRED")

    def digest(self) -> str:
        self.validate()
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


DEFAULT_OBJECTIVE_WEIGHTS = ObjectiveWeights()
