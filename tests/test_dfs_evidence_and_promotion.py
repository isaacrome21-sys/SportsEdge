from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.dfs.calibration import (
    ProjectionCalibrationMetrics,
    ProjectionObservation,
    evaluate_projection_calibration,
)
from sportsedge.dfs.mlb_joint_v2 import _bullpen_preserved_lead, _split_runs_at_exit
from sportsedge.dfs.objective import DEFAULT_OBJECTIVE_WEIGHTS, ObjectiveWeights
from sportsedge.dfs.ownership_evidence import ingest_standings_csv, write_immutable_evidence
from sportsedge.dfs.projection_promotion import (
    ContestOutcomeMetrics,
    evaluate_projection_promotion,
)
from sportsedge.dfs.tuning import BacktestMetrics, HistoricalSlate, chronological_holdout_tune


def test_starter_win_requires_lead_at_exit_and_unrelinquished_lead() -> None:
    import random

    rng = random.Random(7)
    # Final score can be a win, but a starter who exits trailing cannot receive W.
    assert not _bullpen_preserved_lead(
        rng,
        own_pre=2,
        opp_pre=3,
        own_post=[0, 0, 0, 0, 0, 0, 2, 2, 0],
        opp_post=[0] * 9,
    )
    # A lead that is tied after exit is relinquished even if the team later retakes it.
    rng = random.Random(3)
    assert not _bullpen_preserved_lead(
        rng,
        own_pre=4,
        opp_pre=3,
        own_post=[0, 0, 0, 0, 0, 0, 0, 1, 0],
        opp_post=[0, 0, 0, 0, 0, 0, 1, 0, 0],
    )


def test_starter_exit_split_does_not_charge_all_nine_innings() -> None:
    import random

    # Starter records 15 outs: only first five innings are before exit.
    pre, post = _split_runs_at_exit(
        random.Random(1),
        [0, 1, 0, 0, 1, 4, 3, 2, 1],
        15,
    )
    assert pre == 2
    assert sum(post) == 10


def test_postcontest_ownership_evidence_is_exact_and_immutable(tmp_path) -> None:
    raw = (
        "EntryId,EntryName,Points,Lineup\n"
        '1,A,200,"QB Alpha QB RB Runner One RB Runner Two WR Wide One WR Wide Two WR Wide Three TE Tight One FLEX Flex One DST Defense One"\n'
        '2,B,190,"QB Alpha QB RB Runner One RB Runner Three WR Wide One WR Wide Four WR Wide Five TE Tight Two FLEX Flex Two DST Defense Two"\n'
    ).encode()
    evidence = ingest_standings_csv(
        raw,
        sport="NFL",
        contest_id="12345",
        contest_name="Single Entry",
        draft_group_id="77",
        slate_start=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        captured_at=datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc),
    )
    assert evidence.valid_entries == 2
    by_name = {p.display_name: p for p in evidence.players}
    assert by_name["Alpha QB"].ownership == 1.0
    assert by_name["Runner Two"].ownership == 0.5
    out = tmp_path / "ownership.json"
    write_immutable_evidence(evidence, out)
    with pytest.raises(FileExistsError):
        write_immutable_evidence(evidence, out)


def test_malformed_standings_lineup_blocks_evidence() -> None:
    raw = (
        "EntryId,Lineup\n"
        '1,"QB Alpha RB One WR Missing Slots"\n'
    ).encode()
    with pytest.raises(ValueError, match="DFS_OWNERSHIP_MALFORMED_ROW"):
        ingest_standings_csv(raw, sport="NFL", contest_id="x")


def test_projection_calibration_metrics_use_player_observations() -> None:
    rows = []
    # Construct 1,000 observations with calibrated threshold frequencies:
    # >p10 = 90%, >p50 = 50%, >p90 = 10%, [p10,p90] = 80%.
    for i in range(1000):
        if i < 100:
            actual = 5.0
        elif i < 500:
            actual = 15.0
        elif i < 900:
            actual = 25.0
        else:
            actual = 35.0
        rows.append(ProjectionObservation(str(i), actual, 20.0, 10.0, 20.0, 30.0))
    metrics = evaluate_projection_calibration(rows)
    assert metrics.observations == 1000
    assert metrics.quantile_calibration_error < 1e-12
    assert metrics.central_80_coverage == pytest.approx(0.8)


def _cal(qce: float, rmse: float = 6.0, mae: float = 4.5) -> ProjectionCalibrationMetrics:
    return ProjectionCalibrationMetrics(
        observations=1200,
        mae=mae,
        rmse=rmse,
        exceed_p10_rate=0.90,
        exceed_p50_rate=0.50,
        exceed_p90_rate=0.10,
        central_80_coverage=0.80,
        quantile_calibration_error=qce,
    )


def test_great_contest_roi_cannot_rescue_worse_calibration() -> None:
    decision = evaluate_projection_promotion(
        candidate=_cal(0.060, rmse=6.2, mae=4.7),
        baseline=_cal(0.020, rmse=6.0, mae=4.5),
        candidate_contest=ContestOutcomeMetrics(40, 0.80, 0.08, 0.25),
        baseline_contest=ContestOutcomeMetrics(40, 0.00, 0.01, 0.30),
    )
    assert not decision.promoted
    assert "NO_CALIBRATION_OR_ERROR_IMPROVEMENT" in decision.reason


def test_better_calibration_can_promote_with_slightly_worse_roi_inside_veto() -> None:
    decision = evaluate_projection_promotion(
        candidate=_cal(0.012, rmse=5.98, mae=4.48),
        baseline=_cal(0.020, rmse=6.0, mae=4.5),
        candidate_contest=ContestOutcomeMetrics(40, -0.04, 0.009, 0.31),
        baseline_contest=ContestOutcomeMetrics(40, 0.00, 0.010, 0.30),
    )
    assert decision.promoted
    assert decision.reason == "CALIBRATION_HOLDOUT_PASS"


def test_objective_tuning_never_auto_promotes_on_roi_alone() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    slates = tuple(
        HistoricalSlate(f"s{i}", t0 + timedelta(days=i), f"/frozen/s{i}.json")
        for i in range(40)
    )
    candidate = ObjectiveWeights(version="CANDIDATE", upside_weight=0.44)

    def evaluator(weights, subset):
        better = weights.version == "CANDIDATE"
        return BacktestMetrics(
            slate_count=len(subset),
            roi=0.50 if better else 0.0,
            top_one_percent_rate=0.10 if better else 0.01,
            cash_rate=0.40 if better else 0.20,
            max_drawdown=0.20,
        )

    result = chronological_holdout_tune(
        slates=slates,
        baseline=DEFAULT_OBJECTIVE_WEIGHTS,
        candidates=(candidate,),
        evaluator=evaluator,
        min_holdout_slates=10,
    )
    assert not result.promoted
    assert result.selected == DEFAULT_OBJECTIVE_WEIGHTS
    assert "NO_POLICY_PROMOTION_AUTHORITY" in result.reason
