"""Immutable content-addressed pregame prediction journal for MLB modeled rows."""
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

JOURNAL_SCHEMA_VERSION = "mlb_prediction_journal_v1"
DECISION_STATUSES = frozenset({"BET", "OFFICIAL_BET", "PASS"})
STAGE1_GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})
RESET_PROP_MARKETS = frozenset({"HITS", "TOTAL_BASES", "PITCHER_BB"})
STAGE1_PROVENANCE_FIELDS = ("model_input_hash", "distribution_sha256", "readout_sha256", "readout_version")
RESET_PROP_PROVENANCE_FIELDS = ("model_input_hash", "engine_version", "seed_policy", "mc_paths")


class PredictionJournalError(ValueError):
    pass


@dataclass(frozen=True)
class JournalWriteResult:
    path: str
    journal_sha256: str
    source_report_sha256: str
    prediction_count: int
    created: bool


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


def _modeled_prediction(row: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    model_p = row.get("model_p")
    if model_p is None:
        return None
    if isinstance(model_p, bool):
        raise PredictionJournalError(f"result[{index}].model_p must be probability")
    try:
        probability = float(model_p)
    except (TypeError, ValueError) as exc:
        raise PredictionJournalError(f"result[{index}].model_p must be probability") from exc
    if not isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise PredictionJournalError(f"result[{index}].model_p must be in [0,1]")
    status = str(row.get("bet_status") or "").strip().upper()
    if status not in DECISION_STATUSES:
        raise PredictionJournalError(f"result[{index}] modeled row lacks BET/PASS decision: {status or 'MISSING'}")
    market = str(row.get("market") or "").strip().upper()
    if not market:
        raise PredictionJournalError(f"result[{index}].market missing")
    out = dict(row); out["market"] = market; out["bet_status"] = status; out["model_p"] = probability
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


def build_prediction_journal_record(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping): raise PredictionJournalError("report payload must be an object")
    results = payload.get("results")
    if not isinstance(results, list): raise PredictionJournalError("report results must be a list")
    predictions = []
    for index, raw in enumerate(results):
        if not isinstance(raw, Mapping): raise PredictionJournalError(f"result[{index}] must be an object")
        modeled = _modeled_prediction(raw, index)
        if modeled is not None: predictions.append(modeled)
    if not predictions: return None
    slate_date = str(payload.get("slate_date_ct") or "").strip()
    try: date.fromisoformat(slate_date)
    except ValueError as exc: raise PredictionJournalError("slate_date_ct must be YYYY-MM-DD") from exc
    generated_at = parse_timestamp(payload.get("generated_at_utc"))
    source_report_sha256 = _sha256_bytes(_canonical_bytes(dict(payload)))
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION, "slate_date_ct": slate_date,
        "generated_at_utc": generated_at.isoformat(), "mode": payload.get("mode"),
        "run_status": payload.get("run_status"), "card_status": payload.get("card_status"),
        "source_report_sha256": source_report_sha256,
        "prediction_count": len(predictions), "predictions": predictions,
    }


def write_prediction_journal(payload: Mapping[str, Any], *, root: str | Path = "artifacts/prediction_journal") -> JournalWriteResult | None:
    record = build_prediction_journal_record(payload)
    if record is None: return None
    canonical = _canonical_bytes(record); journal_sha256 = _sha256_bytes(canonical); raw = canonical + b"\n"
    generated_at = parse_timestamp(record["generated_at_utc"]); timestamp = generated_at.strftime("%Y%m%dT%H%M%S.%fZ")
    directory = Path(root) / str(record["slate_date_ct"]); directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{timestamp}_{journal_sha256}.json"; created = False
    try:
        with target.open("xb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        created = True
    except FileExistsError:
        if target.read_bytes() != raw: raise PredictionJournalError("immutable journal path collision")
    return JournalWriteResult(path=str(target), journal_sha256=journal_sha256, source_report_sha256=str(record["source_report_sha256"]), prediction_count=int(record["prediction_count"]), created=created)


def journal_reference(result: JournalWriteResult) -> dict[str, Any]:
    return {"schema_version": JOURNAL_SCHEMA_VERSION, "path": result.path, "journal_sha256": result.journal_sha256, "source_report_sha256": result.source_report_sha256, "prediction_count": result.prediction_count, "created": result.created}
