"""Frozen holdout evaluator for NFL discrete v2. Locked before W4.

Every gate is read from config/nfl_discrete_v2_eval_freeze.json.
Dicts passed into evaluate_holdout must hash to the on-disk freeze.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
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


def _require_passed_freeze(
    passed: Mapping[str, Any] | None,
    loader: Callable[[], Mapping[str, Any]],
    mismatch_code: str,
) -> Mapping[str, Any]:
    """Passed freeze/eval dicts must recompute to the on-disk artifact SHA."""
    disk = loader()
    expected = str(disk.get("artifact_sha256") or "").lower()
    if passed is None:
        return disk
    payload = dict(passed)
    embedded = str(payload.pop("artifact_sha256", "") or "").lower()
    actual = canonical_sha256(payload)
    if not expected or embedded != expected or actual != expected:
        raise ValueError(f"{mismatch_code}:{actual}")
    return dict(passed)


def active_holdout(ev: Mapping[str, Any]) -> dict[str, Any]:
    hold = ev["holdout"]
    window = hold[str(hold["active"])]
    if int(window["season"]) != 2026 or window["game_type"] != "REG":
        raise ValueError("NFL_DISCRETE_V2_EVAL_HOLDOUT_IDENTITY")
    return {"season": 2026, "game_type": "REG", "weeks": [int(w) for w in window["weeks"]], "key": str(hold["active"])}


def _require_holdout_row(row: Mapping[str, Any], window: Mapping[str, Any]) -> None:
    season = int(row["season"])
    week = int(row["week"])
    game_type = str(row["game_type"])
    if season == 2025 or week in {1, 2, 3} or season != window["season"] or game_type != window["game_type"] or week not in window["weeks"]:
        raise ValueError(f"NFL_DISCRETE_V2_EVAL_HOLDOUT_LEAK:season={season}:week={week}:game_type={game_type}")


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
    art = _require_passed_freeze(freeze, load_freeze, "NFL_DISCRETE_V2_SHA_MISMATCH")
    ev = _require_passed_freeze(eval_freeze, load_eval_freeze, "NFL_DISCRETE_V2_EVAL_SHA_MISMATCH")
    gates = ev["gates"]
    min_n = int(ev["min_n"])
    baseline = float(gates["brier_vs_home_win_baseline"])
    slope_lo, slope_hi = (float(v) for v in gates["calibration_slope"])
    intercept_abs = float(gates["calibration_intercept_abs"])
    freq_tol = float(gates["outcome_freq_tolerance"])
    total_lo = int(gates["integer_totals"]["lo"])
    total_hi = int(gates["integer_totals"]["hi"])
    margin_keys = [int(k) for k in gates["margin_keys"]]
    if (total_lo, total_hi) != (40, 51) or margin_keys != [3, 7, 10] or min_n != 80:
        raise ValueError("NFL_DISCRETE_V2_EVAL_GATE_DRIFT")
    window = active_holdout(ev)
    rows = list(games)
    for row in rows:
        _require_holdout_row(row, window)
    n = len(rows)
    if n < min_n:
        return {"status": "INSUFFICIENT", "n": n, "min_n": min_n, "pass": False, "holdout": window}
    p_hats: list[float] = []
    y: list[int] = []
    pred_m = {k: 0.0 for k in margin_keys}
    obs_m = {k: 0 for k in margin_keys}
    pred_totals = {k: 0.0 for k in range(total_lo, total_hi + 1)}
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
        base_brier += (baseline - won) ** 2
        am = abs(home - away)
        for k in margin_keys:
            pred_m[k] += margin_mass(grid, k)
            obs_m[k] += int(am == k)
        obs_totals[home + away] = obs_totals.get(home + away, 0) + 1
        for k in range(total_lo, total_hi + 1):
            pred_totals[k] += total_mass(grid, k)
    slope, intercept = _ols(p_hats, [float(v) for v in y])
    gate_brier = (brier / n) < (base_brier / n)
    gate_cal = (slope_lo <= slope <= slope_hi) and abs(intercept) <= intercept_abs
    margin_ok = {k: abs(pred_m[k] / n - obs_m[k] / n) <= freq_tol for k in margin_keys}
    gate_totals = all(abs(pred_totals[k] / n - obs_totals.get(k, 0) / n) <= freq_tol for k in range(total_lo, total_hi + 1))
    passed = bool(gate_brier and gate_cal and all(margin_ok.values()) and gate_totals)
    return {
        "status": "SCORED",
        "n": n,
        "min_n": min_n,
        "holdout": window,
        "brier": brier / n,
        "baseline_brier": base_brier / n,
        "gate_brier": gate_brier,
        "slope": slope,
        "intercept": intercept,
        "gate_calibration": gate_cal,
        "p_abs_margin_3_pred": pred_m[3] / n,
        "p_abs_margin_3_obs": obs_m[3] / n,
        "p_abs_margin_7_pred": pred_m[7] / n,
        "p_abs_margin_7_obs": obs_m[7] / n,
        "p_abs_margin_10_pred": pred_m[10] / n,
        "p_abs_margin_10_obs": obs_m[10] / n,
        "gate_margin_3": margin_ok[3],
        "gate_margin_7": margin_ok[7],
        "gate_margin_10": margin_ok[10],
        "gate_integer_totals": gate_totals,
        "totals_range": [total_lo, total_hi],
        "pass": passed,
        "phone_card": False,
        "freeze_sha256": str(art["artifact_sha256"]),
        "eval_sha256": str(ev["artifact_sha256"]),
    }
