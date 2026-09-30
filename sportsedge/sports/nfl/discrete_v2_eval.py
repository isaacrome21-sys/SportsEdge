"""Frozen holdout evaluator for NFL discrete v2. Locked before W4."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import json

from sportsedge.sports.nfl.discrete_v2 import (
    home_win_mass,
    load_freeze,
    margin_mass,
    means_from_attempt9,
    score_grid,
    total_mass,
)

EVAL_PATH = Path(__file__).resolve().parents[3] / "config" / "nfl_discrete_v2_eval_freeze.json"
EVAL_SCHEMA = "SPORTSEDGE_NFL_DISCRETE_V2_EVAL_FREEZE_V1"
MIN_N = 80
BASELINE_HOME_WIN = 0.5400183992640294
SLOPE_LO, SLOPE_HI = 0.70, 1.30
INTERCEPT_ABS = 0.10
FREQ_TOL = 0.03


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def load_eval_freeze(path: Path | None = None) -> dict[str, Any]:
    artifact = json.loads((path or EVAL_PATH).read_text())
    expected = str(artifact.get("artifact_sha256") or "").lower()
    payload = dict(artifact)
    payload.pop("artifact_sha256", None)
    actual = canonical_sha256(payload)
    if artifact.get("schema_version") != EVAL_SCHEMA:
        raise ValueError("NFL_DISCRETE_V2_EVAL_SCHEMA_INVALID")
    if expected != actual:
        raise ValueError(f"NFL_DISCRETE_V2_EVAL_SHA_MISMATCH:{actual}")
    return artifact


def _ols(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    den = sum((xi - mx) ** 2 for xi in x)
    if den <= 0:
        return float("nan"), float("nan")
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / den
    return slope, my - slope * mx


def evaluate_holdout(
    games: Iterable[Mapping[str, Any]],
    *,
    freeze: Mapping[str, Any] | None = None,
    eval_freeze: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    art = freeze or load_freeze()
    ev = eval_freeze or load_eval_freeze()
    if ev.get("min_n") != MIN_N:
        raise ValueError("NFL_DISCRETE_V2_EVAL_MIN_N_DRIFT")
    rows = list(games)
    n = len(rows)
    if n < MIN_N:
        return {"status": "INSUFFICIENT", "n": n, "min_n": MIN_N, "pass": False}

    p_hats: list[float] = []
    y: list[int] = []
    pred3 = pred7 = pred10 = 0.0
    obs3 = obs7 = obs10 = 0
    pred_totals: dict[int, float] = {}
    obs_totals: dict[int, int] = {}
    brier = 0.0
    base_brier = 0.0
    for row in rows:
        means = means_from_attempt9(row["attempt9_margin"], row["attempt9_total"])
        grid = score_grid(means["mean_home"], means["mean_away"], art)
        p_home = home_win_mass(grid)
        home = int(row["home_score"])
        away = int(row["away_score"])
        won = 1 if home > away else 0
        p_hats.append(p_home)
        y.append(won)
        brier += (p_home - won) ** 2
        base_brier += (BASELINE_HOME_WIN - won) ** 2
        pred3 += margin_mass(grid, 3)
        pred7 += margin_mass(grid, 7)
        pred10 += margin_mass(grid, 10)
        am = abs(home - away)
        obs3 += int(am == 3)
        obs7 += int(am == 7)
        obs10 += int(am == 10)
        obs_totals[home + away] = obs_totals.get(home + away, 0) + 1
        for k in range(30, 61):
            pred_totals[k] = pred_totals.get(k, 0.0) + total_mass(grid, k)
    slope, intercept = _ols(p_hats, [float(v) for v in y])
    gate_brier = (brier / n) < (base_brier / n)
    gate_cal = (SLOPE_LO <= slope <= SLOPE_HI) and abs(intercept) <= INTERCEPT_ABS
    gate_m3 = abs(pred3 / n - obs3 / n) <= FREQ_TOL
    gate_m7 = abs(pred7 / n - obs7 / n) <= FREQ_TOL
    gate_m10 = abs(pred10 / n - obs10 / n) <= FREQ_TOL
    gate_totals = all(
        abs(pred_totals.get(k, 0.0) / n - obs_totals.get(k, 0) / n) <= FREQ_TOL for k in range(30, 61)
    )
    passed = bool(gate_brier and gate_cal and gate_m3 and gate_m7 and gate_m10 and gate_totals)
    return {
        "status": "SCORED",
        "n": n,
        "min_n": MIN_N,
        "brier": brier / n,
        "baseline_brier": base_brier / n,
        "gate_brier": gate_brier,
        "slope": slope,
        "intercept": intercept,
        "gate_calibration": gate_cal,
        "p_abs_margin_3_pred": pred3 / n,
        "p_abs_margin_3_obs": obs3 / n,
        "p_abs_margin_7_pred": pred7 / n,
        "p_abs_margin_7_obs": obs7 / n,
        "p_abs_margin_10_pred": pred10 / n,
        "p_abs_margin_10_obs": obs10 / n,
        "gate_margin_3": gate_m3,
        "gate_margin_7": gate_m7,
        "gate_margin_10": gate_m10,
        "gate_integer_totals": gate_totals,
        "pass": passed,
        "phone_card": False,
    }
