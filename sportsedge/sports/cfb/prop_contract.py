"""Experimental CFB prop contract.

Player props are useful to scan in Manual/Hybrid mode, but they are not certified by
CFB_TRUTH_GATE_V1 and cannot enter the main-market predictive feature path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any


class CFBPropContractError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBPropContractError(f"{field}:TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBPropContractError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBPropContractError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBPropContractError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBPropContractError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class ExperimentalCFBProp:
    game_id: str
    player_id: str
    team_id: str
    opponent_id: str
    market_type: str
    side: str
    sportsbook_line: float
    american_odds: float
    model_fair_line: float
    model_probability: float
    role_status: str
    expected_opportunities: float
    opportunity_share: float
    role_source_asof_ts: str
    feature_asof_ts: str
    game_start_ts: str
    source_provenance_id: str
    status: str = "EXPERIMENTAL_PROP"
    truth_gate_policy: str = "NONE"

    def validate(self) -> "ExperimentalCFBProp":
        if not all((self.game_id, self.player_id, self.team_id, self.opponent_id, self.market_type, self.side)):
            raise CFBPropContractError("PROP_IDENTITY_REQUIRED")
        if self.status != "EXPERIMENTAL_PROP" or self.truth_gate_policy != "NONE":
            raise CFBPropContractError("PROP_MAIN_GATE_INHERITANCE_FORBIDDEN")
        if self.role_status not in {"CONFIRMED", "PROJECTED"}:
            raise CFBPropContractError("PROP_ROLE_STATUS_INVALID")
        for field in ("sportsbook_line", "american_odds", "model_fair_line", "expected_opportunities", "opportunity_share"):
            _finite(getattr(self, field), field)
        p = _finite(self.model_probability, "model_probability")
        if not 0.0 <= p <= 1.0:
            raise CFBPropContractError("PROP_PROBABILITY_RANGE")
        if not 0.0 <= float(self.opportunity_share) <= 1.0:
            raise CFBPropContractError("PROP_OPPORTUNITY_SHARE_RANGE")
        source = _utc(self.role_source_asof_ts, "role_source_asof_ts")
        feature = _utc(self.feature_asof_ts, "feature_asof_ts")
        game = _utc(self.game_start_ts, "game_start_ts")
        if source > feature or feature >= game:
            raise CFBPropContractError("PROP_PIT_VIOLATION")
        if not self.source_provenance_id:
            raise CFBPropContractError("PROP_PROVENANCE_REQUIRED")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


def assert_prop_isolation(*, status: str, truth_gate_policy: str | None) -> None:
    if str(status).upper() not in {"EXPERIMENTAL_PROP", "MANUAL_HYBRID_REVIEW"}:
        raise CFBPropContractError("PROP_STATUS_NOT_EXPERIMENTAL")
    if str(truth_gate_policy or "").upper() not in {"", "NONE", "CFB_PROP_TRUTH_GATE_V1_UNBUILT"}:
        raise CFBPropContractError("PROP_MAIN_GATE_INHERITANCE_FORBIDDEN")
