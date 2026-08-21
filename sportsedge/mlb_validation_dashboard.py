from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from sportsedge.mlb_truth_gate_eval import GateMetrics, evaluate_truth_gate


@dataclass(frozen=True)
class MLBValidationDashboardRow:
    market: str
    predictive_status: str
    infrastructure_status: str
    settled_bets: int
    settled_passes: int
    brier_score: float | None
    log_loss: float | None
    calibration_slope: float | None
    calibration_intercept: float | None
    calibration_mae: float | None
    mean_clv: float | None
    pct_beat_close: float | None
    model_sha: str
    feature_sha: str
    last_durable_evidence_timestamp: str | None
    uncertainty_enabled: bool
    mean_uncertainty_haircut: float | None
    pct_edges_haircut: float | None
    uncertainty_sha: str | None
    gate_quality_score: float | None
    gate_sample_size: int
    accepted_mean_clv: float | None
    accepted_pct_beat_close: float | None
    rejected_mean_clv: float | None
    rejected_pct_beat_close: float | None
    avoided_bad_bet_rate: float | None
    good_pass_fn_rate: float | None
    selectivity_ratio: float | None
    accepted_vs_rejected_clv_delta: float | None
    tier_monotonicity_status: str | None
    tier_monotonicity_score: float | None
    last_gate_eval_timestamp: str | None
    gate_evaluator_sha: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _uncertainty_stats(rows: list[Mapping[str, Any]]) -> tuple[float | None, float | None]:
    magnitudes = [float(r.get("uncertainty_haircut_magnitude", 0.0) or 0.0) for r in rows]
    if not magnitudes:
        return None, None
    return sum(magnitudes) / len(magnitudes), sum(x > 0 for x in magnitudes) / len(magnitudes)


def build_dashboard_row(*, market: str, rows: Iterable[Mapping[str, Any]], predictive_status: str,
                        infrastructure_status: str, model_sha: str, feature_sha: str,
                        last_durable_evidence_timestamp: str | None, uncertainty_enabled: bool,
                        uncertainty_sha: str | None = None, gate_evaluator_sha: str | None = None,
                        last_gate_eval_timestamp: str | None = None, brier_score: float | None = None,
                        log_loss: float | None = None, calibration_slope: float | None = None,
                        calibration_intercept: float | None = None, calibration_mae: float | None = None,
                        mean_clv: float | None = None, pct_beat_close: float | None = None,
                        minimum_gate_n: int = 300, minimum_per_tier: int = 150) -> MLBValidationDashboardRow:
    data = list(rows)
    gate: GateMetrics = evaluate_truth_gate(data, minimum_n=minimum_gate_n, minimum_per_tier=minimum_per_tier)
    mean_haircut, pct_haircut = _uncertainty_stats(data)
    settled_bets = sum(r.get("gate_decision") == "BET" and r.get("outcome") in {"WIN", "LOSS", "PUSH"} for r in data)
    settled_passes = sum(r.get("gate_decision") != "BET" and r.get("outcome") in {"WIN", "LOSS", "PUSH"} for r in data)
    return MLBValidationDashboardRow(
        market, predictive_status, infrastructure_status, settled_bets, settled_passes,
        brier_score, log_loss, calibration_slope, calibration_intercept, calibration_mae,
        mean_clv, pct_beat_close, model_sha, feature_sha, last_durable_evidence_timestamp,
        uncertainty_enabled, mean_haircut, pct_haircut, uncertainty_sha,
        gate.quality_score, gate.n_total, gate.accepted_mean_clv, gate.accepted_beat_close_rate,
        gate.rejected_mean_clv, gate.rejected_beat_close_rate, gate.avoided_bad_bets_rate,
        gate.good_pass_false_negative_rate, gate.selectivity_ratio, gate.clv_delta,
        gate.tier_monotonicity_status, gate.tier_monotonicity_score,
        last_gate_eval_timestamp, gate_evaluator_sha,
    )
