"""Fail-closed prospective evidence receipts for NHL player props.

This module records already-computed candidate/baseline probabilities together
with an external sportsbook quote.  It never calculates Model_P, edge, EV,
Score, staking, role state, or promotion authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Mapping


WINDOW_START = date(2026, 10, 8)
WINDOW_END = date(2026, 11, 30)
SUPPORTED_LINES = {
    "PLAYER_SHOTS": frozenset({1.5, 2.5, 3.5, 4.5}),
    "GOALIE_SAVES": frozenset({21.5, 23.5, 25.5, 27.5, 29.5}),
}
MAX_RECEIPT_AGE = timedelta(minutes=15)
MAX_FUTURE_SKEW = timedelta(minutes=2)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_FORBIDDEN_AUTHORITY_FIELDS = {
    "model_p",
    "edge",
    "ev",
    "kelly",
    "stake",
    "score",
    "official",
    "actionable",
}
_INFERENCE_FIELDS = {"role_inferred", "starter_inferred", "inferred_role", "inferred_starter"}


class NHLPropReceiptError(ValueError):
    pass


def _utc(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NHLPropReceiptError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NHLPropReceiptError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _prob(value: object, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise NHLPropReceiptError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise NHLPropReceiptError(f"{field} must be in [0,1]")
    return parsed


def _slug(value: str) -> str:
    slug = _SAFE.sub("-", value.strip()).strip("-._")
    return slug[:96] or "unknown"


@dataclass(frozen=True)
class PropReceipt:
    market: str
    game_id: str
    subject_id: str
    line: float
    candidate_p: float
    baseline_p: float
    book: str
    american_odds: int
    captured_at: str
    start_time_utc: str
    role_status: str
    role_source: str
    model_version: str
    source: str
    source_sha256: str

    def validate(self, *, now: datetime | None = None) -> None:
        if self.market not in SUPPORTED_LINES:
            raise NHLPropReceiptError(f"unsupported market: {self.market}")
        if self.line not in SUPPORTED_LINES[self.market]:
            raise NHLPropReceiptError(
                f"line {self.line} is outside preregistered grid for {self.market}"
            )
        _prob(self.candidate_p, "candidate_p")
        _prob(self.baseline_p, "baseline_p")
        if not self.game_id or not self.subject_id or not self.model_version:
            raise NHLPropReceiptError("game/subject/model identity required")
        if not self.book or not self.source or not self.role_source:
            raise NHLPropReceiptError("book/source/role_source required")
        if self.role_status not in {"CONFIRMED", "PROJECTED"}:
            raise NHLPropReceiptError("role_status must be explicitly CONFIRMED or PROJECTED")
        if not _SHA256.fullmatch(self.source_sha256):
            raise NHLPropReceiptError("source_sha256 must be lowercase SHA-256")
        if abs(self.american_odds) < 100 or abs(self.american_odds) > 10000:
            raise NHLPropReceiptError("american_odds must have absolute value in [100,10000]")

        captured = _utc(self.captured_at, "captured_at")
        start = _utc(self.start_time_utc, "start_time_utc")
        if captured >= start:
            raise NHLPropReceiptError("receipt is not pre-puck")
        if not WINDOW_START <= start.date() <= WINDOW_END:
            raise NHLPropReceiptError("game is outside frozen forward window")

        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if captured > current + MAX_FUTURE_SKEW:
            raise NHLPropReceiptError("captured_at is in the future")
        if current - captured > MAX_RECEIPT_AGE:
            raise NHLPropReceiptError("stale receipt blocked by no-backfill policy")

    def as_dict(self) -> dict[str, object]:
        return {
            "receipt_version": "NHL_PROP_FORWARD_RECEIPT_V1",
            "market": self.market,
            "game_id": self.game_id,
            "subject_id": self.subject_id,
            "line": self.line,
            "candidate_p": self.candidate_p,
            "baseline_p": self.baseline_p,
            "book": self.book,
            "american_odds": self.american_odds,
            "captured_at": self.captured_at,
            "start_time_utc": self.start_time_utc,
            "role_status": self.role_status,
            "role_source": self.role_source,
            "model_version": self.model_version,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "authority": "EVIDENCE_ONLY_NO_CARD_AUTHORITY",
        }


def receipt_from_mapping(row: Mapping[str, object], *, now: datetime | None = None) -> PropReceipt:
    lowered = {str(key).strip().lower() for key in row}
    forbidden = sorted(lowered & _FORBIDDEN_AUTHORITY_FIELDS)
    if forbidden:
        raise NHLPropReceiptError(f"card-authority fields forbidden: {','.join(forbidden)}")
    inference = sorted(
        key for key in _INFERENCE_FIELDS
        if key in row and bool(row[key])
    )
    if inference:
        raise NHLPropReceiptError(f"inferred role/starter state forbidden: {','.join(inference)}")

    try:
        odds_raw = row["american_odds"]
        if isinstance(odds_raw, bool) or int(odds_raw) != float(odds_raw):
            raise ValueError
        receipt = PropReceipt(
            market=str(row["market"]).strip().upper(),
            game_id=str(row["game_id"]).strip(),
            subject_id=str(row["subject_id"]).strip(),
            line=float(row["line"]),
            candidate_p=_prob(row["candidate_p"], "candidate_p"),
            baseline_p=_prob(row["baseline_p"], "baseline_p"),
            book=str(row["book"]).strip(),
            american_odds=int(odds_raw),
            captured_at=str(row["captured_at"]).strip(),
            start_time_utc=str(row["start_time_utc"]).strip(),
            role_status=str(row["role_status"]).strip().upper(),
            role_source=str(row["role_source"]).strip(),
            model_version=str(row["model_version"]).strip(),
            source=str(row["source"]).strip(),
            source_sha256=str(row["source_sha256"]).strip(),
        )
    except KeyError as exc:
        raise NHLPropReceiptError(f"receipt missing field: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise NHLPropReceiptError("line and american_odds must be numeric") from exc
    receipt.validate(now=now)
    return receipt


def canonical_bytes(receipt: PropReceipt) -> bytes:
    return (json.dumps(receipt.as_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def receipt_path(receipt: PropReceipt, *, output_root: str | Path) -> Path:
    payload_hash = hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    start = _utc(receipt.start_time_utc, "start_time_utc")
    captured = _utc(receipt.captured_at, "captured_at")
    return (
        Path(output_root)
        / start.date().isoformat()
        / _slug(receipt.game_id)
        / receipt.market.lower()
        / _slug(receipt.subject_id)
        / f"{captured.strftime('%Y%m%dT%H%M%SZ')}_{payload_hash[:16]}.json"
    )


def write_create_only(receipt: PropReceipt, *, output_root: str | Path) -> tuple[Path, str]:
    path = receipt_path(receipt, output_root=output_root)
    payload = canonical_bytes(receipt)
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise NHLPropReceiptError(f"create-only collision: {path}")
        return path, "ALREADY_CAPTURED"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path, "CAPTURED"
