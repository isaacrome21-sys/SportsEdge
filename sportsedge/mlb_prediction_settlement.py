"""Deterministic settlement bridge for immutable MLB game-market predictions.

This module does not infer sportsbook settlement semantics. It consumes the immutable
pregame prediction journal plus per-game reports from ``mlb_settlement_evidence``.
A prediction receives WIN/LOSS/PUSH only when the corresponding market row is
SETTLEMENT_ELIGIBLE using non-synthetic official facts and validated sportsbook-rule
evidence. Otherwise the prediction remains UNRESOLVED with a machine-readable reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
from typing import Any, Mapping

from .mlb_settlement_evidence import canonical_bytes as settlement_fact_bytes
from .prediction_journal import JOURNAL_SCHEMA_VERSION, STAGE1_PROVENANCE_FIELDS
from .runtime import parse_timestamp

SETTLEMENT_SCHEMA_VERSION = "mlb_game_prediction_settlement_v1"
SETTLEMENT_EVIDENCE_SCHEMA_VERSION = "mlb_settlement_evidence_v3"
STAGE1_GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS"})
FINAL_RESULTS = frozenset({"WIN", "LOSS", "PUSH"})
REQUIRED_RULE_ID = "FULL_GAME_FINAL_SCORE_SETTLEMENT"
SYNTHETIC_EVIDENCE_CLASS = "SYNTHETIC_CONTRACT_TEST"


class MLBPredictionSettlementError(ValueError):
    pass


@dataclass(frozen=True)
class SettlementWriteResult:
    path: str
    settlement_sha256: str
    prediction_journal_sha256: str
    prediction_count: int
    resolved_count: int
    unresolved_count: int
    created: bool


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MLBPredictionSettlementError("settlement payload is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def prediction_journal_sha256(record: Mapping[str, Any]) -> str:
    if not isinstance(record, Mapping):
        raise MLBPredictionSettlementError("prediction journal must be an object")
    if str(record.get("schema_version")) != JOURNAL_SCHEMA_VERSION:
        raise MLBPredictionSettlementError("unsupported prediction journal schema")
    predictions = record.get("predictions")
    if not isinstance(predictions, list):
        raise MLBPredictionSettlementError("prediction journal predictions must be a list")
    try:
        declared_count = int(record.get("prediction_count"))
    except (TypeError, ValueError) as exc:
        raise MLBPredictionSettlementError("prediction journal prediction_count invalid") from exc
    if declared_count != len(predictions):
        raise MLBPredictionSettlementError("prediction journal prediction_count mismatch")
    return _sha256(dict(record))


def _valid_sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise MLBPredictionSettlementError(f"{field} must be SHA-256 hex")
    return text


def _settled_at(value: Any) -> str:
    dt = parse_timestamp(value)
    return dt.astimezone(timezone.utc).isoformat()


def _line(value: Any) -> float:
    if isinstance(value, bool):
        raise MLBPredictionSettlementError("prediction line must be finite numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBPredictionSettlementError("prediction line must be finite numeric") from exc
    if not isfinite(out):
        raise MLBPredictionSettlementError("prediction line must be finite numeric")
    return out


def _game_id_from_report(report: Mapping[str, Any]) -> str:
    facts = report.get("facts")
    if not isinstance(facts, Mapping):
        raise MLBPredictionSettlementError("settlement report facts missing")
    raw = facts.get("game_pk")
    try:
        game_pk = int(raw)
    except (TypeError, ValueError) as exc:
        raise MLBPredictionSettlementError("settlement report game_pk invalid") from exc
    if game_pk <= 0:
        raise MLBPredictionSettlementError("settlement report game_pk invalid")
    game = facts.get("game")
    if not isinstance(game, Mapping):
        raise MLBPredictionSettlementError("settlement report game facts missing")
    return str(game_pk)


def _report_index(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(reports, Mapping):
        raise MLBPredictionSettlementError("settlement_reports_by_game must be an object")
    out: dict[str, Mapping[str, Any]] = {}
    for supplied_game_id, raw in reports.items():
        if not isinstance(raw, Mapping):
            raise MLBPredictionSettlementError("settlement report must be an object")
        actual_game_id = _game_id_from_report(raw)
        if str(supplied_game_id) != actual_game_id:
            raise MLBPredictionSettlementError(
                f"settlement report key/game mismatch: {supplied_game_id}!={actual_game_id}"
            )
        if actual_game_id in out:
            raise MLBPredictionSettlementError(f"duplicate settlement report for game {actual_game_id}")
        out[actual_game_id] = raw
    return out


def _market_row(report: Mapping[str, Any], market: str) -> Mapping[str, Any] | None:
    rows = report.get("markets")
    if not isinstance(rows, list):
        raise MLBPredictionSettlementError("settlement report markets must be a list")
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and str(row.get("market") or "").strip().upper() == market
    ]
    if len(matches) > 1:
        raise MLBPredictionSettlementError(f"duplicate settlement market row: {market}")
    return matches[0] if matches else None


def _eligibility(report: Mapping[str, Any], market: str) -> tuple[bool, str, str | None]:
    evidence_sha = hashlib.sha256(settlement_fact_bytes(report)).hexdigest()
    if str(report.get("schema_version") or "") != SETTLEMENT_EVIDENCE_SCHEMA_VERSION:
        return False, "SETTLEMENT_EVIDENCE_SCHEMA_UNSUPPORTED", evidence_sha

    evidence_class = str(report.get("evidence_class") or "").strip().upper()
    if not evidence_class:
        return False, "SETTLEMENT_EVIDENCE_CLASS_MISSING", evidence_sha
    if evidence_class == SYNTHETIC_EVIDENCE_CLASS:
        return False, "SYNTHETIC_SETTLEMENT_EVIDENCE_PROHIBITED", evidence_sha

    facts = report.get("facts")
    if not isinstance(facts, Mapping):
        raise MLBPredictionSettlementError("settlement report facts missing")
    reported_facts_sha = _valid_sha256(report.get("facts_sha256"), "facts_sha256")
    actual_facts_sha = hashlib.sha256(settlement_fact_bytes(facts)).hexdigest()
    if reported_facts_sha != actual_facts_sha:
        return False, "SETTLEMENT_FACTS_HASH_MISMATCH", evidence_sha

    row = _market_row(report, market)
    if row is None:
        return False, "MARKET_SETTLEMENT_ROW_MISSING", evidence_sha
    required_rules = row.get("required_book_rules")
    if not isinstance(required_rules, list) or REQUIRED_RULE_ID not in [str(x) for x in required_rules]:
        return False, "FULL_GAME_SETTLEMENT_RULE_ID_MISMATCH", evidence_sha
    state = str(row.get("settlement_semantics_state") or "").strip().upper()
    if state != "SETTLEMENT_ELIGIBLE":
        return False, state or "SETTLEMENT_STATE_MISSING", evidence_sha
    if str(row.get("official_fact_state") or "").strip().upper() != "OFFICIAL_FACTS_PROVEN":
        return False, "OFFICIAL_FACTS_NOT_PROVEN", evidence_sha
    if row.get("book_rules_validated") is not True:
        return False, "BOOK_SETTLEMENT_UNVALIDATED", evidence_sha
    return True, "SETTLEMENT_ELIGIBLE", evidence_sha


def _final_score(report: Mapping[str, Any], expected_game_id: str) -> tuple[int, int]:
    facts = report.get("facts")
    if not isinstance(facts, Mapping):
        raise MLBPredictionSettlementError("settlement report facts missing")
    if str(facts.get("game_pk")) != expected_game_id:
        raise MLBPredictionSettlementError("prediction/settlement game mismatch")
    game = facts.get("game")
    if not isinstance(game, Mapping):
        raise MLBPredictionSettlementError("settlement report game facts missing")
    try:
        away_runs = int(game.get("away_runs"))
        home_runs = int(game.get("home_runs"))
    except (TypeError, ValueError) as exc:
        raise MLBPredictionSettlementError("final score missing") from exc
    if away_runs < 0 or home_runs < 0:
        raise MLBPredictionSettlementError("final score invalid")
    return away_runs, home_runs


def _validate_stage1_prediction(prediction: Mapping[str, Any], index: int) -> str:
    market = str(prediction.get("market") or "").strip().upper()
    if market not in STAGE1_GAME_MARKETS:
        return market
    for field in STAGE1_PROVENANCE_FIELDS:
        if field == "readout_version":
            if not str(prediction.get(field) or "").strip():
                raise MLBPredictionSettlementError(
                    f"prediction[{index}].readout_version missing"
                )
        else:
            _valid_sha256(prediction.get(field), f"prediction[{index}].{field}")
    return market


def _resolve_result(prediction: Mapping[str, Any], away_runs: int, home_runs: int) -> tuple[str, str]:
    market = str(prediction.get("market") or "").strip().upper()
    side = str(prediction.get("side") or "").strip().upper()

    if market == "MONEYLINE":
        if away_runs == home_runs:
            return "UNRESOLVED", "MONEYLINE_FINAL_TIE_REQUIRES_BOOK_RULE"
        if side in {"HOME", "HOME_ML"}:
            won = home_runs > away_runs
        elif side in {"AWAY", "AWAY_ML"}:
            won = away_runs > home_runs
        else:
            raise MLBPredictionSettlementError("moneyline side unsupported")
        return ("WIN" if won else "LOSS"), "FINAL_SCORE"

    line = _line(prediction.get("line"))
    if market == "RUN_LINE":
        if side in {"HOME", "HOME_RL"}:
            margin = (home_runs - away_runs) + line
        elif side in {"AWAY", "AWAY_RL"}:
            margin = (away_runs - home_runs) + line
        else:
            raise MLBPredictionSettlementError("run-line side unsupported")
        if abs(margin) < 1e-12:
            return "PUSH", "FINAL_SCORE_AND_LINE"
        return ("WIN" if margin > 0 else "LOSS"), "FINAL_SCORE_AND_LINE"

    if market == "TOTALS":
        if line < 0:
            raise MLBPredictionSettlementError("totals line must be >= 0")
        difference = (away_runs + home_runs) - line
        if abs(difference) < 1e-12:
            return "PUSH", "FINAL_SCORE_AND_LINE"
        if side == "OVER":
            won = difference > 0
        elif side == "UNDER":
            won = difference < 0
        else:
            raise MLBPredictionSettlementError("totals side unsupported")
        return ("WIN" if won else "LOSS"), "FINAL_SCORE_AND_LINE"

    raise MLBPredictionSettlementError(f"unsupported Stage 1 settlement market: {market}")


def _unresolved(
    prediction: Mapping[str, Any],
    *,
    reason: str,
    evidence_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        **dict(prediction),
        "settlement_result": "UNRESOLVED",
        "settlement_reason": reason,
        "away_runs": None,
        "home_runs": None,
        "settlement_evidence_sha256": evidence_sha256,
    }


def build_game_prediction_settlement_record(
    prediction_journal: Mapping[str, Any],
    *,
    settlement_reports_by_game: Mapping[str, Mapping[str, Any]],
    settled_at_utc: Any,
    expected_prediction_journal_sha256: str | None = None,
) -> dict[str, Any] | None:
    journal_sha = prediction_journal_sha256(prediction_journal)
    if expected_prediction_journal_sha256 is not None:
        expected = _valid_sha256(
            expected_prediction_journal_sha256, "expected_prediction_journal_sha256"
        )
        if expected != journal_sha:
            raise MLBPredictionSettlementError("prediction journal SHA mismatch")

    source_report_sha = _valid_sha256(
        prediction_journal.get("source_report_sha256"), "source_report_sha256"
    )
    predictions = prediction_journal.get("predictions")
    if not isinstance(predictions, list):
        raise MLBPredictionSettlementError("prediction journal predictions must be a list")
    reports = _report_index(settlement_reports_by_game)

    game_predictions: list[Mapping[str, Any]] = []
    for index, raw in enumerate(predictions):
        if not isinstance(raw, Mapping):
            raise MLBPredictionSettlementError(f"prediction[{index}] must be an object")
        market = _validate_stage1_prediction(raw, index)
        if market in STAGE1_GAME_MARKETS:
            game_predictions.append(raw)
    if not game_predictions:
        return None

    outcomes: list[dict[str, Any]] = []
    for prediction in game_predictions:
        game_id = str(prediction.get("game_id") or "").strip()
        if not game_id:
            raise MLBPredictionSettlementError("game prediction missing game_id")
        report = reports.get(game_id)
        if report is None:
            outcomes.append(_unresolved(prediction, reason="GAME_SETTLEMENT_EVIDENCE_MISSING"))
            continue

        market = str(prediction.get("market") or "").strip().upper()
        eligible, reason, evidence_sha = _eligibility(report, market)
        if not eligible:
            outcomes.append(
                _unresolved(prediction, reason=reason, evidence_sha256=evidence_sha)
            )
            continue

        away_runs, home_runs = _final_score(report, game_id)
        result, result_reason = _resolve_result(prediction, away_runs, home_runs)
        outcomes.append({
            **dict(prediction),
            "settlement_result": result,
            "settlement_reason": result_reason,
            "away_runs": away_runs,
            "home_runs": home_runs,
            "settlement_evidence_sha256": evidence_sha,
        })

    resolved = sum(row["settlement_result"] in FINAL_RESULTS for row in outcomes)
    unresolved = len(outcomes) - resolved
    wins = sum(row["settlement_result"] == "WIN" for row in outcomes)
    losses = sum(row["settlement_result"] == "LOSS" for row in outcomes)
    pushes = sum(row["settlement_result"] == "PUSH" for row in outcomes)

    return {
        "schema_version": SETTLEMENT_SCHEMA_VERSION,
        "prediction_journal_schema_version": JOURNAL_SCHEMA_VERSION,
        "prediction_journal_sha256": journal_sha,
        "source_report_sha256": source_report_sha,
        "slate_date_ct": str(prediction_journal.get("slate_date_ct") or ""),
        "prediction_generated_at_utc": str(prediction_journal.get("generated_at_utc") or ""),
        "settled_at_utc": _settled_at(settled_at_utc),
        "prediction_count": len(outcomes),
        "resolved_count": resolved,
        "unresolved_count": unresolved,
        "win_count": wins,
        "loss_count": losses,
        "push_count": pushes,
        "settlement_complete": unresolved == 0,
        "outcomes": outcomes,
    }


def write_game_prediction_settlement(
    record: Mapping[str, Any],
    *,
    root: str | Path = "artifacts/settlement_journal",
) -> SettlementWriteResult:
    if not isinstance(record, Mapping):
        raise MLBPredictionSettlementError("settlement record must be an object")
    if str(record.get("schema_version")) != SETTLEMENT_SCHEMA_VERSION:
        raise MLBPredictionSettlementError("unsupported settlement record schema")
    journal_sha = _valid_sha256(
        record.get("prediction_journal_sha256"), "prediction_journal_sha256"
    )
    settled_at = parse_timestamp(record.get("settled_at_utc"))
    canonical = _canonical_bytes(dict(record))
    settlement_sha = hashlib.sha256(canonical).hexdigest()
    raw = canonical + b"\n"
    slate_date = str(record.get("slate_date_ct") or "UNKNOWN")
    directory = Path(root) / slate_date / journal_sha
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = settled_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = directory / f"{timestamp}_{settlement_sha}.json"

    created = False
    try:
        with target.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        created = True
    except FileExistsError:
        if target.read_bytes() != raw:
            raise MLBPredictionSettlementError("immutable settlement path collision")

    return SettlementWriteResult(
        path=str(target),
        settlement_sha256=settlement_sha,
        prediction_journal_sha256=journal_sha,
        prediction_count=int(record.get("prediction_count", 0)),
        resolved_count=int(record.get("resolved_count", 0)),
        unresolved_count=int(record.get("unresolved_count", 0)),
        created=created,
    )
