"""Immutable content-addressed pregame prediction journal for MLB evaluated rows.

Schema v2 preserves fail-closed BLOCKED candidates instead of silently dropping
unpriced/blocked evaluations. Historical v1 artifacts are immutable and remain
recognizable, but v1 and v2 prediction counts are not directly comparable because
v1 omitted unpriced BLOCKED rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
from typing import Any, Mapping

from .runtime import parse_timestamp

JOURNAL_SCHEMA_VERSION = "mlb_prediction_journal_v2"
LEGACY_JOURNAL_SCHEMA_VERSIONS = frozenset({"mlb_prediction_journal_v1"})
DECISION_STATUSES = frozenset({"BET", "OFFICIAL_BET", "PASS"})
JOURNALED_STATUSES = frozenset(set(DECISION_STATUSES) | {"BLOCKED"})
STAGE1_GAME_MARKETS = frozenset({
    "MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS",
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS",
    "FIRST_HOME_RUN", "PITCHER_RECORD_WIN",
})
RESET_PROP_MARKETS = frozenset({"HITS", "TOTAL_BASES", "PITCHER_BB"})
STAGE1_PROVENANCE_FIELDS = ("model_input_hash", "distribution_sha256", "readout_sha256", "readout_version")
RESET_PROP_PROVENANCE_FIELDS = ("model_input_hash", "engine_version", "seed_policy", "mc_paths")
_CANONICAL_COUNT_STATUSES = ("BET", "OFFICIAL_BET", "PASS", "BLOCKED", "NO_ENGINE")


class PredictionJournalError(ValueError):
    pass


@dataclass(frozen=True)
class JournalWriteResult:
    path: str
    journal_sha256: str
    source_report_sha256: str
    prediction_count: int
    created: bool


def normalize_legacy_block_reason(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize legacy serializer output before the journal boundary.

    The durable v2 journal has one canonical field for a blocked explanation:
    ``block_reason``. Legacy run objects still expose ``reason``; serializers call
    this helper so the journal itself never needs to accept two names.
    """
    if not isinstance(row, Mapping):
        raise PredictionJournalError("result row must be an object")
    out = dict(row)
    status = str(out.get("bet_status") or "").strip().upper()
    if status == "BLOCKED":
        legacy = out.pop("reason", None)
        canonical = str(out.get("block_reason") or "").strip()
        if not canonical and legacy not in (None, ""):
            out["block_reason"] = str(legacy).strip()
    return out


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PredictionJournalError("journal payload is not canonical JSON") from exc


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise PredictionJournalError(f"{field} must be SHA-256 hex")
    return text


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PredictionJournalError(f"{field} required")
    return text


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise PredictionJournalError(f"{field} must be a nonnegative integer")
    try:
        parsed = int(value); numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise PredictionJournalError(f"{field} must be a nonnegative integer") from exc
    if parsed < 0 or numeric != parsed:
        raise PredictionJournalError(f"{field} must be a nonnegative integer")
    return parsed


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise PredictionJournalError(f"{field} must be probability")
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise PredictionJournalError(f"{field} must be probability") from exc
    if not isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise PredictionJournalError(f"{field} must be in [0,1]")
    return probability


def _validate_priced_provenance(out: dict[str, Any], row: Mapping[str, Any], *, market: str) -> None:
    out["model_input_hash"] = _valid_sha256(row.get("model_input_hash"), "model_input_hash")
    if market in STAGE1_GAME_MARKETS:
        out["distribution_sha256"] = _valid_sha256(row.get("distribution_sha256"), "distribution_sha256")
        out["readout_sha256"] = _valid_sha256(row.get("readout_sha256"), "readout_sha256")
        out["readout_version"] = _required_text(row.get("readout_version"), "readout_version")
    if market in RESET_PROP_MARKETS:
        out["engine_version"] = _required_text(row.get("engine_version"), "engine_version")
        out["seed_policy"] = _required_text(row.get("seed_policy"), "seed_policy")
        out["mc_paths"] = _nonnegative_int(row.get("mc_paths"), "mc_paths")


