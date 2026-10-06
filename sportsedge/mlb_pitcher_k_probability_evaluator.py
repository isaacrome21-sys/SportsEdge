"""Deterministic evaluator for the frozen MLB pitcher-K probability candidate.

This module is research-only. It selects hyperparameters on the preregistered
2023/2024 development split, refits on 2023+2024, and performs the single
candidate-specific 2025 comparison against PIT-matched incumbent probabilities.
It never emits production model_p or betting authority.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import floor, log
import random
from typing import Any, Mapping, Sequence

from .mlb_pitcher_k_probability_candidate import (
    HALF_LINES,
    fit_payload,
    fit_rate_model,
    predict_k_rate,
    price_threshold,
    projected_batters_faced,
    select_hyperparameters,
)

TRAIN_SEASON = 2023
VALIDATION_SEASON = 2024
TEST_SEASON = 2025
TYPICAL_LINES = (3.5, 4.5, 5.5, 6.5)
MIN_TEST_STARTS = 500
BOOT_REPS = 2000
BOOT_SEED = 20261006
CI_LEVEL = 0.95
AUTHORITY = {
    "model_p": False,
    "truth_gate": False,
    "promotion": False,
    "staking": False,
    "official": False,
    "bettor_facing_release": False,
}


class PitcherKProbabilityEvaluationError(ValueError):
    pass


def _season(row: Mapping[str, Any]) -> int:
    try:
        value = int(row.get("season"))
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError("row season required") from exc
    if value not in {TRAIN_SEASON, VALIDATION_SEASON, TEST_SEASON}:
        raise PitcherKProbabilityEvaluationError("row season outside frozen split")
    return value


def _pitcher_id(row: Mapping[str, Any]) -> str:
    value = str(row.get("pitcher_id") or "").strip()
    if not value:
        raise PitcherKProbabilityEvaluationError("pitcher_id required")
    return value


def _realized_k(row: Mapping[str, Any]) -> int:
    try:
        value = int(row.get("realized_strikeouts"))
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError("realized_strikeouts required") from exc
    if value < 0:
        raise PitcherKProbabilityEvaluationError("realized_strikeouts invalid")
    return value


def _probability(value: Any, name: str) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityEvaluationError(f"{name} must be numeric") from exc
    if not 0.0 <= p <= 1.0:
        raise PitcherKProbabilityEvaluationError(f"{name} outside [0,1]")
    return p


def _incumbent_probs(row: Mapping[str, Any]) -> dict[float, float]:
    raw = row.get("incumbent_p_over")
    if not isinstance(raw, Mapping):
        raise PitcherKProbabilityEvaluationError("incumbent_p_over mapping required on test rows")
    out = {}
    for line in HALF_LINES:
        value = None
        for key in (line, str(line), f"{line:.1f}"):
            if key in raw:
                value = raw[key]
                break
        if value is None:
            raise PitcherKProbabilityEvaluationError(f"incumbent probability missing for {line:.1f}")
        out[float(line)] = _probability(value, f"incumbent_p_over[{line:.1f}]")
    return out


def _candidate_probs(row: Mapping[str, Any], fit, concentration: float) -> dict[float, float]:
    candidate = row.get("candidate")
    if not isinstance(candidate, Mapping):
        raise PitcherKProbabilityEvaluationError("candidate bundle required")
    return {
        float(line): float(
            price_threshold(candidate, fit, concentration=concentration, line=float(line))[
                "candidate_p_over"
            ]
        )
        for line in HALF_LINES
    }


def _rps(probs: Mapping[float, float], realized_k: int) -> float:
    values = []
    for line in HALF_LINES:
        y = 1.0 if realized_k > line else 0.0
        values.append((float(probs[float(line)]) - y) ** 2)
    return float(sum(values) / len(values))


def _log_loss(p: float, y: int) -> float:
    q = min(1.0 - 1e-12, max(1e-12, float(p)))
    return float(-(y * log(q) + (1 - y) * log(1.0 - q)))


def _ece(pairs: Sequence[tuple[float, int]]) -> float:
    if not pairs:
        raise PitcherKProbabilityEvaluationError("ECE pairs required")
    bins: list[list[tuple[float, int]]] = [[] for _ in range(10)]
    for p, y in pairs:
        bins[min(9, int(float(p) * 10.0))].append((float(p), int(y)))
    total = len(pairs)
    value = 0.0
    for bucket in bins:
        if not bucket:
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        mean_y = sum(y for _, y in bucket) / len(bucket)
        value += len(bucket) / total * abs(mean_p - mean_y)
    return float(value)


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise PitcherKProbabilityEvaluationError("quantile values required")
    xs = sorted(float(v) for v in values)
    pos = (len(xs) - 1) * float(q)
    lo = int(floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return float(xs[lo] * (1.0 - frac) + xs[hi] * frac)


def _cluster_ci(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[_pitcher_id(row)].append(float(row["rps_diff"]))
    if not grouped:
        raise PitcherKProbabilityEvaluationError("test clusters required")
    keys = sorted(grouped)
    rng = random.Random(BOOT_SEED)
    boot = []
    for _ in range(BOOT_REPS):
        sampled = [keys[rng.randrange(len(keys))] for _ in keys]
        values = [value for key in sampled for value in grouped[key]]
        boot.append(sum(values) / len(values))
    point = sum(value for vals in grouped.values() for value in vals) / sum(
        len(vals) for vals in grouped.values()
    )
    alpha = (1.0 - CI_LEVEL) / 2.0
    return {
        "value": float(point),
        "lo": _quantile(boot, alpha),
        "hi": _quantile(boot, 1.0 - alpha),
        "clusters": len(keys),
        "reps": BOOT_REPS,
        "seed": BOOT_SEED,
    }


def evaluate_pitcher_k_candidate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
        raise PitcherKProbabilityEvaluationError("evaluation rows required")
    clean = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise PitcherKProbabilityEvaluationError("evaluation row must be object")
        _season(row)
        _pitcher_id(row)
        _realized_k(row)
        clean.append(dict(row))

    train = [row for row in clean if _season(row) == TRAIN_SEASON]
    validation = [row for row in clean if _season(row) == VALIDATION_SEASON]
    test = [row for row in clean if _season(row) == TEST_SEASON]
    if not train or not validation or not test:
        raise PitcherKProbabilityEvaluationError("all frozen split seasons require eligible rows")

    selected = select_hyperparameters(train, validation)
    alpha = float(selected["ridge_alpha"])
    concentration = float(selected["concentration"])
    final_fit = fit_rate_model(train + validation, ridge_alpha=alpha)

    scored = []
    candidate_pairs: list[tuple[float, int]] = []
    incumbent_pairs: list[tuple[float, int]] = []
    candidate_ll = []
    incumbent_ll = []
    count_errors = []

    for row in test:
        realized_k = _realized_k(row)
        candidate_probs = _candidate_probs(row, final_fit, concentration)
        incumbent_probs = _incumbent_probs(row)
        candidate_rps = _rps(candidate_probs, realized_k)
        incumbent_rps = _rps(incumbent_probs, realized_k)
        scored.append(
            {
                "pitcher_id": _pitcher_id(row),
                "candidate_rps": candidate_rps,
                "incumbent_rps": incumbent_rps,
                "rps_diff": candidate_rps - incumbent_rps,
            }
        )
        for line in TYPICAL_LINES:
            y = int(realized_k > line)
            cp = candidate_probs[line]
            ip = incumbent_probs[line]
            candidate_pairs.append((cp, y))
            incumbent_pairs.append((ip, y))
            candidate_ll.append(_log_loss(cp, y))
            incumbent_ll.append(_log_loss(ip, y))

        candidate = row["candidate"]
        expected_count = predict_k_rate(final_fit, candidate) * projected_batters_faced(candidate)
        count_errors.append(abs(float(expected_count) - realized_k))

    ci = _cluster_ci(scored)
    candidate_log_loss = float(sum(candidate_ll) / len(candidate_ll))
    incumbent_log_loss = float(sum(incumbent_ll) / len(incumbent_ll))
    candidate_ece = _ece(candidate_pairs)
    incumbent_ece = _ece(incumbent_pairs)
    blockers = []
    if len(test) < MIN_TEST_STARTS:
        blockers.append(f"MIN_CANDIDATE_TEST_STARTS:{len(test)}<{MIN_TEST_STARTS}")
    if float(ci["hi"]) >= 0.0:
        blockers.append("RPS_DIFFERENCE_CI_HIGH_NOT_BELOW_ZERO")
    if candidate_ece > incumbent_ece + 0.005:
        blockers.append("CANDIDATE_ECE_WORSE_THAN_INCUMBENT_PLUS_0_005")
    if candidate_log_loss > incumbent_log_loss:
        blockers.append("CANDIDATE_LOG_LOSS_WORSE_THAN_INCUMBENT")

    result = {
        "schema": "MLB_PITCHER_K_PROBABILITY_EVALUATION_V1",
        "candidate_family": "RIDGE_LOGIT_K_RATE_BETA_BINOMIAL_V1",
        "authority": dict(AUTHORITY),
        "split": {
            "training_season": TRAIN_SEASON,
            "validation_season": VALIDATION_SEASON,
            "candidate_test_season": TEST_SEASON,
            "training_rows": len(train),
            "validation_rows": len(validation),
            "candidate_test_rows": len(test),
        },
        "selection": {
            "ridge_alpha": alpha,
            "concentration": concentration,
            "validation_mean_rps": float(selected["mean_rps"]),
            "grid_scores": selected["grid_scores"],
        },
        "final_fit": fit_payload(final_fit),
        "metrics": {
            "candidate_mean_rps": float(sum(row["candidate_rps"] for row in scored) / len(scored)),
            "incumbent_mean_rps": float(sum(row["incumbent_rps"] for row in scored) / len(scored)),
            "candidate_minus_incumbent_rps_ci": ci,
            "candidate_typical_line_log_loss": candidate_log_loss,
            "incumbent_typical_line_log_loss": incumbent_log_loss,
            "candidate_typical_line_ece": candidate_ece,
            "incumbent_typical_line_ece": incumbent_ece,
            "candidate_count_mae": float(sum(count_errors) / len(count_errors)),
        },
        "passes_development_gate": not blockers,
        "blockers": blockers,
        "model_p_eligible": False,
        "deployment": False,
    }
    digest_payload = dict(result)
    result["report_sha256"] = sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result
