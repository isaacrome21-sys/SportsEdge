"""Chronological calibration-method selection for SportsEdge research.

Calibration is not automatically beneficial. This module compares identity,
Platt/logistic recalibration and isotonic regression inside the calibration fold,
then refits only the selected method on the full calibration fold. The untouched
test/holdout is never inspected during method selection.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any, Iterable, Mapping, Sequence

from .multi_market_backtest import BinaryResearchRow, ResearchBacktestError, canonicalize_rows

EPS = 1e-9
CALIBRATION_SELECTOR_VERSION = "chronological_calibration_selector_v1"


def _clip(p: float) -> float:
    return min(1.0 - EPS, max(EPS, float(p)))


def _scores(pairs: Sequence[tuple[float, int]]) -> dict[str, float]:
    if not pairs:
        raise ResearchBacktestError("CALIBRATION_SCORE_ROWS_EMPTY")
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    logloss = sum(-(y * log(_clip(p)) + (1 - y) * log(1.0 - _clip(p))) for p, y in pairs) / len(pairs)
    return {"brier": float(brier), "log_loss": float(logloss)}


def _platt_fit(pairs: Sequence[tuple[float, int]], max_iter: int = 60) -> tuple[float, float]:
    if len(pairs) < 20:
        raise ResearchBacktestError("PLATT_ROWS_INSUFFICIENT")
    xs = [log(_clip(p) / (1.0 - _clip(p))) for p, _ in pairs]
    ys = [int(y) for _, y in pairs]
    a, b = 0.0, 1.0
    ridge = 1e-8
    for _ in range(max_iter):
        g0 = g1 = 0.0
        h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            z = max(-35.0, min(35.0, a + b * x))
            q = 1.0 / (1.0 + exp(-z))
            w = max(EPS, q * (1.0 - q))
            diff = y - q
            g0 += diff
            g1 += diff * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        h00 += ridge
        h11 += ridge
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-15:
            raise ResearchBacktestError("PLATT_HESSIAN_SINGULAR")
        da = (g0 * h11 - g1 * h01) / det
        db = (g1 * h00 - g0 * h01) / det
        a += da
        b += db
        if max(abs(da), abs(db)) < 1e-9:
            break
    if not isfinite(a) or not isfinite(b):
        raise ResearchBacktestError("PLATT_FIT_NONFINITE")
    return float(a), float(b)


def _platt_predict(p: float, params: tuple[float, float]) -> float:
    a, b = params
    x = log(_clip(p) / (1.0 - _clip(p)))
    z = max(-35.0, min(35.0, a + b * x))
    return _clip(1.0 / (1.0 + exp(-z)))


def _isotonic_fit(pairs: Sequence[tuple[float, int]]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if len(pairs) < 20:
        raise ResearchBacktestError("ISOTONIC_ROWS_INSUFFICIENT")
    ordered = sorted((float(p), int(y)) for p, y in pairs)
    # Equal raw probabilities must first collapse into one empirical block.
    # Otherwise PAV can leave multiple blocks with the same threshold and a
    # step lookup may return the wrong one for that exact probability.
    blocks: list[dict[str, float]] = []
    for p, y in ordered:
        if blocks and abs(blocks[-1]["hi"] - p) <= 1e-15:
            blocks[-1]["sum"] += float(y)
            blocks[-1]["n"] += 1.0
            continue
        blocks.append({"lo": p, "hi": p, "sum": float(y), "n": 1.0})

    i = 0
    while i < len(blocks) - 1:
        left = blocks[i]["sum"] / blocks[i]["n"]
        right = blocks[i + 1]["sum"] / blocks[i + 1]["n"]
        if left <= right + 1e-15:
            i += 1
            continue
        a, b = blocks[i], blocks[i + 1]
        blocks[i:i + 2] = [{
            "lo": a["lo"],
            "hi": b["hi"],
            "sum": a["sum"] + b["sum"],
            "n": a["n"] + b["n"],
        }]
        if i > 0:
            i -= 1

    thresholds = tuple(float(block["hi"]) for block in blocks)
    values = tuple(_clip(block["sum"] / block["n"]) for block in blocks)
    return thresholds, values


def _isotonic_predict(p: float, params: tuple[tuple[float, ...], tuple[float, ...]]) -> float:
    thresholds, values = params
    if not thresholds or len(thresholds) != len(values):
        raise ResearchBacktestError("ISOTONIC_PARAMS_INVALID")
    x = float(p)
    for threshold, value in zip(thresholds, values):
        if x <= threshold:
            return _clip(value)
    return _clip(values[-1])


@dataclass(frozen=True)
class SelectedCalibrator:
    version: str
    method: str
    parameters: Mapping[str, Any]
    selection_scores: Mapping[str, Mapping[str, float]]
    calibration_n: int
    fit_n: int
    selection_n: int

    def predict(self, raw_probability: float) -> float:
        p = _clip(float(raw_probability))
        if self.method == "IDENTITY":
            return p
        if self.method == "PLATT":
            return _platt_predict(p, (float(self.parameters["intercept"]), float(self.parameters["slope"])))
        if self.method == "ISOTONIC":
            thresholds = tuple(float(x) for x in self.parameters["thresholds"])
            values = tuple(float(x) for x in self.parameters["values"])
            return _isotonic_predict(p, (thresholds, values))
        raise ResearchBacktestError("UNKNOWN_CALIBRATOR_METHOD")


def _pairs(rows: Sequence[BinaryResearchRow]) -> list[tuple[float, int]]:
    return [(row.model_p, int(row.outcome)) for row in rows if row.outcome in (0, 1)]


def select_calibrator(
    rows: Iterable[Mapping[str, Any] | BinaryResearchRow], *,
    fit_fraction: float = 2.0 / 3.0,
    minimum_rows: int = 90,
    tolerance: float = 1e-6,
) -> SelectedCalibrator:
    data = [row for row in canonicalize_rows(rows) if row.outcome in (0, 1)]
    if len(data) < int(minimum_rows):
        raise ResearchBacktestError(f"CALIBRATION_ROWS_INSUFFICIENT:{len(data)}<{int(minimum_rows)}")
    fraction = float(fit_fraction)
    if not 0.5 <= fraction <= 0.85:
        raise ResearchBacktestError("CALIBRATION_FIT_FRACTION_OUT_OF_RANGE")
    split = int(len(data) * fraction)
    if split < 20 or len(data) - split < 20:
        raise ResearchBacktestError("CALIBRATION_INTERNAL_SPLIT_TOO_SMALL")
    fit_rows = data[:split]
    selection_rows = data[split:]
    fit_pairs = _pairs(fit_rows)
    selection_pairs = _pairs(selection_rows)

    platt = _platt_fit(fit_pairs)
    isotonic = _isotonic_fit(fit_pairs)
    predictors = {
        "IDENTITY": lambda p: _clip(p),
        "PLATT": lambda p: _platt_predict(p, platt),
        "ISOTONIC": lambda p: _isotonic_predict(p, isotonic),
    }
    scores: dict[str, dict[str, float]] = {}
    for method, predictor in predictors.items():
        scores[method] = _scores([(predictor(p), y) for p, y in selection_pairs])

    base = scores["IDENTITY"]
    admissible = ["IDENTITY"]
    for method in ("PLATT", "ISOTONIC"):
        score = scores[method]
        not_worse = (
            score["brier"] <= base["brier"] + tolerance
            and score["log_loss"] <= base["log_loss"] + tolerance
        )
        improves = (
            score["brier"] < base["brier"] - tolerance
            or score["log_loss"] < base["log_loss"] - tolerance
        )
        if not_worse and improves:
            admissible.append(method)
    selected = min(admissible, key=lambda method: (scores[method]["log_loss"], scores[method]["brier"], method))

    full_pairs = _pairs(data)
    if selected == "PLATT":
        intercept, slope = _platt_fit(full_pairs)
        params: Mapping[str, Any] = {"intercept": intercept, "slope": slope}
    elif selected == "ISOTONIC":
        thresholds, values = _isotonic_fit(full_pairs)
        params = {"thresholds": thresholds, "values": values}
    else:
        params = {}

    return SelectedCalibrator(
        version=CALIBRATION_SELECTOR_VERSION,
        method=selected,
        parameters=params,
        selection_scores=scores,
        calibration_n=len(data),
        fit_n=len(fit_rows),
        selection_n=len(selection_rows),
    )
