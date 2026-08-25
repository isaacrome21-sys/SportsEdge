"""Fail-closed per-market NFL promotion registry.

Structural implementation never implies promotion. This layer composes the
canonical football ladder with hash-bound math/history evidence, held-out
calibration, an external CI attestation state, and forward CLV evidence.
Missing market evidence is represented explicitly and cannot inherit another
market's stage. Historical evidence must also be produced by the exact
production NFL M2 feature/model contract; a simpler challenger cannot promote
another model by accident.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sportsedge.core.promotion.football import evaluate_football_promotion_from_math_artifact
from sportsedge.core.validation.math_attestation import attest_validated_math
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _source_hash(value: Mapping[str, Any], name: str) -> str:
    raw = str(value.get("source_sha256") or "").strip().lower()
    if len(raw) != 64:
        raise ValueError(f"{name}_SOURCE_SHA256_INVALID")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise ValueError(f"{name}_SOURCE_SHA256_INVALID") from exc
    return raw


def _reason(
    *,
    stage: str,
    history: Mapping[str, Any] | None,
    calibration: Mapping[str, Any] | None,
    ci_attested: bool,
    clv: Mapping[str, Any] | None,
) -> str:
    if stage == "BLOCKED_MATH":
        return "MATH_ATTESTATION_FAILED"
    if stage == "VALIDATED_MATH":
        if history is None:
            return "WALKFORWARD_EVIDENCE_MISSING"
        return "FOLD_WIN_RATE_BELOW_THRESHOLD"
    if stage == "PRODUCTION_LOGIC_PASS":
        if calibration is None:
            return "CALIBRATION_EVIDENCE_MISSING"
        if calibration.get("pass") is not True:
            return "CALIBRATION_GATE_FAILED"
        if not ci_attested:
            return "CI_ATTESTATION_MISSING"
        return "CI_OR_CALIBRATION_GATE_NOT_ATTESTED"
    if stage == "CI_ATTESTED":
        if clv is None:
            return "CLV_EVIDENCE_MISSING"
        return "CLV_GATE_NOT_MET"
    if stage == "DEPLOYED":
        return "ALL_PROMOTION_GATES_PASS"
    return "UNKNOWN_PROMOTION_STAGE"


def build_nfl_promotion_registry(
    math_artifact: Mapping[str, Any],
    historical_evidence: Mapping[str, Any],
    *,
    declared_markets: Iterable[str],
    ci_attested: bool = False,
    clv_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate every declared NFL market independently.

    ``ci_attested`` must come from executable evidence outside this function; the
    registry cannot attest its own workflow. ``clv_evidence`` is expected to be
    forward decision-vs-close evidence. Missing CLV never defaults to pass.
    """
    if not isinstance(ci_attested, bool):
        raise ValueError("CI_ATTESTED_STATE_INVALID")
    math_hash = _source_hash(math_artifact, "MATH")
    history_hash = _source_hash(historical_evidence, "HISTORY")
    if math_hash != history_hash:
        raise ValueError("NFL_PROMOTION_SOURCE_HASH_MISMATCH")

    if historical_evidence.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_PROMOTION_MODEL_ID_MISMATCH")
    if historical_evidence.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_PROMOTION_FEATURE_CONTRACT_MISMATCH")

    math_attestation = attest_validated_math(math_artifact)
    promotion_raw = _mapping(historical_evidence.get("promotion_evidence")) or {}
    clv_raw: Mapping[str, Mapping[str, Any]] = clv_evidence or {}

    markets = []
    seen: set[str] = set()
    for raw in declared_markets:
        market = str(raw).strip().lower()
        if not market or market in seen:
            continue
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
            calibration_max = 1.0
            calibration_threshold = 0.0
        else:
            raw_max = calibration.get("max_bin_deviation")
            raw_threshold = calibration.get("threshold")
            calibration_max = float(raw_max) if raw_max is not None else 1.0
            calibration_threshold = float(raw_threshold) if raw_threshold is not None else 0.0
            if calibration_max < 0 or calibration_threshold < 0:
                raise ValueError(f"NFL_CALIBRATION_EVIDENCE_INVALID:{market}")
            numeric_pass = calibration_max <= calibration_threshold
            if calibration.get("pass") is True and not numeric_pass:
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
                stage=stage,
                history=history,
                calibration=calibration,
                ci_attested=ci_attested,
                clv=clv,
            ),
            "fold_wins": fold_wins,
            "fold_total": fold_total,
            "fold_win_rate": (fold_wins / fold_total) if fold_total else None,
            "calibration": dict(calibration) if calibration is not None else None,
            "ci_attested": ci_attested,
            "clv": dict(clv) if clv is not None else None,
        }

    return {
        "schema_version": 1,
        "sport": "nfl",
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "source_sha256": math_hash,
        "math_attestation": math_attestation,
        "markets": registry,
        "deployed_markets": sorted(market for market, row in registry.items() if row["eligible"]),
    }
