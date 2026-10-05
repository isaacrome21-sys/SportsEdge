from pathlib import Path

import pytest

from scripts.run_nfl_score_counts_attempt import (
    IDENTITY_PATHS,
    PREREG_BY_ATTEMPT,
    code_identity,
    run_attempt,
)


def test_code_identity_is_stable_sha256():
    first = code_identity(Path("."))
    second = code_identity(Path("."))
    assert first == second
    assert len(first) == 64
    int(first, 16)
    assert "sportsedge/sports/nfl/score_counts_source_projection.py" in IDENTITY_PATHS


def test_attempt_confirmation_is_required_before_any_source_access(tmp_path):
    with pytest.raises(RuntimeError, match="ATTEMPT_CONFIRMATION_REQUIRED"):
        run_attempt(attempt_number=1, confirm="NO", output_dir=tmp_path / "attempt")


def test_attempt_number_fails_outside_frozen_budget(tmp_path):
    with pytest.raises(RuntimeError, match="ATTEMPT_NUMBER_OUT_OF_FROZEN_BUDGET"):
        run_attempt(
            attempt_number=4,
            confirm="CONSUME_SCORE_COUNTS_ATTEMPT_4",
            output_dir=tmp_path / "attempt",
        )


def test_source_root_cannot_live_inside_uploaded_artifact_tree(tmp_path):
    output = tmp_path / "artifact"
    with pytest.raises(RuntimeError, match="SOURCE_ROOT_MUST_BE_OUTSIDE_ARTIFACT_OUTPUT"):
        run_attempt(
            attempt_number=1,
            confirm="CONSUME_SCORE_COUNTS_ATTEMPT_1",
            output_dir=output,
            source_root=output / "sources",
        )


def test_attempt2_prereg_is_bound_into_runner_identity():
    path = "config/research/nfl_score_counts_g1_attempt2_fg_prereg_v1.json"
    assert path in IDENTITY_PATHS
    assert PREREG_BY_ATTEMPT[2] == Path(path)


def test_attempt3_fails_closed_until_preregistered(tmp_path):
    with pytest.raises(RuntimeError, match="ATTEMPT_PREREG_REQUIRED:3"):
        run_attempt(
            attempt_number=3,
            confirm="CONSUME_SCORE_COUNTS_ATTEMPT_3",
            output_dir=tmp_path / "attempt3",
        )
