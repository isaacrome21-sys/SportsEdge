from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from .runtime import parse_timestamp


class MLBBetLedgerError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise MLBBetLedgerError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBBetLedgerError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _prob(value: Any, field: str, *, inclusive: bool = True) -> float:
    if isinstance(value, bool):
        raise MLBBetLedgerError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBBetLedgerError(f"{field} must be numeric") from exc
    if not math.isfinite(x) or (not 0 <= x <= 1 if inclusive else not 0 < x < 1):
        raise MLBBetLedgerError(f"{field} outside probability range")
    return x


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MLBBetLedgerError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBBetLedgerError(f"{field} must be numeric") from exc
    if not math.isfinite(x):
        raise MLBBetLedgerError(f"{field} must be finite")
    return x


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class MLBBetLedgerRow:
    game_id: str
    market: str
    entity: str
    side: str
    line: float
    american_odds: int
    sportsbook: str
    observed_at_utc: str
    first_pitch_at_utc: str
    model_probability: float
    fair_market_probability: float
    raw_edge: float
    confidence_multiplier: float
    research_adjusted_edge: float
    model_sha: str
    feature_contract_sha: str
    lineup_state: str
    weather_state: str
    umpire_state: str
    conflict_flags: tuple[str, ...]
    result: str | None = None
    outcome: float | None = None
    closing_american_odds: int | None = None

    @property
    def selection_key(self) -> str:
        return _sha({
            "game_id": self.game_id,
            "market": self.market,
            "entity": self.entity,
            "side": self.side,
            "line": self.line,
            "american_odds": self.american_odds,
            "sportsbook": self.sportsbook,
            "observed_at_utc": self.observed_at_utc,
        })

    def as_record(self) -> dict[str, Any]:
        row = asdict(self)
        row["selection_key"] = self.selection_key
        return row


def validate_ledger_row(row: Mapping[str, Any]) -> MLBBetLedgerRow:
    required_text = (
        "game_id", "market", "entity", "side", "sportsbook", "model_sha",
        "feature_contract_sha", "lineup_state", "weather_state", "umpire_state",
    )
    text: dict[str, str] = {}
    for field in required_text:
        value = str(row.get(field) or "").strip()
        if not value:
            raise MLBBetLedgerError(f"{field} is required")
        text[field] = value

    observed = _utc(row.get("observed_at_utc"), "observed_at_utc")
    first_pitch = _utc(row.get("first_pitch_at_utc"), "first_pitch_at_utc")
    if observed >= first_pitch:
        raise MLBBetLedgerError("ledger quote must be pregame")

    line = _finite(row.get("line"), "line")
    try:
        odds = int(row.get("american_odds"))
    except Exception as exc:
        raise MLBBetLedgerError("american_odds must be integer-like") from exc
    if -100 < odds < 100:
        raise MLBBetLedgerError("invalid American odds")

    model_p = _prob(row.get("model_probability"), "model_probability")
    fair_p = _prob(row.get("fair_market_probability"), "fair_market_probability", inclusive=False)
    raw_edge = _finite(row.get("raw_edge"), "raw_edge")
    if abs(raw_edge - (model_p - fair_p)) > 1e-9:
        raise MLBBetLedgerError("raw_edge does not reconcile")
    confidence = _prob(row.get("confidence_multiplier"), "confidence_multiplier")
    adjusted = _finite(row.get("research_adjusted_edge"), "research_adjusted_edge")
    if abs(adjusted - raw_edge * confidence) > 1e-9:
        raise MLBBetLedgerError("research_adjusted_edge does not reconcile")

    flags_raw = row.get("conflict_flags", ())
    if not isinstance(flags_raw, (list, tuple)):
        raise MLBBetLedgerError("conflict_flags must be an array")
    flags = tuple(str(v).strip() for v in flags_raw if str(v).strip())

    result = row.get("result")
    result_text = None if result in (None, "") else str(result).upper().strip()
    if result_text not in {None, "WIN", "LOSS", "PUSH", "VOID"}:
        raise MLBBetLedgerError("invalid result")
    outcome = None if row.get("outcome") is None else _prob(row.get("outcome"), "outcome")
    closing = row.get("closing_american_odds")
    if closing is not None:
        closing = int(closing)
        if -100 < closing < 100:
            raise MLBBetLedgerError("invalid closing American odds")

    return MLBBetLedgerRow(
        game_id=text["game_id"], market=text["market"].upper(), entity=text["entity"],
        side=text["side"].upper(), line=line, american_odds=odds,
        sportsbook=text["sportsbook"], observed_at_utc=observed.isoformat(),
        first_pitch_at_utc=first_pitch.isoformat(), model_probability=model_p,
        fair_market_probability=fair_p, raw_edge=raw_edge,
        confidence_multiplier=confidence, research_adjusted_edge=adjusted,
        model_sha=text["model_sha"], feature_contract_sha=text["feature_contract_sha"],
        lineup_state=text["lineup_state"].upper(), weather_state=text["weather_state"].upper(),
        umpire_state=text["umpire_state"].upper(), conflict_flags=flags,
        result=result_text, outcome=outcome, closing_american_odds=closing,
    )


def summarize_ledger(rows: Iterable[Mapping[str, Any] | MLBBetLedgerRow]) -> dict[str, Any]:
    parsed = [r if isinstance(r, MLBBetLedgerRow) else validate_ledger_row(r) for r in rows]
    settled = [r for r in parsed if r.result in {"WIN", "LOSS", "PUSH", "VOID"}]
    by_market: dict[str, dict[str, int]] = {}
    for row in settled:
        bucket = by_market.setdefault(row.market, {"WIN": 0, "LOSS": 0, "PUSH": 0, "VOID": 0, "N": 0})
        bucket[row.result] += 1
        bucket["N"] += 1
    return {
        "rows": len(parsed),
        "settled": len(settled),
        "by_market": by_market,
        "ledger_sha256": _sha([r.as_record() for r in parsed]),
    }
