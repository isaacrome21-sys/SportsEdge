from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from scripts.build_mlb_moneyline_preseason_evidence import Game, calibration_metrics, fit_logistic

MODEL_VERSION = "mlb_moneyline_rolling_market_blind_v2"
FEATURE_NAMES = (
    "elo_diff_400",
    "rolling30_win_pct_diff",
    "rolling30_run_diff_pg_diff",
    "rolling30_runs_scored_pg_diff",
    "rolling30_runs_allowed_pg_diff",
)
K_FACTOR = 20.0
HISTORICAL_EMBARGO_HOURS = 48
MIN_ROLLING_GAMES = 10
CALIBRATION_SLOPE_MIN = 0.90
CALIBRATION_SLOPE_MAX = 1.10
CALIBRATION_INTERCEPT_ABS_MAX = 0.03
ECE_MAX = 0.025
MIN_SAMPLE = 200


class RollingCandidateError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _utc(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise RollingCandidateError("timezone required")
    return dt.astimezone(timezone.utc)


def read_games(path: Path) -> list[Game]:
    import pyarrow.parquet as pq
    rows = pq.read_table(path).to_pylist()
    games = []
    for r in rows:
        games.append(Game(
            int(r["season"]), int(r["game_pk"]), _utc(r["start_utc"]),
            int(r["home_team_id"]), int(r["away_team_id"]),
            int(r["home_runs"]), int(r["away_runs"]),
        ))
    games.sort(key=lambda g: (g.start_utc, g.game_pk))
    return games


def _team_summary(history: deque[tuple[int, int, int]]) -> tuple[float, float, float, float]:
    if len(history) < MIN_ROLLING_GAMES:
        raise RollingCandidateError("insufficient rolling history")
    wins = [r[0] for r in history]
    rf = [r[1] for r in history]
    ra = [r[2] for r in history]
    n = float(len(history))
    return sum(wins) / n, sum(x - y for x, y in zip(rf, ra)) / n, sum(rf) / n, sum(ra) / n


def build_chronological_examples(games: list[Game]) -> list[dict[str, Any]]:
    elo: dict[int, float] = defaultdict(lambda: 1500.0)
    hist: dict[int, deque[tuple[int, int, int]]] = defaultdict(lambda: deque(maxlen=30))
    applied = 0
    rows: list[dict[str, Any]] = []

    def apply_result(g: Game) -> None:
        eh = 1.0 / (1.0 + 10.0 ** ((elo[g.away_team_id] - elo[g.home_team_id]) / 400.0))
        result = 1.0 if g.home_runs > g.away_runs else 0.0
        delta = K_FACTOR * (result - eh)
        elo[g.home_team_id] += delta
        elo[g.away_team_id] -= delta
        hist[g.home_team_id].append((int(result), g.home_runs, g.away_runs))
        hist[g.away_team_id].append((int(1.0 - result), g.away_runs, g.home_runs))

    for g in games:
        while applied < len(games):
            source = games[applied]
            available_at = source.start_utc + timedelta(hours=HISTORICAL_EMBARGO_HOURS)
            if available_at >= g.start_utc:
                break
            apply_result(source)
            applied += 1

        if g.season < 2023:
            continue
        if len(hist[g.home_team_id]) < MIN_ROLLING_GAMES or len(hist[g.away_team_id]) < MIN_ROLLING_GAMES:
            continue
        hw, hrd, hrs, hra = _team_summary(hist[g.home_team_id])
        aw, ard, ars, ara = _team_summary(hist[g.away_team_id])
        feature_asof = g.start_utc - timedelta(hours=HISTORICAL_EMBARGO_HOURS)
        features = [
            (elo[g.home_team_id] - elo[g.away_team_id]) / 400.0,
            hw - aw,
            hrd - ard,
            hrs - ars,
            hra - ara,
        ]
        rows.append({
            "season": g.season,
            "game_pk": g.game_pk,
            "event_start_ts": g.start_utc.isoformat(),
            "development_feature_cutoff_ts": feature_asof.isoformat(),
            "home_team_id": g.home_team_id,
            "away_team_id": g.away_team_id,
            "home_win": 1 if g.home_runs > g.away_runs else 0,
            **{name: float(v) for name, v in zip(FEATURE_NAMES, features)},
        })
    return rows


def matrix(rows: list[dict[str, Any]], mean: np.ndarray | None = None, sd: np.ndarray | None = None):
    raw = np.asarray([[r[n] for n in FEATURE_NAMES] for r in rows], dtype=float)
    if mean is None:
        mean = raw.mean(axis=0)
    if sd is None:
        sd = raw.std(axis=0)
        sd = np.where(sd < 1e-9, 1.0, sd)
    z = (raw - mean) / sd
    return np.column_stack([np.ones(len(rows)), z]), np.asarray([r["home_win"] for r in rows], dtype=float), mean, sd


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-x))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule-parquet", default="data/mlb_moneyline_preseason/schedule_final_games.parquet")
    ap.add_argument("--artifact-dir", default="artifacts/mlb_moneyline_rolling_v2")
    ap.add_argument("--holdout-cutoff", default="2026-09-15T23:59:59+00:00")
    args = ap.parse_args()

    games = read_games(Path(args.schedule_parquet))
    cutoff = _utc(args.holdout_cutoff)
    rows = [r for r in build_chronological_examples(games) if _utc(r["event_start_ts"]) <= cutoff]
    train = [r for r in rows if r["season"] in {2023, 2024}]
    cal = [r for r in rows if r["season"] == 2025]
    dev = [r for r in rows if r["season"] == 2026]
    if min(len(train), len(cal), len(dev)) < MIN_SAMPLE:
        raise RollingCandidateError(f"insufficient split sizes train={len(train)} cal={len(cal)} dev={len(dev)}")

    xtr, ytr, mean, sd = matrix(train)
    beta = fit_logistic(xtr, ytr, ridge=1.0)
    xcal, ycal, _, _ = matrix(cal, mean, sd)
    raw_cal = xcal @ beta
    platt = fit_logistic(np.column_stack([np.ones(len(cal)), raw_cal]), ycal, ridge=1e-6)
    xdev, ydev, _, _ = matrix(dev, mean, sd)
    raw_dev = xdev @ beta
    pdev = _sigmoid(platt[0] + platt[1] * raw_dev)
    for r, p in zip(dev, pdev):
        r["model_p_home"] = float(p)
        r["model_p_away"] = float(1.0 - p)

    metrics = calibration_metrics(ydev, pdev)
    diagnostic_pass = (
        CALIBRATION_SLOPE_MIN <= metrics["calibration_slope"] <= CALIBRATION_SLOPE_MAX
        and abs(metrics["calibration_intercept"]) <= CALIBRATION_INTERCEPT_ABS_MAX
        and metrics["ece_10_equal_frequency"] <= ECE_MAX
        and len(dev) >= MIN_SAMPLE
    )
    now = datetime.now(timezone.utc)
    artifact = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "market": "MONEYLINE",
        "market_blind": True,
        "forbidden_inputs": ["odds", "current_lines", "implied_probability", "public_betting", "consensus", "handicapper_opinion"],
        "training_seasons": [2023, 2024],
        "calibration_season": 2025,
        "development_diagnostic_season": 2026,
        "development_diagnostic_cutoff": cutoff.isoformat(),
        "feature_names": list(FEATURE_NAMES),
        "feature_standardization_mean": mean.tolist(),
        "feature_standardization_sd": sd.tolist(),
        "raw_logistic_beta": beta.tolist(),
        "platt_calibrator": {"intercept": float(platt[0]), "slope": float(platt[1])},
        "elo_k_factor": K_FACTOR,
        "historical_development_embargo_hours": HISTORICAL_EMBARGO_HOURS,
        "historical_development_only": True,
        "historical_availability_note": "48h embargo is a conservative development chronology rule, not source-attested publication time; it cannot grant promotion authority",
        "generated_at_utc": now.isoformat(),
        "forward_holdout_not_before_utc": now.isoformat(),
        "forward_holdout_rule": "only source observations captured with real observed_at_utc strictly before event_start_ts may count",
        "promotion_authority": False,
    }
    artifact["artifact_sha256"] = _sha(artifact)
    report = {
        "schema_version": 1,
        "model_artifact_sha256": artifact["artifact_sha256"],
        "development_sample_size": len(dev),
        "development_metrics": metrics,
        "development_calibration_diagnostic_pass": diagnostic_pass,
        "development_evidence_grants_promotion": False,
        "pre_2026_09_16_evidence_spent_for_selection": True,
        "forward_holdout_not_before_utc": artifact["forward_holdout_not_before_utc"],
        "truth_gate_complete": False,
        "promotion_authority": False,
        "remaining_blockers": [
            "real forward timestamp-attested PIT predictions after candidate freeze",
            "paired no-vig closing-price CLV evidence",
            "minimum frozen forward sample requirement",
            "fresh quote acquisition and identity binding",
            "production inference parity",
        ],
    }
    out = Path(args.artifact_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_artifact.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    (out / "development_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(dev), out / "development_predictions.parquet", compression="zstd")
    except ImportError as exc:
        raise RollingCandidateError("pyarrow required") from exc
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
