"""Prospective validation contract for NHL player-shots and goalie-saves models.

This module evaluates prediction receipts that were captured before puck drop
against separate postgame settlement rows.  It does not create predictions,
fetch historical replacements, or grant production/card authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import math
import re
from typing import Iterable, Mapping, Sequence


WINDOW_START = date(2026, 10, 8)
WINDOW_END = date(2026, 11, 30)
SUPPORTED_LINES = {
    "PLAYER_SHOTS": frozenset({1.5, 2.5, 3.5, 4.5}),
    "GOALIE_SAVES": frozenset({21.5, 23.5, 25.5, 27.5, 29.5}),
}
MIN_CONFIRMED_ROWS = {"PLAYER_SHOTS": 200, "GOALIE_SAVES": 80}
MAX_ECE = 0.05
MAX_ABS_CALIBRATION_GAP = 0.04
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class NHLPropForwardValidationError(ValueError):
    pass


def _utc(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NHLPropForwardValidationError(f"invalid timestamp: {value}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NHLPropForwardValidationError("timestamps must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _prob(value: object, field: str) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError) as exc:
        raise NHLPropForwardValidationError(f"{field} must be numeric") from exc
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise NHLPropForwardValidationError(f"{field} must be in [0,1]")
    return p


@dataclass(frozen=True)
class PredictionReceipt:
    market: str
    game_id: str
    subject_id: str
    line: float
    candidate_p: float
    baseline_p: float
    captured_at: str
    start_time_utc: str
    role_status: str
    model_version: str
    source_sha256: str

    @property
    def key(self) -> tuple[str, str, str, float]:
        return self.market, self.game_id, self.subject_id, self.line

    def validate(self) -> None:
        if self.market not in SUPPORTED_LINES:
            raise NHLPropForwardValidationError(f"unsupported market: {self.market}")
        if self.line not in SUPPORTED_LINES[self.market]:
            raise NHLPropForwardValidationError(
                f"line {self.line} is outside preregistered grid for {self.market}"
            )
        _prob(self.candidate_p, "candidate_p")
        _prob(self.baseline_p, "baseline_p")
        if not self.game_id or not self.subject_id or not self.model_version:
            raise NHLPropForwardValidationError("game/subject/model identity required")
        if not _SHA256.fullmatch(self.source_sha256):
            raise NHLPropForwardValidationError("source_sha256 must be lowercase SHA-256")
        captured = _utc(self.captured_at)
        start = _utc(self.start_time_utc)
        if captured >= start:
            raise NHLPropForwardValidationError("prediction receipt is not pregame")
        if not WINDOW_START <= start.date() <= WINDOW_END:
            raise NHLPropForwardValidationError("prediction is outside frozen forward window")
        if self.role_status not in {"CONFIRMED", "PROJECTED"}:
            raise NHLPropForwardValidationError("role_status must be CONFIRMED or PROJECTED")


@dataclass(frozen=True)
class Settlement:
    market: str
    game_id: str
    subject_id: str
    actual_count: int
    final_at: str

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.market, self.game_id, self.subject_id

    def validate(self) -> None:
        if self.market not in SUPPORTED_LINES:
            raise NHLPropForwardValidationError(f"unsupported settlement market: {self.market}")
        if not self.game_id or not self.subject_id:
            raise NHLPropForwardValidationError("settlement identity required")
        if not isinstance(self.actual_count, int) or self.actual_count < 0:
            raise NHLPropForwardValidationError("actual_count must be a nonnegative integer")
        _utc(self.final_at)


@dataclass(frozen=True)
class EvaluationRow:
    market: str
    key: tuple[str, str, str, float]
    candidate_p: float
    baseline_p: float
    outcome: int
    role_status: str


def prediction_from_mapping(row: Mapping[str, object]) -> PredictionReceipt:
    try:
        receipt = PredictionReceipt(
            market=str(row["market"]).strip().upper(),
            game_id=str(row["game_id"]).strip(),
            subject_id=str(row["subject_id"]).strip(),
            line=float(row["line"]),
            candidate_p=_prob(row["candidate_p"], "candidate_p"),
            baseline_p=_prob(row["baseline_p"], "baseline_p"),
            captured_at=str(row["captured_at"]),
            start_time_utc=str(row["start_time_utc"]),
            role_status=str(row["role_status"]).strip().upper(),
            model_version=str(row["model_version"]).strip(),
            source_sha256=str(row["source_sha256"]).strip(),
        )
    except KeyError as exc:
        raise NHLPropForwardValidationError(f"prediction missing field: {exc.args[0]}") from exc
    receipt.validate()
    return receipt


def settlement_from_mapping(row: Mapping[str, object]) -> Settlement:
    try:
        settlement = Settlement(
            market=str(row["market"]).strip().upper(),
            game_id=str(row["game_id"]).strip(),
            subject_id=str(row["subject_id"]).strip(),
            actual_count=int(row["actual_count"]),
            final_at=str(row["final_at"]),
        )
    except KeyError as exc:
        raise NHLPropForwardValidationError(f"settlement missing field: {exc.args[0]}") from exc
    settlement.validate()
    return settlement


def join_rows(
    predictions: Sequence[PredictionReceipt],
    settlements: Sequence[Settlement],
) -> list[EvaluationRow]:
    seen: set[tuple[str, str, str, float]] = set()
    for prediction in predictions:
        prediction.validate()
        if prediction.key in seen:
            raise NHLPropForwardValidationError(f"duplicate prediction key: {prediction.key}")
        seen.add(prediction.key)

    settlement_by_identity: dict[tuple[str, str, str], Settlement] = {}
    for settlement in settlements:
        settlement.validate()
        if settlement.identity in settlement_by_identity:
            raise NHLPropForwardValidationError(
                f"duplicate settlement identity: {settlement.identity}"
            )
        settlement_by_identity[settlement.identity] = settlement

    joined: list[EvaluationRow] = []
    for prediction in predictions:
        identity = prediction.key[:3]
        settlement = settlement_by_identity.get(identity)
        if settlement is None:
            continue
        if _utc(settlement.final_at) <= _utc(prediction.start_time_utc):
            raise NHLPropForwardValidationError("settlement timestamp does not follow game start")
        joined.append(
            EvaluationRow(
                market=prediction.market,
                key=prediction.key,
                candidate_p=prediction.candidate_p,
                baseline_p=prediction.baseline_p,
                outcome=int(settlement.actual_count > prediction.line),
                role_status=prediction.role_status,
            )
        )
    return joined


def brier(rows: Iterable[EvaluationRow], field: str) -> float:
    seq = list(rows)
    if not seq:
        raise NHLPropForwardValidationError("cannot score an empty row set")
    return sum((float(getattr(row, field)) - row.outcome) ** 2 for row in seq) / len(seq)


def calibration_gap(rows: Iterable[EvaluationRow]) -> float:
    seq = list(rows)
    if not seq:
        raise NHLPropForwardValidationError("cannot calibrate an empty row set")
    return abs(sum(row.candidate_p for row in seq) / len(seq) - sum(row.outcome for row in seq) / len(seq))


def ece(rows: Iterable[EvaluationRow], *, bins: int = 10) -> float:
    seq = list(rows)
    if not seq:
        raise NHLPropForwardValidationError("cannot calibrate an empty row set")
    if bins < 2:
        raise NHLPropForwardValidationError("ECE requires at least two bins")
    total = len(seq)
    score = 0.0
    for idx in range(bins):
        lo = idx / bins
        hi = (idx + 1) / bins
        members = [
            row for row in seq
            if (lo <= row.candidate_p < hi) or (idx == bins - 1 and row.candidate_p == 1.0)
        ]
        if not members:
            continue
        mean_p = sum(row.candidate_p for row in members) / len(members)
        mean_y = sum(row.outcome for row in members) / len(members)
        score += (len(members) / total) * abs(mean_p - mean_y)
    return score


def evaluate_market(rows: Sequence[EvaluationRow], market: str) -> dict[str, object]:
    primary = [
        row for row in rows
        if row.market == market and row.role_status == "CONFIRMED"
    ]
    projected = [
        row for row in rows
        if row.market == market and row.role_status == "PROJECTED"
    ]
    minimum = MIN_CONFIRMED_ROWS[market]
    if not primary:
        return {
            "market": market,
            "status": "FORWARD_SAMPLE_PENDING",
            "n_confirmed": 0,
            "n_projected_report_only": len(projected),
            "minimum_confirmed_rows": minimum,
            "pass": False,
        }

    candidate_brier = brier(primary, "candidate_p")
    baseline_brier = brier(primary, "baseline_p")
    metric_ece = ece(primary)
    gap = calibration_gap(primary)
    gates = {
        "sample_size": len(primary) >= minimum,
        "brier_noninferiority": candidate_brier <= baseline_brier,
        "ece": metric_ece <= MAX_ECE,
        "absolute_calibration_gap": gap <= MAX_ABS_CALIBRATION_GAP,
    }
    passed = all(gates.values())
    return {
        "market": market,
        "status": "PASS_ELIGIBLE_FOR_SEPARATE_PROMOTION_REVIEW" if passed else "HOLD",
        "n_confirmed": len(primary),
        "n_projected_report_only": len(projected),
        "minimum_confirmed_rows": minimum,
        "candidate_brier": candidate_brier,
        "baseline_brier": baseline_brier,
        "ece": metric_ece,
        "absolute_calibration_gap": gap,
        "gates": gates,
        "pass": passed,
    }


def evaluate(
    predictions: Sequence[PredictionReceipt],
    settlements: Sequence[Settlement],
) -> dict[str, object]:
    joined = join_rows(predictions, settlements)
    markets = {
        market: evaluate_market(joined, market)
        for market in sorted(SUPPORTED_LINES)
    }
    return {
        "version": "NHL_PROP_FORWARD_VALIDATION_V1",
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "joined_rows": len(joined),
        "markets": markets,
        "authority": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
    }
