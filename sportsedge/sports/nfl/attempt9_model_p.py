"""Governed probability wrapper for the frozen NFL attempt-9 owner.

The frozen attempt-9 runtime emits only market-blind point forecasts.  This
module converts those point forecasts into market-threshold probabilities using
an immutable, selection-exposed historical calibration artifact.  The wrapper
creates Model_P, but it does not promote a market, attest calibration, mark a
model deployed, grant Truth-Gate authority, authorize OFFICIAL bets, or stake.
Those are separate prospective evidence decisions.

Integer spread/total thresholds fail closed because attempt-9 v1 has no
validated discrete push-mass model.  Half-point (or otherwise non-integer)
thresholds have zero push probability by score arithmetic and are eligible for
a probability output.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import erf, isfinite, sqrt
from typing import Any, Iterable, Mapping

MODEL_P_SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_MODEL_P_ARTIFACT_V1"
MODEL_P_ID = "nfl_attempt9_exponential_recency_weighted_model_p_v1"
CANDIDATE_ID = "nfl_attempt9_exponential_recency_weighted_baseline"
CALIBRATION_CONTRACT = "SELECTION_EXPOSED_ISOTONIC_NOT_PROMOTION_EVIDENCE_V1"
MODEL_P_STATUS = "FROZEN_MODEL_P_WRAPPER_NOT_PROMOTED"


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _finite(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not isfinite(out):
        raise ValueError(error)
    return out


def _clip_probability(value: float) -> float:
    return min(1.0 - 1e-9, max(1e-9, float(value)))


def _normal_cdf(x: float, *, mean: float, sigma: float) -> float:
    if sigma <= 0.0 or not isfinite(sigma):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_SIGMA_INVALID")
    return 0.5 * (1.0 + erf((x - mean) / (sigma * sqrt(2.0))))


def fit_isotonic_blocks(
    scores: Iterable[float], outcomes: Iterable[int]
) -> list[dict[str, Any]]:
    """Fit deterministic PAV blocks for a serialized probability mapping."""
    x = [float(value) for value in scores]
    y = [int(value) for value in outcomes]
    if len(x) != len(y) or not x:
        raise ValueError("NFL_ATTEMPT9_CALIBRATION_INPUT_LENGTH")
    if any(not isfinite(value) or value < 0.0 or value > 1.0 for value in x):
        raise ValueError("NFL_ATTEMPT9_CALIBRATION_SCORE_INVALID")
    if any(value not in (0, 1) for value in y):
        raise ValueError("NFL_ATTEMPT9_CALIBRATION_OUTCOME_INVALID")

    grouped: list[dict[str, Any]] = []
    for score, outcome in sorted(zip(x, y), key=lambda row: row[0]):
        if grouped and score == grouped[-1]["hi"]:
            block = grouped[-1]
            old_weight = int(block["weight"])
            new_weight = old_weight + 1
            block["mean"] = (float(block["mean"]) * old_weight + outcome) / new_weight
            block["weight"] = new_weight
        else:
            grouped.append({"lo": score, "hi": score, "weight": 1, "mean": float(outcome)})

    blocks: list[dict[str, Any]] = []
    for source in grouped:
        blocks.append(dict(source))
        while len(blocks) >= 2 and float(blocks[-2]["mean"]) > float(blocks[-1]["mean"]):
            right = blocks.pop()
            left = blocks.pop()
            weight = int(left["weight"]) + int(right["weight"])
            blocks.append(
                {
                    "lo": float(left["lo"]),
                    "hi": float(right["hi"]),
                    "weight": weight,
                    "mean": (
                        float(left["mean"]) * int(left["weight"])
                        + float(right["mean"]) * int(right["weight"])
                    )
                    / weight,
                }
            )
    return blocks


def apply_isotonic_blocks(blocks: Iterable[Mapping[str, Any]], score: float) -> float:
    rows = [dict(row) for row in blocks]
    if not rows:
        raise ValueError("NFL_ATTEMPT9_CALIBRATION_BLOCKS_MISSING")
    value = _finite(score, "NFL_ATTEMPT9_MODEL_P_RAW_PROBABILITY_INVALID")
    if not 0.0 <= value <= 1.0:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_RAW_PROBABILITY_INVALID")
    chosen = _finite(rows[-1].get("mean"), "NFL_ATTEMPT9_CALIBRATION_BLOCK_INVALID")
    previous_hi = -1.0
    for row in rows:
        lo = _finite(row.get("lo"), "NFL_ATTEMPT9_CALIBRATION_BLOCK_INVALID")
        hi = _finite(row.get("hi"), "NFL_ATTEMPT9_CALIBRATION_BLOCK_INVALID")
        mean = _finite(row.get("mean"), "NFL_ATTEMPT9_CALIBRATION_BLOCK_INVALID")
        try:
            weight = int(row.get("weight"))
        except (TypeError, ValueError) as exc:
            raise ValueError("NFL_ATTEMPT9_CALIBRATION_BLOCK_INVALID") from exc
        if weight <= 0 or not (0.0 <= lo <= hi <= 1.0) or not 0.0 <= mean <= 1.0:
            raise ValueError("NFL_ATTEMPT9_CALIBRATION_BLOCK_INVALID")
        if lo < previous_hi:
            raise ValueError("NFL_ATTEMPT9_CALIBRATION_BLOCK_ORDER_INVALID")
        previous_hi = hi
        if value <= hi:
            chosen = mean
            break
    return _clip_probability(chosen)


def verify_model_p_artifact(artifact: Mapping[str, Any]) -> str:
    if artifact.get("schema_version") != MODEL_P_SCHEMA:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_ARTIFACT_SCHEMA_INVALID")
    if artifact.get("status") != MODEL_P_STATUS:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_ARTIFACT_STATUS_INVALID")
    if artifact.get("model_p_id") != MODEL_P_ID or artifact.get("candidate_id") != CANDIDATE_ID:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_IDENTITY_INVALID")
    authority = artifact.get("authority")
    if not isinstance(authority, Mapping):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_AUTHORITY_MISSING")
    if authority.get("creates_model_p") is not True:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_CREATION_AUTHORITY_INVALID")
    for key in (
        "historical_fit_promotion_authority",
        "deployed",
        "truth_gate_pass",
        "official_authority",
        "staking_authority",
    ):
        if authority.get(key) is not False:
            raise ValueError(f"NFL_ATTEMPT9_MODEL_P_AUTHORITY_INVALID:{key}")
    fit = artifact.get("calibration_fit")
    if not isinstance(fit, Mapping):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_CALIBRATION_FIT_MISSING")
    if fit.get("contract") != CALIBRATION_CONTRACT:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_CALIBRATION_CONTRACT_INVALID")
    if fit.get("role") != "SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE":
        raise ValueError("NFL_ATTEMPT9_MODEL_P_CALIBRATION_ROLE_INVALID")
    markets = artifact.get("markets")
    if not isinstance(markets, Mapping):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_MARKETS_MISSING")
    for market in ("spread", "total"):
        row = markets.get(market)
        if not isinstance(row, Mapping):
            raise ValueError(f"NFL_ATTEMPT9_MODEL_P_MARKET_MISSING:{market}")
        sigma = _finite(row.get("sigma"), f"NFL_ATTEMPT9_MODEL_P_SIGMA_INVALID:{market}")
        if sigma <= 0.0:
            raise ValueError(f"NFL_ATTEMPT9_MODEL_P_SIGMA_INVALID:{market}")
        apply_isotonic_blocks(row.get("calibration_blocks") or [], 0.5)
    expected = str(artifact.get("artifact_sha256") or "").lower()
    if len(expected) != 64:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_ARTIFACT_SHA_MISSING")
    payload = dict(artifact)
    payload.pop("artifact_sha256", None)
    actual = canonical_sha256(payload)
    if actual != expected:
        raise ValueError(f"NFL_ATTEMPT9_MODEL_P_ARTIFACT_SHA_MISMATCH:{actual}:{expected}")
    return expected


def _is_integer_line(line: float) -> bool:
    return abs(line - round(line)) <= 1e-12


def model_probability(
    artifact: Mapping[str, Any],
    *,
    market: str,
    raw_prediction: float,
    line: float,
    selection: str,
) -> dict[str, Any]:
    """Return Model_P at a non-integer market threshold.

    Spread line is canonical home handicap (e.g. -3.5 means home -3.5).
    Total line is the sportsbook game total.  Integer thresholds fail closed
    because v1 does not claim a validated push-mass model.
    """
    artifact_sha = verify_model_p_artifact(artifact)
    market_key = str(market).strip().lower()
    selection_key = str(selection).strip().lower()
    if market_key not in {"spread", "total"}:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_MARKET_UNSUPPORTED")
    allowed = {"spread": {"home", "away"}, "total": {"over", "under"}}[market_key]
    if selection_key not in allowed:
        raise ValueError("NFL_ATTEMPT9_MODEL_P_SELECTION_INVALID")
    prediction = _finite(raw_prediction, "NFL_ATTEMPT9_MODEL_P_RAW_PREDICTION_INVALID")
    threshold_line = _finite(line, "NFL_ATTEMPT9_MODEL_P_LINE_INVALID")
    if _is_integer_line(threshold_line):
        raise ValueError("NFL_ATTEMPT9_MODEL_P_PUSH_MODEL_REQUIRED_FOR_INTEGER_LINE")

    market_row = artifact["markets"][market_key]
    sigma = float(market_row["sigma"])
    if market_key == "spread":
        # Home cover: home margin + home handicap > 0.
        threshold = -threshold_line
        raw_home_or_over = 1.0 - _normal_cdf(threshold, mean=prediction, sigma=sigma)
    else:
        raw_home_or_over = 1.0 - _normal_cdf(threshold_line, mean=prediction, sigma=sigma)
    calibrated_home_or_over = apply_isotonic_blocks(
        market_row["calibration_blocks"], raw_home_or_over
    )
    if selection_key in {"away", "under"}:
        probability = _clip_probability(1.0 - calibrated_home_or_over)
    else:
        probability = calibrated_home_or_over
    return {
        "schema_version": "SPORTSEDGE_NFL_ATTEMPT9_MODEL_P_OUTPUT_V1",
        "model_p_id": MODEL_P_ID,
        "candidate_id": CANDIDATE_ID,
        "model_p_artifact_sha256": artifact_sha,
        "market": market_key,
        "selection": selection_key,
        "line": threshold_line,
        "raw_prediction": prediction,
        "raw_threshold_probability": _clip_probability(raw_home_or_over),
        "model_p": probability,
        "push_probability": 0.0,
        "calibration_contract": CALIBRATION_CONTRACT,
        "calibration_fit_role": "SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE",
        "promotion_authority": False,
        "deployed": False,
        "truth_gate_pass": False,
        "official_authority": False,
        "staking_authority": False,
    }
