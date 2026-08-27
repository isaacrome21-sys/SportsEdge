"""
SportsEdge CFB Holdout Runner.

Computes frozen walk-forward evidence and feeds it to CFB_TRUTH_GATE_V1.
It does not fit, tune, or alter model predictions.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .truth_gate import GateReport, TruthGate


class HoldoutRunnerError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class HoldoutRunner:
    def __init__(self, policy_path: str | Path = "config/cfb_truth_gate_v1.json"):
        self.gate = TruthGate(policy_path)
        self.edge_floor = float(self.gate.gates["edge_floor"])

    @staticmethod
    def _vector(value: Any, name: str, *, probability: bool = False, binary: bool = False) -> np.ndarray:
        try:
            out = np.asarray(value, dtype=float)
        except Exception as exc:
            raise HoldoutRunnerError(f"{name}:NUMERIC_VECTOR_REQUIRED") from exc
        if out.ndim != 1:
            raise HoldoutRunnerError(f"{name}:ONE_DIMENSIONAL_REQUIRED")
        if out.size == 0:
            raise HoldoutRunnerError(f"{name}:NONEMPTY_REQUIRED")
        if not np.all(np.isfinite(out)):
            raise HoldoutRunnerError(f"{name}:FINITE_REQUIRED")
        if probability and (np.any(out < 0.0) or np.any(out > 1.0)):
            raise HoldoutRunnerError(f"{name}:PROBABILITY_REQUIRED")
        if binary and np.any((out != 0.0) & (out != 1.0)):
            raise HoldoutRunnerError(f"{name}:BINARY_REQUIRED")
        return out

    @staticmethod
    def _logloss(y_true: np.ndarray, y_prob: np.ndarray) -> float:
        p = np.clip(y_prob, 1e-15, 1.0 - 1e-15)
        return float(-np.mean(y_true * np.log(p) + (1.0 - y_true) * np.log(1.0 - p)))

    @staticmethod
    def compute_clv_metrics(clv_series: np.ndarray) -> tuple[float, float]:
        values = np.asarray(clv_series, dtype=float)
        if values.ndim != 1 or values.size < 2 or not np.all(np.isfinite(values)):
            return 0.0, 0.0
        mean_clv = float(np.mean(values))
        sd = float(np.std(values, ddof=1))
        if sd <= 1e-15:
            return mean_clv, 0.0
        return mean_clv, float(mean_clv / (sd / sqrt(values.size)))

    @staticmethod
    def compute_calibration(
        y_true: np.ndarray,
        y_prob: np.ndarray,
        n_bins: int = 15,
    ) -> tuple[float, float, float]:
        if isinstance(n_bins, bool) or not isinstance(n_bins, int) or n_bins < 2:
            raise HoldoutRunnerError("n_bins:INTEGER_AT_LEAST_2_REQUIRED")
        bins = np.linspace(0.0, 1.0, n_bins + 1)
        bin_indices = np.clip(np.digitize(y_prob, bins, right=True) - 1, 0, n_bins - 1)

        xs: list[float] = []
        ys: list[float] = []
        weights: list[float] = []
        ece = 0.0
        total = float(len(y_true))

        for index in range(n_bins):
            mask = bin_indices == index
            count = int(mask.sum())
            if count == 0:
                continue
            avg_true = float(np.mean(y_true[mask]))
            avg_pred = float(np.mean(y_prob[mask]))
            xs.append(avg_pred)
            ys.append(avg_true)
            weights.append(float(count))
            ece += (count / total) * abs(avg_true - avg_pred)

        if len(xs) < 2:
            return 0.0, 0.0, float(ece)

        x = np.asarray(xs, dtype=float)
        y = np.asarray(ys, dtype=float)
        w = np.asarray(weights, dtype=float)
        x_bar = float(np.average(x, weights=w))
        y_bar = float(np.average(y, weights=w))
        denom = float(np.sum(w * (x - x_bar) ** 2))
        if denom <= 1e-15:
            return 0.0, y_bar, float(ece)
        slope = float(np.sum(w * (x - x_bar) * (y - y_bar)) / denom)
        intercept = float(y_bar - slope * x_bar)
        return slope, intercept, float(ece)

    def evaluate_market(
        self,
        market: str,
        *,
        y_true: Any,
        y_prob: Any,
        market_novig_prob: Any,
        clv_series: Any,
        roi_series: Any,
        season_ids: Any,
        pit_reproducible: bool,
        leakage_violations: int,
        paired_historical_price_evidence_complete: bool,
        recent_two_season_ok: bool,
    ) -> GateReport:
        """
        Evaluate one settled, non-push market vector.

        clv_series and roi_series must be aligned one-for-one with the holdout rows.
        CLV and ROI gate metrics are calculated only on the frozen promoted subset:
        model probability - decision-time no-vig probability >= policy edge floor.
        """
        truth = self._vector(y_true, "y_true", binary=True)
        model = self._vector(y_prob, "y_prob", probability=True)
        market_prob = self._vector(market_novig_prob, "market_novig_prob", probability=True)
        clv = self._vector(clv_series, "clv_series")
        roi = self._vector(roi_series, "roi_series")

        seasons = np.asarray(season_ids)
        if seasons.ndim != 1 or seasons.size == 0:
            raise HoldoutRunnerError("season_ids:NONEMPTY_ONE_DIMENSIONAL_REQUIRED")
        n = truth.size
        if any(x.size != n for x in (model, market_prob, clv, roi, seasons)):
            raise HoldoutRunnerError("CFB_HOLDOUT_VECTOR_LENGTH_MISMATCH")

        brier_model = float(np.mean((model - truth) ** 2))
        brier_market = float(np.mean((market_prob - truth) ** 2))
        logloss_model = self._logloss(truth, model)
        logloss_market = self._logloss(truth, market_prob)

        eligible_seasons: list[Any] = []
        season_wins = 0
        for season in sorted(set(seasons.tolist())):
            mask = seasons == season
            if int(mask.sum()) < 10:
                continue
            eligible_seasons.append(season)
            model_brier = float(np.mean((model[mask] - truth[mask]) ** 2))
            market_brier = float(np.mean((market_prob[mask] - truth[mask]) ** 2))
            model_log = self._logloss(truth[mask], model[mask])
            market_log = self._logloss(truth[mask], market_prob[mask])
            if model_brier < market_brier and model_log < market_log:
                season_wins += 1
        n_forward_seasons = len(eligible_seasons)
        season_fold_win_rate = season_wins / n_forward_seasons if n_forward_seasons else 0.0

        edges = model - market_prob
        promoted_mask = edges >= self.edge_floor
        n_promoted = int(promoted_mask.sum())
        mean_clv, clv_t = self.compute_clv_metrics(clv[promoted_mask])
        roi_after_vig = float(np.mean(roi[promoted_mask])) if n_promoted else 0.0

        slope, intercept, ece = self.compute_calibration(truth, model)

        hit_rates: dict[str, float] = {}
        for lo, hi, key in (
            (0.03, 0.05, "edge_3_to_5"),
            (0.05, 0.07, "edge_5_to_7"),
            (0.07, float("inf"), "edge_7_plus"),
        ):
            mask = (edges >= lo) & (edges < hi)
            if int(mask.sum()) > 0:
                hit_rates[key] = float(np.mean(truth[mask]))

        return self.gate.evaluate(
            market=market,
            pit_reproducible=pit_reproducible,
            leakage_violations=leakage_violations,
            n_forward_seasons=n_forward_seasons,
            brier_model=brier_model,
            brier_market=brier_market,
            logloss_model=logloss_model,
            logloss_market=logloss_market,
            season_fold_scoring_win_rate=season_fold_win_rate,
            mean_novig_clv=mean_clv,
            clv_t_stat=clv_t,
            roi_after_vig=roi_after_vig,
            calibration_slope=slope,
            calibration_intercept=intercept,
            ece=ece,
            n_promoted=n_promoted,
            recent_two_season_ok=recent_two_season_ok,
            paired_historical_price_evidence_complete=paired_historical_price_evidence_complete,
            evidence_policy_sha256=self.gate.policy_sha256,
            hit_rates=hit_rates or None,
        )

    def run_full_card(self, evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, GateReport]:
        expected = set(self.gate.markets)
        supplied = {str(key).strip().upper() for key in evidence}
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise HoldoutRunnerError(
                "CFB_HOLDOUT_MARKET_SURFACE_MISMATCH:"
                f"missing={','.join(missing) or '-'}:"
                f"extra={','.join(extra) or '-'}"
            )
        reports: dict[str, GateReport] = {}
        for market in sorted(expected):
            reports[market] = self.evaluate_market(market, **dict(evidence[market]))
        return reports

    def write_reports(self, reports: Mapping[str, GateReport], out_dir: str | Path) -> dict[str, str]:
        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=True)
        written: dict[str, str] = {}
        for market in sorted(reports):
            report = reports[market]
            payload = report.to_dict()
            raw = _canonical_bytes(payload)
            digest = sha256(raw).hexdigest()
            target = root / f"{market.lower()}_{report.policy_id.lower()}_{digest}.json"
            body = raw + b"\n"
            try:
                with target.open("xb") as handle:
                    handle.write(body)
            except FileExistsError:
                if target.read_bytes() != body:
                    raise HoldoutRunnerError("CFB_HOLDOUT_REPORT_IMMUTABLE_COLLISION")
            written[market] = str(target)
        return written
