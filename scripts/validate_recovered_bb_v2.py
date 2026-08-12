#!/usr/bin/env python3
"""External validation of the frozen recovered pitcher-BB v2 artifact.

This does not retrain, recalibrate, or modify v2. The artifact predates the 2025/2026
checks and is extracted byte-for-byte from the recovered automation wrapper. Because
this candidate is being examined after BB-v4's 2026 1.5-line miss was observed, the
result is explicitly classified as POST_HOC_CANDIDATE_COMPARISON, not a pristine
model-selection holdout. Acceptance therefore requires independent passing evidence
on both 2025 and source-bounded 2026, plus the artifact's original 2024 holdout pass.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import zipfile

import joblib
import numpy as np

import scripts.rebuild_pitcher_bb_v4 as metrics
import scripts.rebuild_pitcher_bb_v4_1 as strict

WRAPPER = Path("SportsEdge_Automation_Wrapper_v1_1_1.zip")
MEMBER = "SportsEdge_Automation_Wrapper_v1_1_1/sportsedge_pitcher_bb_v2.joblib"


def load_frozen_artifact():
    if not WRAPPER.exists():
        raise RuntimeError("RECOVERED_WRAPPER_MISSING")
    with zipfile.ZipFile(WRAPPER) as zf:
        if MEMBER not in zf.namelist():
            raise RuntimeError("RECOVERED_BB_V2_MISSING")
        raw = zf.read(MEMBER)
    with tempfile.NamedTemporaryFile(suffix=".joblib") as fh:
        fh.write(raw)
        fh.flush()
        artifact = joblib.load(fh.name)
    return artifact, raw


def season_report(models, X, walks, years, season: int):
    mask = years == season
    result = {}
    all_pass = True
    for line in metrics.THRESHOLDS:
        key = str(line)
        model = models[key]
        y = (walks > line).astype(int)
        p = model.predict_proba(X[mask])[:, 1]
        aggregate = metrics.metric_with_ci(p, y[mask])
        buckets = metrics.diagnostic_buckets(p, y[mask])
        passed = aggregate["z"] <= 2.5 and max([b["z"] for b in buckets] or [0.0]) <= 3.0
        all_pass &= passed
        result[key] = {
            "pass": bool(passed),
            "aggregate": aggregate,
            "probability_buckets": buckets,
        }
    return {"season": season, "rows": int(mask.sum()), "all_thresholds_pass": bool(all_pass), "thresholds": result}


def main():
    artifact, raw = load_frozen_artifact()
    metadata = artifact.get("metadata") or {}
    models = artifact.get("models") or {}
    expected_features = list(metadata.get("feature_list") or [])
    actual_features = list(metrics.FEATURES)
    feature_contract_exact = expected_features == actual_features
    model_feature_counts_exact = all(getattr(models.get(str(line)), "n_features_in_", None) == len(actual_features) for line in metrics.THRESHOLDS)
    original_2024_pass = bool(metadata.get("all_common_thresholds_pass_2se"))
    if not feature_contract_exact or not model_feature_counts_exact:
        raise RuntimeError("RECOVERED_BB_V2_FEATURE_CONTRACT_MISMATCH")

    root = Path(".cache/sportsedge/bb-rebuild")
    games, excluded = strict.fetch_schedule_strict(root / "schedule")
    metrics.old.ensure_boxes(games, root / "boxscores")
    X, walks, years, identities = metrics.build_cutoff(games, root / "boxscores")

    report_2025 = season_report(models, X, walks, years, 2025)
    report_2026 = season_report(models, X, walks, years, 2026)
    dates_2026 = [g["officialDate"] for g in games if int(g["year"]) == 2026]
    source_bound_pass = bool(dates_2026) and max(dates_2026) <= "2026-08-10"

    overall = bool(
        original_2024_pass
        and report_2025["all_thresholds_pass"]
        and report_2026["all_thresholds_pass"]
        and source_bound_pass
    )
    validation = {
        "schema_version": "recovered_pitcher_bb_v2_external_validation_v1",
        "evidence_class": "POST_HOC_CANDIDATE_COMPARISON_NOT_PRISTINE_MODEL_SELECTION_HOLDOUT",
        "artifact_source": str(WRAPPER),
        "artifact_member": MEMBER,
        "artifact_metadata": metadata,
        "feature_contract_exact": feature_contract_exact,
        "model_feature_counts_exact": model_feature_counts_exact,
        "chronology_policy": "OFFICIAL_DATE_PRIOR_DAY_SNAPSHOT_APPLY_RESULTS_AFTER_DAY",
        "source_range_policy": "EVERY_RESPONSE_AND_CACHE_ROW_MUST_MATCH_REQUESTED_INTERVAL",
        "source_bound_assertion_pass": source_bound_pass,
        "observed_2026_date_max": max(dates_2026) if dates_2026 else None,
        "source_range_violation_count": sum(1 for x in excluded if x.get("reason_code") == "SOURCE_RANGE_VIOLATION"),
        "original_2024_holdout_pass_all_common_thresholds_2se": original_2024_pass,
        "external_2025": report_2025,
        "external_2026_through_aug10": report_2026,
        "all_required_evidence_pass": overall,
        "rows": int(len(X)),
        "identity_rows": int(len(identities)),
        "policy": "NO_RETRAIN_NO_RECALIBRATION_NO_TOLERANCE_CHANGE_NO_SPORTSBOOK_FEATURES",
    }
    out = Path("artifacts/recovered_bb_v2_external_validation.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "feature_contract_exact": feature_contract_exact,
        "original_2024_pass": original_2024_pass,
        "2025_pass": report_2025["all_thresholds_pass"],
        "2026_pass": report_2026["all_thresholds_pass"],
        "source_bound_pass": source_bound_pass,
        "overall": overall,
    }, indent=2, sort_keys=True))
    return 0 if overall else 2


if __name__ == "__main__":
    raise SystemExit(main())
