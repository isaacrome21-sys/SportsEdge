import json
from pathlib import Path

import pytest

from sportsedge.research.nfl_prop_usage_v1_validate_2025 import (
    FIT_RAW_SHA,
    FIT_SHA,
    INACTIVE_AUDIT_SHA,
    SOURCE_AUDIT_SHA,
    admitted_inactive_index,
    evaluate_rows,
    load_lock,
    normal_over_probability,
)


def test_validation_lock_exact_identities_and_one_look():
    cfg = load_lock()
    assert cfg["fit_identity"]["fit_artifact_sha256"] == FIT_SHA
    assert cfg["fit_identity"]["fit_json_raw_sha256"] == FIT_RAW_SHA
    assert cfg["source_identity"]["source_audit_sha256"] == SOURCE_AUDIT_SHA
    assert cfg["source_identity"]["pre_kick_inactive_audit_sha256"] == INACTIVE_AUDIT_SHA
    assert cfg["validation_window"]["status"] == "UNSPENT"
    assert cfg["validation_window"]["one_look"] is True
    assert cfg["validation_window"]["second_look"] is False
    assert cfg["cohort"]["missing_or_ambiguous_evidence"] == "ZERO_MODEL_ROWS"


def test_normal_over_probability_direction():
    assert normal_over_probability(100.0, 10.0, 100.0) == pytest.approx(0.5)
    assert normal_over_probability(110.0, 10.0, 100.0) > 0.5
    assert normal_over_probability(90.0, 10.0, 100.0) < 0.5


def test_metric_contract_uses_abs_mean_gap_and_brier():
    rows = [
        {
            "candidate_p_over": 0.60,
            "baseline_p_over": 0.55,
            "observed_over": 1,
        },
        {
            "candidate_p_over": 0.40,
            "baseline_p_over": 0.45,
            "observed_over": 0,
        },
    ]
    out = evaluate_rows(rows)
    assert out["n"] == 2
    assert out["mean_predicted_over"] == pytest.approx(0.5)
    assert out["observed_over_rate"] == pytest.approx(0.5)
    assert out["calibration_gap"] == pytest.approx(0.0)
    assert out["candidate_brier"] == pytest.approx(0.16)
    assert out["baseline_brier"] == pytest.approx(0.2025)


def test_inactive_index_requires_exact_52_unique_admitted_games():
    games = []
    for i in range(52):
        week = i % 18 + 1
        a = f"T{i:02d}A"
        b = f"T{i:02d}B"
        games.append({
            "admissible": True,
            "week": week,
            "kickoff_at": f"2025-10-{i % 28 + 1:02d}T17:00:00-04:00",
            "source_url": f"https://example.com/{i}",
            "teams": [{"team": a}, {"team": b}],
            "inactive_by_team": {a: ["Player One"], b: ["Player Two"]},
        })
    idx = admitted_inactive_index({"admitted_games": games})
    assert len(idx) == 52
    first = next(iter(idx.values()))
    assert "player one" in next(iter(first["inactive"].values()))

    with pytest.raises(Exception, match="INACTIVE_ADMITTED_INDEX_DRIFT"):
        admitted_inactive_index({"admitted_games": games[:-1]})
