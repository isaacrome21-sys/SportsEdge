"""Deterministic SportsEdge CFB V2 model-replacement gate.

This gate is separate from CFB_TRUTH_GATE_V1. It compares the enriched V2 score model
against the current baseline on identical chronological outer folds and identical PIT
rows. Passing this gate never certifies a betting market by itself; production switch
also requires the frozen CFB Truth Gate to be OFFICIAL for every required main market.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable, Mapping


REQUIRED_MARKETS = ("MONEYLINE", "SPREAD", "TOTAL")


class CFBModelPromotionError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CFBModelPromotionError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBModelPromotionError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBModelPromotionError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class CFBModelComparisonMarket:
    market: str
    outer_forward_seasons: int
    predictive_rows: int
    economic_candidates: int
    baseline_brier: float
    candidate_brier: float
    paired_brier_delta_upper_95: float
    baseline_logloss: float
    candidate_logloss: float
    paired_logloss_delta_upper_95: float
    baseline_ece: float
    candidate_ece: float
    candidate_calibration_slope: float
    candidate_calibration_intercept: float
    baseline_mean_clv: float
    candidate_mean_clv: float
    baseline_roi_after_vig: float
    candidate_roi_after_vig: float
    recent_two_seasons_both_metrics_worse: bool
    candidate_truth_gate_status: str
    attestations_passed: bool
    baseline_key_number_max_abs_error: float | None = None
    candidate_key_number_max_abs_error: float | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "CFBModelComparisonMarket":
        return cls(
            market=str(row.get("market") or "").strip().upper(),
            outer_forward_seasons=int(row.get("outer_forward_seasons")),
            predictive_rows=int(row.get("predictive_rows")),
            economic_candidates=int(row.get("economic_candidates")),
            baseline_brier=_finite(row.get("baseline_brier"), "baseline_brier"),
            candidate_brier=_finite(row.get("candidate_brier"), "candidate_brier"),
            paired_brier_delta_upper_95=_finite(row.get("paired_brier_delta_upper_95"), "paired_brier_delta_upper_95"),
            baseline_logloss=_finite(row.get("baseline_logloss"), "baseline_logloss"),
            candidate_logloss=_finite(row.get("candidate_logloss"), "candidate_logloss"),
            paired_logloss_delta_upper_95=_finite(row.get("paired_logloss_delta_upper_95"), "paired_logloss_delta_upper_95"),
            baseline_ece=_finite(row.get("baseline_ece"), "baseline_ece"),
            candidate_ece=_finite(row.get("candidate_ece"), "candidate_ece"),
            candidate_calibration_slope=_finite(row.get("candidate_calibration_slope"), "candidate_calibration_slope"),
            candidate_calibration_intercept=_finite(row.get("candidate_calibration_intercept"), "candidate_calibration_intercept"),
            baseline_mean_clv=_finite(row.get("baseline_mean_clv"), "baseline_mean_clv"),
            candidate_mean_clv=_finite(row.get("candidate_mean_clv"), "candidate_mean_clv"),
            baseline_roi_after_vig=_finite(row.get("baseline_roi_after_vig"), "baseline_roi_after_vig"),
            candidate_roi_after_vig=_finite(row.get("candidate_roi_after_vig"), "candidate_roi_after_vig"),
            recent_two_seasons_both_metrics_worse=row.get("recent_two_seasons_both_metrics_worse") is True,
            candidate_truth_gate_status=str(row.get("candidate_truth_gate_status") or "").strip().upper(),
            attestations_passed=row.get("attestations_passed") is True,
            baseline_key_number_max_abs_error=None if row.get("baseline_key_number_max_abs_error") is None else _finite(row.get("baseline_key_number_max_abs_error"), "baseline_key_number_max_abs_error"),
            candidate_key_number_max_abs_error=None if row.get("candidate_key_number_max_abs_error") is None else _finite(row.get("candidate_key_number_max_abs_error"), "candidate_key_number_max_abs_error"),
        ).validate()

    def validate(self) -> "CFBModelComparisonMarket":
        if self.market not in REQUIRED_MARKETS:
            raise CFBModelPromotionError("PROMOTION_MARKET_INVALID")
        if self.outer_forward_seasons < 0 or self.predictive_rows < 0 or self.economic_candidates < 0:
            raise CFBModelPromotionError("PROMOTION_SAMPLE_COUNT_INVALID")
        for name in (
            "baseline_brier", "candidate_brier", "baseline_logloss", "candidate_logloss",
            "baseline_ece", "candidate_ece", "candidate_calibration_slope",
            "candidate_calibration_intercept", "baseline_mean_clv", "candidate_mean_clv",
            "baseline_roi_after_vig", "candidate_roi_after_vig",
            "paired_brier_delta_upper_95", "paired_logloss_delta_upper_95",
        ):
            _finite(getattr(self, name), name)
        if self.market == "SPREAD":
            if self.baseline_key_number_max_abs_error is None or self.candidate_key_number_max_abs_error is None:
                raise CFBModelPromotionError("SPREAD_KEY_NUMBER_EVIDENCE_REQUIRED")
        return self


@dataclass(frozen=True)
class CFBModelPromotionResult:
    status: str
    failures: tuple[str, ...]
    markets: tuple[CFBModelComparisonMarket, ...]

    @property
    def promote(self) -> bool:
        return self.status == "PROMOTE_V2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failures": list(self.failures),
            "markets": [asdict(row) for row in self.markets],
        }


def evaluate_cfb_model_v2_promotion(
    rows: Iterable[CFBModelComparisonMarket | Mapping[str, Any]],
    *,
    min_outer_forward_seasons: int = 4,
    min_predictive_rows_per_market: int = 500,
    min_economic_candidates_per_market: int = 200,
    calibration_slope_min: float = 0.90,
    calibration_slope_max: float = 1.10,
    max_abs_calibration_intercept: float = 0.03,
    max_ece: float = 0.025,
    max_ece_regression_vs_baseline: float = 0.002,
    spread_max_key_number_abs_error: float = 0.015,
    spread_max_key_number_regression_vs_baseline: float = 0.002,
) -> CFBModelPromotionResult:
    """Evaluate the frozen V2 replacement gate.

    Paired confidence limits must be computed upstream on identical held-out rows. A
    negative upper 95% limit means the candidate's loss is statistically lower than
    baseline at the chosen one-sided confidence level. No discretionary override exists.
    """

    normalized = tuple(
        row.validate() if isinstance(row, CFBModelComparisonMarket) else CFBModelComparisonMarket.from_mapping(row)
        for row in rows
    )
    by_market = {row.market: row for row in normalized}
    if len(by_market) != len(normalized):
        raise CFBModelPromotionError("PROMOTION_DUPLICATE_MARKET")
    if set(by_market) != set(REQUIRED_MARKETS):
        missing = sorted(set(REQUIRED_MARKETS) - set(by_market))
        extra = sorted(set(by_market) - set(REQUIRED_MARKETS))
        raise CFBModelPromotionError(
            "PROMOTION_MARKET_SET_INVALID:missing=" + ",".join(missing) + ";extra=" + ",".join(extra)
        )

    failures: list[str] = []
    for market in REQUIRED_MARKETS:
        row = by_market[market]
        prefix = market + ":"
        if row.outer_forward_seasons < int(min_outer_forward_seasons):
            failures.append(prefix + "FORWARD_SEASONS_INSUFFICIENT")
        if row.predictive_rows < int(min_predictive_rows_per_market):
            failures.append(prefix + "PREDICTIVE_SAMPLE_INSUFFICIENT")
        if row.economic_candidates < int(min_economic_candidates_per_market):
            failures.append(prefix + "ECONOMIC_SAMPLE_INSUFFICIENT")
        if row.candidate_brier > row.baseline_brier:
            failures.append(prefix + "BRIER_WORSE_THAN_BASELINE")
        if row.candidate_logloss > row.baseline_logloss:
            failures.append(prefix + "LOGLOSS_WORSE_THAN_BASELINE")
        if not (row.paired_brier_delta_upper_95 < 0.0 or row.paired_logloss_delta_upper_95 < 0.0):
            failures.append(prefix + "NO_STATISTICALLY_SUPPORTED_PRIMARY_IMPROVEMENT")
        if not (float(calibration_slope_min) <= row.candidate_calibration_slope <= float(calibration_slope_max)):
            failures.append(prefix + "CALIBRATION_SLOPE_OUT_OF_BOUNDS")
        if abs(row.candidate_calibration_intercept) > float(max_abs_calibration_intercept):
            failures.append(prefix + "CALIBRATION_INTERCEPT_OUT_OF_BOUNDS")
        if row.candidate_ece > float(max_ece):
            failures.append(prefix + "ECE_OUT_OF_BOUNDS")
        if row.candidate_ece - row.baseline_ece > float(max_ece_regression_vs_baseline):
            failures.append(prefix + "ECE_REGRESSION_VS_BASELINE")
        if row.candidate_mean_clv < row.baseline_mean_clv:
            failures.append(prefix + "MEAN_CLV_WORSE_THAN_BASELINE")
        if row.candidate_roi_after_vig < row.baseline_roi_after_vig:
            failures.append(prefix + "ROI_WORSE_THAN_BASELINE")
        if row.recent_two_seasons_both_metrics_worse:
            failures.append(prefix + "RECENT_TWO_SEASON_PRIMARY_DETERIORATION")
        if row.candidate_truth_gate_status != "OFFICIAL":
            failures.append(prefix + "CANDIDATE_TRUTH_GATE_NOT_OFFICIAL")
        if not row.attestations_passed:
            failures.append(prefix + "REQUIRED_ATTESTATIONS_NOT_PASSED")
        if market == "SPREAD":
            assert row.candidate_key_number_max_abs_error is not None
            assert row.baseline_key_number_max_abs_error is not None
            if row.candidate_key_number_max_abs_error > float(spread_max_key_number_abs_error):
                failures.append(prefix + "KEY_NUMBER_CALIBRATION_OUT_OF_BOUNDS")
            if row.candidate_key_number_max_abs_error - row.baseline_key_number_max_abs_error > float(spread_max_key_number_regression_vs_baseline):
                failures.append(prefix + "KEY_NUMBER_REGRESSION_VS_BASELINE")

    status = "PROMOTE_V2" if not failures else "RETAIN_BASELINE"
    return CFBModelPromotionResult(status=status, failures=tuple(failures), markets=normalized)
