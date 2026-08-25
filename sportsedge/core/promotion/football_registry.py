"""Fail-closed per-market NFL promotion registry.

Structural implementation never implies promotion. Historical evidence must be
produced by the exact production NFL M2 feature/model contract, share the same
canonical multi-source manifest and exact code SHA as simulator math, and carry
forward CLV from that same exact code contract. Missing market evidence never
inherits a stage from another market, a caller-supplied CI boolean can never
self-attest execution, and promotion-grade CLV must prove comparable threshold,
pregame timing, same-sportsbook close identity, and internally reconciled row
counts before it can advance a market.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from sportsedge.core.promotion.football import evaluate_football_promotion_from_math_artifact
from sportsedge.core.validation.math_attestation import attest_validated_math
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_CI_WORKFLOW = "football-nfl-promotion-evidence"
_EXPECTED_CLV_SCHEMA = 4
_EXPECTED_CLV_REFERENCE = "DECISION_THRESHOLD"
_EXPECTED_CLV_FORWARD_TIME = "PREGAME_DECISION_TO_PREGAME_CLOSE"
_EXPECTED_CLV_BOOK = "SAME_BOOK_AS_DECISION"


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64:
        raise ValueError(error)
    try:
        int(raw, 16)
    except ValueError as exc:
        raise ValueError(error) from exc
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _source_hash(value: Mapping[str, Any], name: str) -> str:
    return _sha256(value.get("source_sha256"), f"{name}_SOURCE_SHA256_INVALID")


def _count(value: Any, error: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(error)
    return value


def _clv_bucket(
    value: Any,
    *,
    required_error: str,
    row_error_prefix: str,
) -> tuple[Mapping[str, Any], int]:
    payload = _mapping(value)
    if payload is None:
        raise ValueError(required_error)
    total = 0
    for raw_market, raw_row in payload.items():
        market = str(raw_market).strip().lower()
        if not market:
            raise ValueError(f"{row_error_prefix}_MARKET_INVALID")
        row = _mapping(raw_row)
        if row is None:
            raise ValueError(f"{row_error_prefix}_ROW_INVALID:{market}")
        total += _count(
            row.get("logged_plays"),
            f"{row_error_prefix}_LOGGED_PLAYS_INVALID:{market}",
        )
    return payload, total


def _verify_ci_attestation(
    value: Mapping[str, Any] | None,
    *,
    code_git_sha: str,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    attestation = _mapping(value)
    if attestation is None:
        raise ValueError("NFL_CI_ATTESTATION_EVIDENCE_REQUIRED")
    if int(attestation.get("schema_version", 0)) != 1:
        raise ValueError("NFL_CI_ATTESTATION_SCHEMA_INVALID")
    if str(attestation.get("workflow_name") or "") != _EXPECTED_CI_WORKFLOW:
        raise ValueError("NFL_CI_ATTESTATION_WORKFLOW_MISMATCH")
    if str(attestation.get("workflow_conclusion") or "").strip().lower() != "success":
        raise ValueError("NFL_CI_ATTESTATION_NOT_SUCCESSFUL")
    try:
        run_id = int(attestation.get("workflow_run_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_CI_ATTESTATION_RUN_ID_INVALID") from exc
    if run_id <= 0:
        raise ValueError("NFL_CI_ATTESTATION_RUN_ID_INVALID")
    attested_code_sha = _git_sha(
        attestation.get("git_sha"), "NFL_CI_ATTESTATION_CODE_SHA_INVALID"
    )
    if attested_code_sha != code_git_sha:
        raise ValueError("NFL_CI_ATTESTATION_CODE_SHA_MISMATCH")
    attested_source_sha = _sha256(
        attestation.get("source_manifest_sha256"),
        "NFL_CI_ATTESTATION_SOURCE_SHA256_INVALID",
    )
    if attested_source_sha != source_manifest_sha256:
        raise ValueError("NFL_CI_ATTESTATION_SOURCE_MISMATCH")
    if attestation.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_CI_ATTESTATION_MODEL_ID_MISMATCH")
    if attestation.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_CI_ATTESTATION_FEATURE_CONTRACT_MISMATCH")
    try:
        verified_count = int(attestation.get("verified_artifact_count"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_CI_ATTESTATION_ARTIFACT_COUNT_INVALID") from exc
    if verified_count <= 0:
        raise ValueError("NFL_CI_ATTESTATION_ARTIFACT_COUNT_INVALID")
    return {
        "schema_version": 1,
        "workflow_name": _EXPECTED_CI_WORKFLOW,
        "workflow_conclusion": "success",
        "workflow_run_id": run_id,
        "git_sha": attested_code_sha,
        "source_manifest_sha256": attested_source_sha,
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "verified_artifact_count": verified_count,
    }


def _reason(*, stage: str, history: Mapping[str, Any] | None, calibration: Mapping[str, Any] | None,
            ci_attested: bool, clv: Mapping[str, Any] | None) -> str:
    if stage == "BLOCKED_MATH":
        return "MATH_ATTESTATION_FAILED"
    if stage == "VALIDATED_MATH":
        return "WALKFORWARD_EVIDENCE_MISSING" if history is None else "FOLD_WIN_RATE_BELOW_THRESHOLD"
    if stage == "PRODUCTION_LOGIC_PASS":
        if calibration is None:
            return "CALIBRATION_EVIDENCE_MISSING"
        if calibration.get("pass") is not True:
            return "CALIBRATION_GATE_FAILED"
        if not ci_attested:
            return "CI_ATTESTATION_MISSING"
        return "CI_OR_CALIBRATION_GATE_NOT_ATTESTED"
    if stage == "CI_ATTESTED":
        return "CLV_EVIDENCE_MISSING" if clv is None else "CLV_GATE_NOT_MET"
    if stage == "DEPLOYED":
        return "ALL_PROMOTION_GATES_PASS"
    return "UNKNOWN_PROMOTION_STAGE"


def build_nfl_promotion_registry(
    math_artifact: Mapping[str, Any],
    historical_evidence: Mapping[str, Any],
    *,
    declared_markets: Iterable[str],
    ci_attested: bool = False,
    ci_attestation: Mapping[str, Any] | None = None,
    clv_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(ci_attested, bool):
        raise ValueError("CI_ATTESTED_STATE_INVALID")
    math_hash = _source_hash(math_artifact, "MATH")
    history_hash = _source_hash(historical_evidence, "HISTORY")
    if math_hash != history_hash:
        raise ValueError("NFL_PROMOTION_SOURCE_HASH_MISMATCH")
    manifest_hash = _sha256(
        historical_evidence.get("source_manifest_sha256"),
        "NFL_PROMOTION_SOURCE_MANIFEST_SHA256_INVALID",
    )
    if math_hash != manifest_hash:
        raise ValueError("NFL_PROMOTION_MANIFEST_BINDING_MISMATCH")

    math_code_sha = _git_sha(math_artifact.get("code_git_sha"), "NFL_PROMOTION_MATH_CODE_SHA_INVALID")
    history_code_sha = _git_sha(
        historical_evidence.get("code_git_sha"),
        "NFL_PROMOTION_HISTORY_CODE_SHA_INVALID",
    )
    if math_code_sha != history_code_sha:
        raise ValueError("NFL_PROMOTION_CODE_SHA_MISMATCH")

    if historical_evidence.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_PROMOTION_MODEL_ID_MISMATCH")
    if historical_evidence.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_PROMOTION_FEATURE_CONTRACT_MISMATCH")

    if ci_attested:
        ci_identity = _verify_ci_attestation(
            ci_attestation,
            code_git_sha=math_code_sha,
            source_manifest_sha256=manifest_hash,
        )
    else:
        if ci_attestation is not None:
            raise ValueError("NFL_CI_ATTESTATION_STATE_CONTRADICTION")
        ci_identity = None

    math_attestation = attest_validated_math(math_artifact)
    promotion_raw = _mapping(historical_evidence.get("promotion_evidence")) or {}

    clv_raw: Mapping[str, Any] = {}
    clv_log_identity: dict[str, Any] | None = None
    if clv_evidence is not None:
        try:
            clv_schema = int(clv_evidence.get("schema_version", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("NFL_CLV_SCHEMA_INVALID") from exc
        if clv_schema != _EXPECTED_CLV_SCHEMA:
            raise ValueError("NFL_CLV_SCHEMA_INVALID")
        if str(clv_evidence.get("sport") or "").strip().lower() != "nfl":
            raise ValueError("NFL_CLV_SPORT_MISMATCH")
        if clv_evidence.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
            raise ValueError("NFL_CLV_MODEL_ID_MISMATCH")
        if clv_evidence.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
            raise ValueError("NFL_CLV_FEATURE_CONTRACT_MISMATCH")
        if clv_evidence.get("clv_probability_reference") != _EXPECTED_CLV_REFERENCE:
            raise ValueError("NFL_CLV_PROBABILITY_REFERENCE_INVALID")
        if clv_evidence.get("forward_time_contract") != _EXPECTED_CLV_FORWARD_TIME:
            raise ValueError("NFL_CLV_FORWARD_TIME_CONTRACT_INVALID")
        if clv_evidence.get("close_book_contract") != _EXPECTED_CLV_BOOK:
            raise ValueError("NFL_CLV_CLOSE_BOOK_CONTRACT_INVALID")
        clv_code_sha = _git_sha(clv_evidence.get("code_git_sha"), "NFL_CLV_CODE_SHA_INVALID")
        if clv_code_sha != math_code_sha:
            raise ValueError("NFL_CLV_CODE_SHA_MISMATCH")

        markets_payload, official_logged = _clv_bucket(
            clv_evidence.get("markets"),
            required_error="NFL_CLV_MARKETS_REQUIRED",
            row_error_prefix="NFL_CLV_OFFICIAL",
        )
        rejected_payload, rejected_logged = _clv_bucket(
            clv_evidence.get("rejected_markets"),
            required_error="NFL_CLV_REJECTED_MARKETS_REQUIRED",
            row_error_prefix="NFL_CLV_REJECTED",
        )
        decision_count = _count(
            clv_evidence.get("decision_count"), "NFL_CLV_DECISION_COUNT_INVALID"
        )
        close_count = _count(
            clv_evidence.get("close_count"), "NFL_CLV_CLOSE_COUNT_INVALID"
        )
        unique_count = _count(
            clv_evidence.get("unique_observation_count"),
            "NFL_CLV_UNIQUE_OBSERVATION_COUNT_INVALID",
        )
        if decision_count != close_count:
            raise ValueError("NFL_CLV_DECISION_CLOSE_COUNT_MISMATCH")
        if unique_count != decision_count:
            raise ValueError("NFL_CLV_UNIQUE_OBSERVATION_COUNT_MISMATCH")
        summarized_count = official_logged + rejected_logged
        if summarized_count != unique_count:
            raise ValueError("NFL_CLV_MARKET_COUNT_MISMATCH")

        clv_raw = markets_payload
        clv_log_identity = {
            "schema_version": _EXPECTED_CLV_SCHEMA,
            "sport": "nfl",
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": clv_code_sha,
            "clv_probability_reference": _EXPECTED_CLV_REFERENCE,
            "forward_time_contract": _EXPECTED_CLV_FORWARD_TIME,
            "close_book_contract": _EXPECTED_CLV_BOOK,
            "decision_count": decision_count,
            "close_count": close_count,
            "unique_observation_count": unique_count,
            "summarized_observation_count": summarized_count,
            "rejected_observation_count": rejected_logged,
            "decision_log_sha256": _sha256(
                clv_evidence.get("decision_log_sha256"), "NFL_CLV_DECISION_LOG_SHA256_INVALID"
            ),
            "close_log_sha256": _sha256(
                clv_evidence.get("close_log_sha256"), "NFL_CLV_CLOSE_LOG_SHA256_INVALID"
            ),
        }

    markets: list[str] = []
    seen: set[str] = set()
    for raw in declared_markets:
        market = str(raw).strip().lower()
        if market and market not in seen:
            seen.add(market)
            markets.append(market)
    if not markets:
        raise ValueError("NFL_DECLARED_MARKETS_REQUIRED")

    registry: dict[str, dict[str, Any]] = {}
    for market in markets:
        history = _mapping(promotion_raw.get(market))
        calibration = _mapping(history.get("calibration")) if history is not None else None
        clv = _mapping(clv_raw.get(market))
        fold_wins = int(history.get("fold_wins", 0)) if history is not None else 0
        fold_total = int(history.get("fold_total", 0)) if history is not None else 0
        if fold_wins < 0 or fold_total < 0 or fold_wins > fold_total:
            raise ValueError(f"NFL_FOLD_EVIDENCE_INVALID:{market}")

        if calibration is None:
            calibration_max, calibration_threshold = 1.0, 0.0
        else:
            raw_max = calibration.get("max_bin_deviation")
            raw_threshold = calibration.get("threshold")
            calibration_max = float(raw_max) if raw_max is not None else 1.0
            calibration_threshold = float(raw_threshold) if raw_threshold is not None else 0.0
            if calibration_max < 0 or calibration_threshold < 0:
                raise ValueError(f"NFL_CALIBRATION_EVIDENCE_INVALID:{market}")
            if calibration.get("pass") is True and calibration_max > calibration_threshold:
                raise ValueError(f"NFL_CALIBRATION_PASS_CONTRADICTION:{market}")

        logged_plays = int(clv.get("logged_plays", 0)) if clv is not None else 0
        mean_clv = float(clv.get("mean_clv", 0.0)) if clv is not None else 0.0
        clv_t_stat = float(clv.get("clv_t_stat", 0.0)) if clv is not None else 0.0
        if logged_plays < 0:
            raise ValueError(f"NFL_CLV_EVIDENCE_INVALID:{market}")

        evaluated = evaluate_football_promotion_from_math_artifact(
            math_artifact,
            fold_wins=fold_wins,
            fold_total=fold_total,
            ci_attested=ci_attested,
            calibration_max_bin_deviation=calibration_max,
            calibration_threshold=calibration_threshold,
            logged_plays=logged_plays,
            mean_clv=mean_clv,
            clv_t_stat=clv_t_stat,
        )
        stage = str(evaluated["stage"])
        registry[market] = {
            "stage": stage,
            "eligible": stage == "DEPLOYED",
            "reason": _reason(
                stage=stage, history=history, calibration=calibration,
                ci_attested=ci_attested, clv=clv,
            ),
            "fold_wins": fold_wins,
            "fold_total": fold_total,
            "fold_win_rate": (fold_wins / fold_total) if fold_total else None,
            "calibration": dict(calibration) if calibration is not None else None,
            "ci_attested": ci_attested,
            "clv": dict(clv) if clv is not None else None,
        }

    return {
        "schema_version": 8,
        "sport": "nfl",
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "code_git_sha": math_code_sha,
        "source_sha256": math_hash,
        "source_manifest_sha256": manifest_hash,
        "math_attestation": math_attestation,
        "ci_attestation": ci_identity,
        "clv_log_identity": clv_log_identity,
        "markets": registry,
        "deployed_markets": sorted(market for market, row in registry.items() if row["eligible"]),
    }