def _modeled_prediction(row: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    status = str(row.get("bet_status") or "").strip().upper()
    model_p = row.get("model_p")
    edge = row.get("edge")

    if status == "NO_ENGINE":
        if model_p is not None or edge is not None:
            raise PredictionJournalError(f"result[{index}] NO_ENGINE cannot carry model_p/edge")
        return None
    if status not in JOURNALED_STATUSES:
        return None

    market = str(row.get("market") or "").strip().upper()
    if not market:
        raise PredictionJournalError(f"result[{index}].market missing")
    out = dict(row)
    out.pop("reason", None)
    out["market"] = market
    out["bet_status"] = status

    if status == "BLOCKED":
        out["block_reason"] = _required_text(row.get("block_reason"), f"result[{index}].block_reason")
        if model_p is None:
            if edge is not None:
                raise PredictionJournalError(f"result[{index}] unpriced BLOCKED cannot carry edge")
            out["model_p"] = None
            return out
        probability = _probability(model_p, f"result[{index}].model_p")
        out["model_p"] = probability
        _validate_priced_provenance(out, row, market=market)
        return out

    if model_p is None:
        raise PredictionJournalError(f"result[{index}] {status} row missing model_p")
    probability = _probability(model_p, f"result[{index}].model_p")
    out["model_p"] = probability
    if market in STAGE1_GAME_MARKETS:
        out["model_input_hash"] = _valid_sha256(row.get("model_input_hash"), "model_input_hash")
        out["distribution_sha256"] = _valid_sha256(row.get("distribution_sha256"), "distribution_sha256")
        out["readout_sha256"] = _valid_sha256(row.get("readout_sha256"), "readout_sha256")
        out["readout_version"] = _required_text(row.get("readout_version"), "readout_version")
    if market in RESET_PROP_MARKETS:
        out["model_input_hash"] = _valid_sha256(row.get("model_input_hash"), "model_input_hash")
        out["engine_version"] = _required_text(row.get("engine_version"), "engine_version")
        out["seed_policy"] = _required_text(row.get("seed_policy"), "seed_policy")
        out["mc_paths"] = _nonnegative_int(row.get("mc_paths"), "mc_paths")
    return out


def _decision_counts(results: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in _CANONICAL_COUNT_STATUSES}
    for row in results:
        status = str(row.get("bet_status") or "MISSING").strip().upper() or "MISSING"
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_prediction_journal_record(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        raise PredictionJournalError("report payload must be an object")
    results = payload.get("results")
    if not isinstance(results, list):
        raise PredictionJournalError("report results must be a list")
    predictions: list[dict[str, Any]] = []
    for index, raw in enumerate(results):
        if not isinstance(raw, Mapping):
            raise PredictionJournalError(f"result[{index}] must be an object")
        modeled = _modeled_prediction(raw, index)
        if modeled is not None:
            predictions.append(modeled)
    if not predictions:
        return None
    slate_date = str(payload.get("slate_date_ct") or "").strip()
    try:
        date.fromisoformat(slate_date)
    except ValueError as exc:
        raise PredictionJournalError("slate_date_ct must be YYYY-MM-DD") from exc
    generated_at = parse_timestamp(payload.get("generated_at_utc"))
    source_report_sha256 = _sha256_bytes(_canonical_bytes(dict(payload)))
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "slate_date_ct": slate_date,
        "generated_at_utc": generated_at.isoformat(),
        "mode": payload.get("mode"),
        "run_status": payload.get("run_status"),
        "card_status": payload.get("card_status"),
        "source_report_sha256": source_report_sha256,
        "prediction_count": len(predictions),
        "decision_counts": _decision_counts(results),
        "predictions": predictions,
    }


def read_prediction_journal(path: str | Path) -> dict[str, Any]:
    """Read v2 or immutable legacy v1 without silently migrating either schema."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise PredictionJournalError("unable to read prediction journal") from exc
    if not isinstance(value, dict):
        raise PredictionJournalError("prediction journal root must be an object")
    version = str(value.get("schema_version") or "")
    if version != JOURNAL_SCHEMA_VERSION and version not in LEGACY_JOURNAL_SCHEMA_VERSIONS:
        raise PredictionJournalError(f"prediction journal schema unsupported: {version or 'MISSING'}")
    return value


def write_prediction_journal(payload: Mapping[str, Any], *, root: str | Path = "artifacts/prediction_journal") -> JournalWriteResult | None:
    record = build_prediction_journal_record(payload)
    if record is None:
        return None
    canonical = _canonical_bytes(record)
    journal_sha256 = _sha256_bytes(canonical)
    raw = canonical + b"\n"
    generated_at = parse_timestamp(record["generated_at_utc"])
    timestamp = generated_at.strftime("%Y%m%dT%H%M%S.%fZ")
    directory = Path(root) / str(record["slate_date_ct"])
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{timestamp}_{journal_sha256}.json"
    created = False
    try:
        with target.open("xb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        created = True
    except FileExistsError:
        if target.read_bytes() != raw:
            raise PredictionJournalError("immutable journal path collision")
    return JournalWriteResult(
        path=str(target), journal_sha256=journal_sha256,
        source_report_sha256=str(record["source_report_sha256"]),
        prediction_count=int(record["prediction_count"]), created=created,
    )


def journal_reference(result: JournalWriteResult) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "path": result.path,
        "journal_sha256": result.journal_sha256,
        "source_report_sha256": result.source_report_sha256,
        "prediction_count": result.prediction_count,
        "created": result.created,
    }
