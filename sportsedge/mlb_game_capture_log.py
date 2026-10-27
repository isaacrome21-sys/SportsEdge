"""Forward MLB capture log: intake quotes stay distinct from closes.

Postseason rows are tagged as their own regime and must never mix into
regular-season calibration. This is a pipeline, not promotion evidence.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math
from datetime import date, datetime, timezone
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



def _american_odds(value: Any, code: str) -> int | None:
    """Keep exact bookmaker American prices; never coerce bool/float/zero."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise MLBCaptureLogError(code)
    if isinstance(value, int):
        odds = value
    elif isinstance(value, str):
        raw = value.strip()
        digits = raw[1:] if raw[:1] in ("+", "-") else raw
        if not digits or not digits.isascii() or not digits.isdigit():
            raise MLBCaptureLogError(code)
        odds = int(raw)
    else:
        raise MLBCaptureLogError(code)
    if -99 <= odds <= 99:
        raise MLBCaptureLogError(code)
    return odds



def _quote_line(value: Any, code: str, *, required: bool = False) -> float | None:
    """Refuse false, non-finite or missing numeric market thresholds."""
    if value is None:
        if required:
            raise MLBCaptureLogError(code)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MLBCaptureLogError(code)
    try:
        line = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MLBCaptureLogError(code) from exc
    if not math.isfinite(line):
        raise MLBCaptureLogError(code)
    return line


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
    # Validate the official identity before allowing any season flag to decide.
    try:
        day = date.fromisoformat(str(official_date))
    except (TypeError, ValueError) as exc:
        raise MLBCaptureLogError("OFFICIAL_DATE_INVALID") from exc
    if not isinstance(postseason, (bool, type(None))):
        raise MLBCaptureLogError("POSTSEASON_FLAG_INVALID")
    code = str(season_type or "").strip().upper()
    post_codes = {"P", "PS", "POST", "POSTSEASON", "PLAYOFFS"}
    regular_codes = {"R", "REG", "REGULAR", "REGULAR_SEASON"}
    if code and code not in post_codes | regular_codes:
        raise MLBCaptureLogError("SEASON_TYPE_UNKNOWN")
    if code and postseason is not None and (code in post_codes) != postseason:
        raise MLBCaptureLogError("SEASON_FLAGS_CONFLICT")
    if postseason is True or code in post_codes:
        return POSTSEASON
    if postseason is False or code in regular_codes:
        return REGULAR
    # 2026 postseason shorthand is legacy evidence only, never a standing
    # rule for every future season. Future late-season rows need an explicit
    # source season type, since October may contain regular or playoff games.
    if day.year == 2026 and day.month >= 10:
        return POSTSEASON
    if day.year >= 2027 and day.month >= 10:
        raise MLBCaptureLogError("FUTURE_LATE_SEASON_TYPE_REQUIRED")
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
    if close_at is not None and close_at <= intake_at:
        raise MLBCaptureLogError("CLOSE_NOT_AFTER_INTAKE")
    if close_at is not None and row.get("close_american") is None:
        raise MLBCaptureLogError("CLOSE_PRICE_MISSING")
    if close_at is None and (row.get("close_american") is not None or row.get("close_line") is not None):
        raise MLBCaptureLogError("CLOSE_TIMESTAMP_MISSING")
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
    # Binary winner moneylines have no threshold; every other market does.
    line_required = market not in {"MONEYLINE", "ML", "H2H"}
    intake_line = _quote_line(row.get("intake_line", row.get("line")),
                              "INTAKE_LINE_INVALID", required=line_required)
    close_line = _quote_line(row.get("close_line"), "CLOSE_LINE_INVALID",
                             required=line_required and close_at is not None)
    if not line_required and (intake_line is not None or close_line is not None):
        # H2H/ML winner quotes are prices only, never handicaps.
        raise MLBCaptureLogError("MONEYLINE_THRESHOLD_FORBIDDEN")
    return MLBCapturedGameRow(
        game_id=game_id,
        market=market,
        selection=selection,
        regime=regime_for(
            official_date=str(row.get("official_date") or ""),
            season_type=row.get("season_type"),
            postseason=row.get("postseason"),
        ),
        intake_line=intake_line,
        intake_american=_american_odds(row.get("intake_american", row.get("american_odds")), "INTAKE_AMERICAN_INVALID"),
        intake_retrieved_at=intake_at.isoformat().replace("+00:00","Z"),
        close_line=close_line,
        close_american=_american_odds(row.get("close_american"), "CLOSE_AMERICAN_INVALID"),
        close_retrieved_at=None if close_at is None else close_at.isoformat().replace("+00:00","Z"),
        estimate_p=estimate,
        model_reliability=rel,
    )
