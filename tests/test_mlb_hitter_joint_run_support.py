from __future__ import annotations

import pytest

from sportsedge.hitter_joint_engine import HitterJointEngineError, _normalize_pool


def _row(*, pa: int = 4, runs: int = 0, rbi: int = 0) -> dict[str, int]:
    return {
        "plate_appearances": pa,
        "hits": 1,
        "singles": 1,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "total_bases": 1,
        "rbi": rbi,
        "runs": runs,
        "stolen_bases": 0,
        "walks": 0,
        "strikeouts": 1,
        "extra_base_hits": 0,
    }


def test_pinch_runner_can_score_one_more_run_than_plate_appearances():
    pool = [_row() for _ in range(9)] + [_row(pa=1, runs=2)]
    normalized = _normalize_pool(pool)
    assert normalized[-1]["plate_appearances"] == 1
    assert normalized[-1]["runs"] == 2


def test_run_support_still_fails_closed_beyond_single_pinch_runner_run():
    pool = [_row() for _ in range(9)] + [_row(pa=1, runs=3)]
    with pytest.raises(HitterJointEngineError, match="violates run/RBI support"):
        _normalize_pool(pool)


def test_rbi_support_remains_bounded_by_four_per_plate_appearance():
    pool = [_row() for _ in range(9)] + [_row(pa=1, rbi=5)]
    with pytest.raises(HitterJointEngineError, match="violates run/RBI support"):
        _normalize_pool(pool)
