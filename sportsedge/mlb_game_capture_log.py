"""Forward MLB capture log: intake quotes stay distinct from closes.

Postseason rows are tagged as their own regime and must never mix into
regular-season calibration. This is a pipeline, not promotion evidence.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


class MLBCaptureLogError(ValueError):
    pass


REGULAR = "REGULAR"
POSTSEASON = "POSTSEASON"
AUTHORITY_FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"


def _utc(value: Any, code: str) -> datetime:
    if isinstance(value, datetime):
        stamp=value
    else:
        try:
            stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        except (TypeError, ValueError) as exc:
            raise MLBCaptureLogError(code) from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise MLBCaptureLogError(code)
    return stamp.astimezone(timezone.utc)


@dataclass(frozen=True)
class MLBCapturedGameRow:
    game_id: str
    market: str
    selection: str
    regime: str
    intake_line: float | None
    intake_american: int | None
    intake_retrieved_at: str
    close_line: float | None
    close_american: int | None
    close_retrieved_at: str | None
    estimate_p: float | None
    model_reliability: float
    authority_footer: str = AUTHORITY_FOOTER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def regime_for(*, official_date: str, season_type: str | None = None, postseason: bool | None = None) -> str:
    if postseason is True or str(season_type or "").upper() in {"P","PS","POST","POSTSEASON","PLAYOFFS"}:
        return POSTSEASON
    if postseason is False:
        return REGULAR
    # Dates after the locked 2026 regular-season holdout remain postseason until 2027.
    day=str(official_date)
    if day >= "2026-10-01":
        return POSTSEASON
    return REGULAR


def record_capture(row: Mapping[str, Any]) -> MLBCapturedGameRow:
    game_id=str(row.get("game_id") or "").strip()
    market=str(row.get("market") or "").strip().upper()
    selection=str(row.get("selection") or row.get("side") or "").strip()
    if not game_id or not market or not selection:
        raise MLBCaptureLogError("CAPTURE_IDENTITY_INCOMPLETE")
    intake_at=_utc(row.get("intake_retrieved_at") or row.get("retrieved_at"), "INTAKE_RETRIEVED_AT_REQUIRED")
    close_raw=row.get("close_retrieved_at")
    close_at=None if close_raw in (None, "") else _utc(close_raw, "CLOSE_RETRIEVED_AT_INVALID")
    if close_at is not None and close_at < intake_at:
        raise MLBCaptureLogError("CLOSE_BEFORE_INTAKE")
    rel=float(row.get("model_reliability") if row.get("model_reliability") is not None else 0.0)
    if rel != 0.0 and not (0.0 < rel <= 1.0):
        raise MLBCaptureLogError("MODEL_RELIABILITY_OUT_OF_RANGE")
    estimate=row.get("estimate_p")
    if "model_p" in row and estimate is None:
        raise MLBCaptureLogError("MODEL_P_FIELD_FORBIDDEN_USE_ESTIMATE_P")
    if estimate is not None:
        estimate=float(estimate)
        if not 0.0 < estimate < 1.0:
            raise MLBCaptureLogError("ESTIMATE_P_OUT_OF_RANGE")
    return MLBCapturedGameRow(
        game_id=game_id,
        market=market,
        selection=selection,
        regime=regime_for(
            official_date=str(row.get("official_date") or ""),
            season_type=row.get("season_type"),
            postseason=row.get("postseason"),
        ),
        intake_line=None if row.get("intake_line", row.get("line")) is None else float(row.get("intake_line", row.get("line"))),
        intake_american=None if row.get("intake_american", row.get("american_odds")) is None else int(row.get("intake_american", row.get("american_odds"))),
        intake_retrieved_at=intake_at.isoformat().replace("+00:00","Z"),
        close_line=None if row.get("close_line") is None else float(row["close_line"]),
        close_american=None if row.get("close_american") is None else int(row["close_american"]),
        close_retrieved_at=None if close_at is None else close_at.isoformat().replace("+00:00","Z"),
        estimate_p=estimate,
        model_reliability=rel,
    )
