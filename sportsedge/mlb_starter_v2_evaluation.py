"""Pure gate logic for the one-shot MLB starter-v2 August evaluation."""
from __future__ import annotations

from statistics import fmean
from typing import Any, Mapping

from .source_lineage import canonical_json_sha256

EVALUATION_VERSION = "mlb_starter_v2_august_gate_v1"
EVALUATION_LINES = (6.5, 7.5, 8.5, 9.5)
SIMULATIONS_PER_GAME_MODEL = 20_000

EVALUATION_CONFIG = {
    "evaluation_version": EVALUATION_VERSION,
    "coverage_start": "2026-08-01",
    "coverage_end": "2026-08-31",
    "game_total_lines": list(EVALUATION_LINES),
    "simulations_per_game_model": SIMULATIONS_PER_GAME_MODEL,
    "baseline": "defense_blend",
    "candidate": "starter_v2",
    "gate": "candidate strictly improves mean_abs_calibration_gap AND mean_brier",
}
EVALUATION_CONFIG_SHA256 = canonical_json_sha256(EVALUATION_CONFIG)


def promotion_gate(*, baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered dual gate to summarize_predictions outputs."""
    by_base = baseline.get("by_event") or {}
    by_candidate = candidate.get("by_event") or {}
    line_rows: list[dict[str, Any]] = []
    for line in EVALUATION_LINES:
        event = f"GAME_TOTAL_OVER_{line:g}"
        b = by_base.get(event)
        c = by_candidate.get(event)
        if not isinstance(b, Mapping) or not isinstance(c, Mapping):
            raise ValueError(f"missing locked gate event {event}")
        if int(b.get("n", 0)) != int(c.get("n", 0)) or int(b.get("n", 0)) <= 0:
            raise ValueError(f"sample mismatch for {event}")
        observed_b = float(b["observed_rate"])
        observed_c = float(c["observed_rate"])
        if abs(observed_b - observed_c) > 1e-12:
            raise ValueError(f"outcome mismatch for {event}")
        line_rows.append({
            "line": float(line),
            "n": int(b["n"]),
            "observed_rate": observed_b,
            "baseline_predicted_rate": float(b["mean_predicted_p"]),
            "candidate_predicted_rate": float(c["mean_predicted_p"]),
            "baseline_abs_calibration_gap": abs(float(b["mean_predicted_p"]) - observed_b),
            "candidate_abs_calibration_gap": abs(float(c["mean_predicted_p"]) - observed_b),
            "baseline_brier": float(b["brier"]),
            "candidate_brier": float(c["brier"]),
        })

    baseline_gap = float(fmean(row["baseline_abs_calibration_gap"] for row in line_rows))
    candidate_gap = float(fmean(row["candidate_abs_calibration_gap"] for row in line_rows))
    baseline_brier = float(fmean(row["baseline_brier"] for row in line_rows))
    candidate_brier = float(fmean(row["candidate_brier"] for row in line_rows))
    calibration_pass = candidate_gap < baseline_gap
    brier_pass = candidate_brier < baseline_brier
    passed = calibration_pass and brier_pass
    return {
        "evaluation_config_sha256": EVALUATION_CONFIG_SHA256,
        "lines": line_rows,
        "mean_abs_calibration_gap": {
            "defense_blend": baseline_gap,
            "starter_v2": candidate_gap,
            "delta_candidate_minus_baseline": candidate_gap - baseline_gap,
            "pass": calibration_pass,
        },
        "mean_brier": {
            "defense_blend": baseline_brier,
            "starter_v2": candidate_brier,
            "delta_candidate_minus_baseline": candidate_brier - baseline_brier,
            "pass": brier_pass,
        },
        "gate_pass": passed,
        "decision": "PASS_PROVISIONAL" if passed else "FAIL_KEEP_DEFENSE_BLEND",
    }
