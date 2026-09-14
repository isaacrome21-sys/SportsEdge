from __future__ import annotations

from dataclasses import dataclass

from .calibration import ProjectionCalibrationMetrics


@dataclass(frozen=True)
class ContestOutcomeMetrics:
    slate_count: int
    roi: float
    top_one_percent_rate: float
    max_drawdown: float

    def validate(self) -> None:
        if self.slate_count < 1:
            raise ValueError("DFS_PROMOTION_CONTEST_SLATE_COUNT_INVALID")
        if not 0.0 <= self.top_one_percent_rate <= 1.0:
            raise ValueError("DFS_PROMOTION_TOP1_INVALID")
        if self.max_drawdown < 0.0:
            raise ValueError("DFS_PROMOTION_DRAWDOWN_INVALID")


@dataclass(frozen=True)
class ProjectionPromotionDecision:
    promoted: bool
    reason: str
    calibration_improved: bool
    error_improved_without_calibration_regression: bool
    error_regression_ok: bool
    contest_roi_veto_ok: bool
    contest_drawdown_veto_ok: bool
    candidate: ProjectionCalibrationMetrics
    baseline: ProjectionCalibrationMetrics


def evaluate_projection_promotion(
    *,
    candidate: ProjectionCalibrationMetrics,
    baseline: ProjectionCalibrationMetrics,
    candidate_contest: ContestOutcomeMetrics | None = None,
    baseline_contest: ContestOutcomeMetrics | None = None,
    min_player_observations: int = 500,
    min_calibration_improvement: float = 0.002,
    min_rmse_improvement_fraction: float = 0.01,
    max_calibration_regression: float = 0.002,
    max_error_regression_fraction: float = 0.015,
    max_roi_worsening: float = 0.10,
    max_drawdown_worsening: float = 0.15,
) -> ProjectionPromotionDecision:
    """Calibration-first DFS projection promotion.

    Promotion authority comes from hundreds/thousands of player-level forecast
    observations rather than a small number of contest outcomes. Contest ROI and
    drawdown can veto an otherwise-valid model, but they cannot create a pass.
    Top-1% finish rate is reported by callers but is not a positive promotion gate.
    """
    candidate.validate()
    baseline.validate()
    if candidate.observations < min_player_observations or baseline.observations < min_player_observations:
        return ProjectionPromotionDecision(
            promoted=False,
            reason="BLOCKED:INSUFFICIENT_PLAYER_OBSERVATIONS",
            calibration_improved=False,
            error_improved_without_calibration_regression=False,
            error_regression_ok=False,
            contest_roi_veto_ok=True,
            contest_drawdown_veto_ok=True,
            candidate=candidate,
            baseline=baseline,
        )

    calibration_improved = (
        candidate.quantile_calibration_error
        <= baseline.quantile_calibration_error - min_calibration_improvement
    )
    error_improved = (
        candidate.rmse <= baseline.rmse * (1.0 - min_rmse_improvement_fraction)
        and candidate.quantile_calibration_error
        <= baseline.quantile_calibration_error + max_calibration_regression
    )
    error_regression_ok = (
        candidate.rmse <= baseline.rmse * (1.0 + max_error_regression_fraction)
        and candidate.mae <= baseline.mae * (1.0 + max_error_regression_fraction)
    )

    roi_veto_ok = True
    drawdown_veto_ok = True
    if (candidate_contest is None) != (baseline_contest is None):
        raise ValueError("DFS_PROMOTION_CONTEST_EVIDENCE_MUST_BE_PAIRED")
    if candidate_contest is not None and baseline_contest is not None:
        candidate_contest.validate()
        baseline_contest.validate()
        roi_veto_ok = candidate_contest.roi >= baseline_contest.roi - max_roi_worsening
        drawdown_veto_ok = (
            candidate_contest.max_drawdown
            <= baseline_contest.max_drawdown + max_drawdown_worsening
        )

    positive_model_gate = calibration_improved or error_improved
    promoted = bool(
        positive_model_gate
        and error_regression_ok
        and roi_veto_ok
        and drawdown_veto_ok
    )
    blockers: list[str] = []
    if not positive_model_gate:
        blockers.append("NO_CALIBRATION_OR_ERROR_IMPROVEMENT")
    if not error_regression_ok:
        blockers.append("FORECAST_ERROR_REGRESSION")
    if not roi_veto_ok:
        blockers.append("CONTEST_ROI_VETO")
    if not drawdown_veto_ok:
        blockers.append("CONTEST_DRAWDOWN_VETO")
    reason = "CALIBRATION_HOLDOUT_PASS" if promoted else "BLOCKED:" + ",".join(blockers)
    return ProjectionPromotionDecision(
        promoted=promoted,
        reason=reason,
        calibration_improved=calibration_improved,
        error_improved_without_calibration_regression=error_improved,
        error_regression_ok=error_regression_ok,
        contest_roi_veto_ok=roi_veto_ok,
        contest_drawdown_veto_ok=drawdown_veto_ok,
        candidate=candidate,
        baseline=baseline,
    )
