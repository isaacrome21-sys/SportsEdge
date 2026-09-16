from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from scripts.build_mlb_moneyline_preseason_evidence import calibration_metrics, fit_logistic

MODEL_VERSION = "mlb_moneyline_rolling_market_blind_v3"
CAL_SPLIT = datetime(2026, 7, 1, tzinfo=timezone.utc)
SLOPE_MIN = 0.90
SLOPE_MAX = 1.10
INTERCEPT_ABS_MAX = 0.03
ECE_MAX = 0.025
MIN_VALIDATION = 200


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _dt(text: str) -> datetime:
    out = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if out.tzinfo is None:
        raise ValueError("timezone required")
    return out.astimezone(timezone.utc)


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-x))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-artifact", default="artifacts/mlb_moneyline_rolling_v2/model_artifact.json")
    ap.add_argument("--development-predictions", default="artifacts/mlb_moneyline_rolling_v2/development_predictions.parquet")
    ap.add_argument("--output-dir", default="artifacts/mlb_moneyline_rolling_v3")
    args = ap.parse_args()

    base = json.loads(Path(args.base_artifact).read_text())
    rows = pq.read_table(args.development_predictions).to_pylist()
    early = [r for r in rows if _dt(r["event_start_ts"]) < CAL_SPLIT]
    late = [r for r in rows if _dt(r["event_start_ts"]) >= CAL_SPLIT]
    if len(early) < 200 or len(late) < MIN_VALIDATION:
        raise RuntimeError(f"insufficient temporal split early={len(early)} late={len(late)}")

    early_p = np.asarray([float(r["model_p_home"]) for r in early])
    early_y = np.asarray([float(r["home_win"]) for r in early])
    early_logit = _logit(early_p)
    second_stage = fit_logistic(np.column_stack([np.ones(len(early)), early_logit]), early_y, ridge=1e-6)

    late_p0 = np.asarray([float(r["model_p_home"]) for r in late])
    late_y = np.asarray([float(r["home_win"]) for r in late])
    late_p = _sigmoid(second_stage[0] + second_stage[1] * _logit(late_p0))
    metrics = calibration_metrics(late_y, late_p)
    passed = (
        SLOPE_MIN <= metrics["calibration_slope"] <= SLOPE_MAX
        and abs(metrics["calibration_intercept"]) <= INTERCEPT_ABS_MAX
        and metrics["ece_10_equal_frequency"] <= ECE_MAX
        and len(late) >= MIN_VALIDATION
    )

    generated = datetime.now(timezone.utc).isoformat()
    artifact = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "market": "MONEYLINE",
        "market_blind": True,
        "base_model_artifact_sha256": base["artifact_sha256"],
        "base_model_version": base["model_version"],
        "second_stage_temporal_calibrator": {
            "fit_window": f"2026 season start through {CAL_SPLIT.isoformat()} exclusive",
            "intercept": float(second_stage[0]),
            "slope": float(second_stage[1]),
        },
        "development_validation_window": f"{CAL_SPLIT.isoformat()} through 2026-09-15",
        "development_validation_consumed_for_selection": True,
        "forbidden_inputs": base["forbidden_inputs"],
        "market_data_used_as_model_feature": False,
        "generated_at_utc": generated,
        "forward_holdout_not_before_utc": generated,
        "forward_holdout_rule": "new observations only; source observed_at_utc must be strictly before event_start_ts; no pre-freeze row may count",
        "promotion_authority": False,
    }
    artifact["artifact_sha256"] = _sha(artifact)
    report = {
        "schema_version": 1,
        "model_artifact_sha256": artifact["artifact_sha256"],
        "calibration_fit_sample": len(early),
        "development_validation_sample": len(late),
        "development_validation_metrics": metrics,
        "development_validation_gate_pass": passed,
        "development_validation_grants_promotion": False,
        "truth_gate_complete": False,
        "promotion_authority": False,
        "forward_holdout_not_before_utc": generated,
        "remaining_blockers": [
            "merge frozen lane/model to main before promotion evidence clock can start",
            "real forward timestamp-attested Model_P rows",
            "paired two-sided pregame and close quotes for CLV",
            "50/100/150 fixed promotion-policy checkpoints",
            "production inference parity for exact v3 artifact",
        ],
    }
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_artifact.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    (out / "development_validation_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
