#!/usr/bin/env python3
"""Diagnose numerical compatibility for the frozen NFL attempt-9 result.

This is a provenance diagnostic only. It never changes expected hashes, candidate
ownership, promotion state, or Model_P authority. Run each thread configuration
in a fresh process so BLAS reads its environment before NumPy initializes.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import platform

from scripts import build_nfl_attempt9_runtime_artifact as builder


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def _runtime_text() -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            builder.np.show_runtime()
        except Exception as exc:
            print(f"NUMPY_SHOW_RUNTIME_UNAVAILABLE:{type(exc).__name__}:{exc}")
    return buffer.getvalue().strip()


def diagnose(source_config: Path) -> dict:
    cfg = json.loads(source_config.read_text(encoding="utf-8"))
    source = cfg["sources"]["nfl_attempt9"]
    raw = builder._fetch(source["raw_url"])
    source_sha = builder._sha256(raw)
    if source_sha != source["expected_sha256"]:
        raise RuntimeError(
            f"NFL_ATTEMPT9_SOURCE_SHA_MISMATCH:{source_sha}:{source['expected_sha256']}"
        )
    games = builder.parse_games(raw)
    x, margin, total, dates = builder.build_features(games)
    targets = {
        "margin": builder.fit_target(x, margin, dates, builder.TARGETS["margin"]),
        "total": builder.fit_target(x, total, dates, builder.TARGETS["total"]),
    }
    result_targets = {}
    all_coefficients_exact = True
    all_predictions_exact = True
    for name, target in targets.items():
        expected_coeff = builder._float_list_json(builder.EXPECTED_COEFFICIENTS[name])
        actual_coeff = str(target["coefficient_json"])
        expected_prediction_sha = source["holdout_prediction_sha256"][name]
        coeff_exact = actual_coeff == expected_coeff
        prediction_exact = target["holdout_prediction_sha256"] == expected_prediction_sha
        all_coefficients_exact = all_coefficients_exact and coeff_exact
        all_predictions_exact = all_predictions_exact and prediction_exact
        result_targets[name] = {
            "coefficient_json": actual_coeff,
            "coefficient_text_exact": coeff_exact,
            "coefficient_json_sha256": target["coefficient_json_sha256"],
            "holdout_prediction_sha256": target["holdout_prediction_sha256"],
            "holdout_prediction_exact": prediction_exact,
            "holdout_rmse": target["holdout_rmse"],
        }
    return {
        "schema_version": "SPORTSEDGE_NFL_ATTEMPT9_NUMERIC_DIAGNOSTIC_V1",
        "status": "DIAGNOSTIC_ONLY_NO_AUTHORITY",
        "source_sha256": source_sha,
        "thread_environment": {
            key: os.environ.get(key) for key in builder.THREAD_ENV_KEYS
        },
        "cpu_model": _cpu_model(),
        "platform_machine": platform.machine(),
        "numpy_version": builder.np.__version__,
        "numpy_runtime": _runtime_text(),
        "all_coefficients_text_exact": all_coefficients_exact,
        "all_predictions_exact": all_predictions_exact,
        "exact_full_compatibility": all_coefficients_exact and all_predictions_exact,
        "targets": result_targets,
        "authority": {
            "creates_model_p": False,
            "changes_candidate": False,
            "changes_expected_hash": False,
            "promotion_authority": False,
            "official_authority": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-config",
        type=Path,
        default=builder.DEFAULT_SOURCES,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = diagnose(args.source_config)
    text = json.dumps(result, sort_keys=True)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
