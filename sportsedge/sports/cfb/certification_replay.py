"""Replay CFB historical evidence into the frozen CFB_TRUTH_GATE_V1.

Predictive skill metrics are scored on ALL PIT-supportable held-out non-push forecasts,
not only bets selected after prediction. Economic metrics (CLV/ROI) are scored only on
rows selected by the frozen historical candidate policy. This prevents bet-selection
from artificially improving Brier/log-loss/calibration and prevents unsupported board
rows from contaminating the scoring population.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, sqrt
from statistics import mean, stdev
from typing import Any, Iterable, Mapping

from .truth_gate_v1 import CFBTruthGateEvidence, CFBTruthGateResult, evaluate_cfb_truth_gate_v1
from .validation_attestation import CFBValidationAttestation, assert_attestations_cover_forward_seasons
from .validation_v12 import brier_score, expected_calibration_error, log_loss, calibration_intercept_slope


class CFBCertificationReplayError(ValueError):
    pass


def _p(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBCertificationReplayError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise CFBCertificationReplayError(f"{field}:PROBABILITY_RANGE")
    return out


def _f(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBCertificationReplayError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBCertificationReplayError(f"{field}:FINITE_REQUIRED")
    return out


def _strict_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise CFBCertificationReplayError(f"{field}:BOOL_REQUIRED")
    return bool(value)


def american_profit_per_unit(odds: float) -> float:
    value = _f(odds, "american_odds")
    if -100.0 < value < 100.0:
        raise CFBCertificationReplayError("AMERICAN_ODDS_INVALID")
    return 100.0 / abs(value) if value < 0 else value / 100.0


@dataclass(frozen=True)
class CFBReplayRow:
    game_id: str
    market: str
    season: int
    week: int
    classification: str
    side: str
    model_probability_nonpush: float
    benchmark_probability_nonpush: float
    settlement: str
    predictive_supportable: bool
    candidate_status: str
    american_odds_at_decision: float | None
    clv_probability_points: float | None
    replayable: bool
    paired_prices_present: bool
    pit_reproducible: bool
    policy_sha_valid: bool
    benchmark_methodology_sha_valid: bool

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "CFBReplayRow":
        return cls(
            game_id=str(row.get("game_id") or "").strip(),
            market=str(row.get("market") or "").strip().upper(),
            season=int(row.get("season")),
            week=int(row.get("week")),
            classification=str(row.get("classification") or "UNKNOWN").upper(),
            side=str(row.get("side") or "").strip().upper(),
            model_probability_nonpush=_p(row.get("model_probability_nonpush"), "model_probability_nonpush"),
            benchmark_probability_nonpush=_p(row.get("benchmark_probability_nonpush"), "benchmark_probability_nonpush"),
            settlement=str(row.get("settlement") or "").strip().upper(),
            predictive_supportable=_strict_bool(row.get("predictive_supportable"), "predictive_supportable"),
            candidate_status=str(row.get("candidate_status") or "").strip().upper(),
            american_odds_at_decision=None if row.get("american_odds_at_decision") is None else _f(row.get("american_odds_at_decision"), "american_odds_at_decision"),
            clv_probability_points=None if row.get("clv_probability_points") is None else _f(row.get("clv_probability_points"), "clv_probability_points"),
            replayable=_strict_bool(row.get("replayable"), "replayable"),
            paired_prices_present=_strict_bool(row.get("paired_prices_present"), "paired_prices_present"),
            pit_reproducible=_strict_bool(row.get("pit_reproducible"), "pit_reproducible"),
            policy_sha_valid=_strict_bool(row.get("policy_sha_valid"), "policy_sha_valid"),
            benchmark_methodology_sha_valid=_strict_bool(row.get("benchmark_methodology_sha_valid"), "benchmark_methodology_sha_valid"),
        ).validate()

    def validate(self) -> "CFBReplayRow":
        if not self.game_id or not self.side:
            raise CFBCertificationReplayError("REPLAY_IDENTITY_REQUIRED")
        if self.market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBCertificationReplayError("REPLAY_MARKET_INVALID")
        if self.week <= 0:
            raise CFBCertificationReplayError("REPLAY_WEEK_INVALID")
        if self.classification not in {"FBS_FBS", "FBS_FCS", "FCS_FCS"}:
            raise CFBCertificationReplayError("REPLAY_CLASSIFICATION_INVALID")
        for name in (
            "predictive_supportable", "replayable", "paired_prices_present", "pit_reproducible",
            "policy_sha_valid", "benchmark_methodology_sha_valid",
        ):
            _strict_bool(getattr(self, name), name)
        _p(self.model_probability_nonpush, "model_probability_nonpush")
        _p(self.benchmark_probability_nonpush, "benchmark_probability_nonpush")
        if self.settlement not in {"WIN", "LOSS", "PUSH"}:
            raise CFBCertificationReplayError("REPLAY_SETTLEMENT_INVALID")
        if self.candidate_status not in {"SHADOW_QUALIFIED", "NO_BET", "BLOCKED"}:
            raise CFBCertificationReplayError("REPLAY_CANDIDATE_STATUS_INVALID")
        if self.candidate_status == "SHADOW_QUALIFIED":
            if not self.predictive_supportable:
                raise CFBCertificationReplayError("REPLAY_CANDIDATE_NOT_PREDICTIVE_SUPPORTABLE")
            if self.american_odds_at_decision is None:
                raise CFBCertificationReplayError("REPLAY_CANDIDATE_PRICE_REQUIRED")
            american_profit_per_unit(self.american_odds_at_decision)
        return self

    @property
    def binary_outcome(self) -> int | None:
        if self.settlement == "PUSH":
            return None
        return 1 if self.settlement == "WIN" else 0

    @property
    def profit_units(self) -> float | None:
        if self.candidate_status != "SHADOW_QUALIFIED":
            return None
        if self.settlement == "PUSH":
            return 0.0
        if self.settlement == "LOSS":
            return -1.0
        assert self.american_odds_at_decision is not None
        return american_profit_per_unit(self.american_odds_at_decision)


@dataclass(frozen=True)
class CFBSeasonMetric:
    season: int
    n: int
    model_brier: float
    benchmark_brier: float
    model_logloss: float
    benchmark_logloss: float


@dataclass(frozen=True)
class CFBCertificationReplay:
    market: str
    rows_total: int
    predictive_rows_nonpush: int
    promoted_sample: int
    forward_seasons: tuple[int, ...]
    season_metrics: tuple[CFBSeasonMetric, ...]
    recent_2season_deterioration: bool
    attestation_bundle_sha: str
    evidence: CFBTruthGateEvidence
    gate_result: CFBTruthGateResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "rows_total": self.rows_total,
            "predictive_rows_nonpush": self.predictive_rows_nonpush,
            "promoted_sample": self.promoted_sample,
            "forward_seasons": list(self.forward_seasons),
            "season_metrics": [asdict(x) for x in self.season_metrics],
            "recent_2season_deterioration": self.recent_2season_deterioration,
            "attestation_bundle_sha": self.attestation_bundle_sha,
            "evidence": asdict(self.evidence),
            "gate_result": self.gate_result.to_dict(),
        }


def _season_metrics(rows: list[CFBReplayRow]) -> tuple[CFBSeasonMetric, ...]:
    out: list[CFBSeasonMetric] = []
    for season in sorted({row.season for row in rows}):
        sr = [row for row in rows if row.binary_outcome is not None]
        if not sr:
            raise CFBCertificationReplayError(f"REPLAY_SEASON_NO_NONPUSH_ROWS:{season}")
        outcomes = [int(row.binary_outcome) for row in sr]
        mp = [row.model_probability_nonpush for row in sr]
        bp = [row.benchmark_probability_nonpush for row in sr]
        out.append(CFBSeasonMetric(
            season=season,
            n=len(sr),
            model_brier=brier_score(mp, outcomes),
            benchmark_brier=brier_score(bp, outcomes),
            model_logloss=log_loss(mp, outcomes),
            benchmark_logloss=log_loss(bp, outcomes),
        ))
    return tuple(out)


def recent_two_season_deterioration(metrics: tuple[CFBSeasonMetric, ...]) -> bool:
    """CFB_RECENT_2SEASON_DETERIORATION_V1.

    True when either primary probability score fails to beat the frozen benchmark in
    BOTH of the two most recent completed outer seasons. One isolated weak season is
    reported but does not satisfy the two-season deterioration definition.
    """

    if len(metrics) < 2:
        raise CFBCertificationReplayError("RECENT_2SEASON_METRICS_REQUIRED")
    last = sorted(metrics, key=lambda x: x.season)[-2:]
    brier_both_fail = all(row.model_brier >= row.benchmark_brier for row in last)
    logloss_both_fail = all(row.model_logloss >= row.benchmark_logloss for row in last)
    return bool(brier_both_fail or logloss_both_fail)


def _clv_tstat(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    sd = stdev(values)
    # A zero-variance CLV sample does not get an artificial infinite t-stat. Treat it
    # conservatively as unproven rather than allowing a degenerate sample to certify.
    if sd <= 1e-15:
        return 0.0
    return mean(values) / (sd / sqrt(len(values)))


def replay_cfb_truth_gate(
    rows: Iterable[CFBReplayRow | Mapping[str, Any]],
    *,
    market: str,
    attestations: list[CFBValidationAttestation],
    leakage_violations: int = 0,
) -> CFBCertificationReplay:
    target = str(market).upper()
    if target not in {"MONEYLINE", "SPREAD", "TOTAL"}:
        raise CFBCertificationReplayError("REPLAY_MARKET_UNSUPPORTED")
    normalized = [row if isinstance(row, CFBReplayRow) else CFBReplayRow.from_mapping(row) for row in rows]
    data = [row.validate() for row in normalized if row.market == target]
    if not data:
        raise CFBCertificationReplayError("REPLAY_ROWS_REQUIRED")

    supportable = [row for row in data if row.predictive_supportable]
    if not supportable:
        raise CFBCertificationReplayError("REPLAY_NO_PREDICTIVE_SUPPORTABLE_ROWS")
    seasons = tuple(sorted({row.season for row in supportable}))
    attestation_bundle_sha = assert_attestations_cover_forward_seasons(
        attestations,
        market=target,
        expected_test_seasons=list(seasons),
    )

    predictive = [row for row in supportable if row.binary_outcome is not None]
    if not predictive:
        raise CFBCertificationReplayError("REPLAY_PREDICTIVE_NONPUSH_ROWS_REQUIRED")
    outcomes = [int(row.binary_outcome) for row in predictive]
    model_probs = [row.model_probability_nonpush for row in predictive]
    benchmark_probs = [row.benchmark_probability_nonpush for row in predictive]
    calibration_intercept, calibration_slope = calibration_intercept_slope(model_probs, outcomes)

    candidates = [row for row in supportable if row.candidate_status == "SHADOW_QUALIFIED"]
    clv_values = [float(row.clv_probability_points) for row in candidates if row.clv_probability_points is not None]
    paired_prices = bool(candidates) and len(clv_values) == len(candidates) and all(row.paired_prices_present for row in candidates)
    replayable_candidates = bool(candidates) and all(row.replayable for row in candidates)
    profits = [row.profit_units for row in candidates]
    if any(value is None for value in profits):
        raise CFBCertificationReplayError("REPLAY_CANDIDATE_SETTLEMENT_MISSING")
    profit_values = [float(value) for value in profits if value is not None]
    roi = mean(profit_values) if profit_values else 0.0
    clv_mean = mean(clv_values) if clv_values else 0.0
    clv_t = _clv_tstat(clv_values)

    season_metrics = _season_metrics(supportable)
    deterioration = recent_two_season_deterioration(season_metrics)
    used_rows = list({id(row): row for row in [*supportable, *candidates]}.values())
    evidence = CFBTruthGateEvidence(
        market=target,
        forward_seasons=len(seasons),
        promoted_sample=len(candidates),
        brier_model=brier_score(model_probs, outcomes),
        brier_novig_market=brier_score(benchmark_probs, outcomes),
        logloss_model=log_loss(model_probs, outcomes),
        logloss_novig_market=log_loss(benchmark_probs, outcomes),
        mean_novig_clv=clv_mean,
        clv_tstat=clv_t,
        roi_after_vig=roi,
        calibration_slope=calibration_slope,
        calibration_intercept=calibration_intercept,
        ece=expected_calibration_error(model_probs, outcomes),
        recent_2season_deterioration=deterioration,
        leakage_violations=int(leakage_violations),
        paired_historical_prices_present=paired_prices,
        pit_reproducible=all(row.pit_reproducible for row in used_rows),
        policy_sha_valid=all(row.policy_sha_valid for row in used_rows),
        benchmark_methodology_sha_valid=all(row.benchmark_methodology_sha_valid for row in used_rows),
        all_promoted_rows_replayable=replayable_candidates,
    )
    gate = evaluate_cfb_truth_gate_v1(evidence)
    return CFBCertificationReplay(
        market=target,
        rows_total=len(data),
        predictive_rows_nonpush=len(predictive),
        promoted_sample=len(candidates),
        forward_seasons=seasons,
        season_metrics=season_metrics,
        recent_2season_deterioration=deterioration,
        attestation_bundle_sha=attestation_bundle_sha,
        evidence=evidence,
        gate_result=gate,
    )
