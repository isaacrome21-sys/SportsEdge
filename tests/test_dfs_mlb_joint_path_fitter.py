from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.dfs.mlb_joint_path_fitter import (
    HistoricalBaserunningOpportunity,
    HistoricalHookOpportunity,
    HistoricalPlateAppearance,
    MlbJointPathFitError,
    MlbJointPathFitPolicy,
    fit_baserunning_profile,
    fit_hook_hazard_surface,
    fit_plate_appearance_profile,
    fit_receipt,
)

UTC = timezone.utc
SOURCE_A = "a" * 64
SOURCE_B = "b" * 64
CUTOFF = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _policy(**overrides) -> MlbJointPathFitPolicy:
    values = dict(
        policy_id="MLB_DFS_JOINT_PATH_FIT_TEST_V1",
        status="FROZEN",
        cutoff_at=CUTOFF,
        min_pa=4,
        min_hook_cell_trials=1,
        min_baserunning_opportunities=2,
        pitch_count_upper_bounds=(50, 220),
        runs_allowed_upper_bounds=(0, 25),
    )
    values.update(overrides)
    return MlbJointPathFitPolicy(**values)


def _pa(minutes: int, outcome: str, pitches: int, *, role: str = "STARTER") -> HistoricalPlateAppearance:
    return HistoricalPlateAppearance(
        occurred_at=CUTOFF - timedelta(minutes=minutes),
        batter_id="H1",
        pitcher_role=role,
        outcome=outcome,
        pitch_count=pitches,
        source_sha256=SOURCE_A,
    )


def test_policy_must_be_frozen_before_any_fit() -> None:
    rows = [_pa(4, "OUT", 3), _pa(3, "OUT", 4), _pa(2, "K", 4), _pa(1, "HR", 5)]
    with pytest.raises(MlbJointPathFitError, match="POLICY_NOT_FROZEN"):
        fit_plate_appearance_profile(
            rows,
            policy=_policy(status="UNFROZEN"),
            batter_id="H1",
            pitcher_role="STARTER",
            source_label="pa-h1",
        )


def test_non_prior_observation_is_rejected_not_silently_filtered() -> None:
    rows = [_pa(4, "OUT", 3), _pa(3, "OUT", 4), _pa(2, "K", 4), _pa(1, "HR", 5)]
    rows.append(
        HistoricalPlateAppearance(
            occurred_at=CUTOFF,
            batter_id="H1",
            pitcher_role="STARTER",
            outcome="OUT",
            pitch_count=3,
            source_sha256=SOURCE_A,
        )
    )
    with pytest.raises(MlbJointPathFitError, match="NON_PRIOR_OBSERVATION"):
        fit_plate_appearance_profile(
            rows,
            policy=_policy(),
            batter_id="H1",
            pitcher_role="STARTER",
            source_label="pa-h1",
        )


def test_plate_appearance_fit_is_pure_empirical_and_source_bound() -> None:
    rows = [_pa(4, "OUT", 3), _pa(3, "OUT", 4), _pa(2, "K", 4), _pa(1, "HR", 5)]
    profile = fit_plate_appearance_profile(
        rows,
        policy=_policy(),
        batter_id="H1",
        pitcher_role="STARTER",
        source_label="pa-h1",
    )
    assert profile.outcome_probabilities == {"HR": 0.25, "K": 0.25, "OUT": 0.5}
    assert profile.pitch_count_probabilities == {3: 0.25, 4: 0.5, 5: 0.25}
    assert profile.source_id.startswith("pa-h1:")

    changed = list(rows)
    changed[-1] = HistoricalPlateAppearance(
        occurred_at=CUTOFF - timedelta(minutes=1),
        batter_id="H1",
        pitcher_role="STARTER",
        outcome="HR",
        pitch_count=5,
        source_sha256=SOURCE_B,
    )
    changed_profile = fit_plate_appearance_profile(
        changed,
        policy=_policy(),
        batter_id="H1",
        pitcher_role="STARTER",
        source_label="pa-h1",
    )
    assert changed_profile.outcome_probabilities == profile.outcome_probabilities
    assert changed_profile.source_id != profile.source_id


def test_pa_fit_fails_closed_on_insufficient_player_role_support() -> None:
    rows = [_pa(3, "OUT", 3), _pa(2, "OUT", 4), _pa(1, "K", 4)]
    with pytest.raises(MlbJointPathFitError, match="PA_INSUFFICIENT"):
        fit_plate_appearance_profile(
            rows,
            policy=_policy(),
            batter_id="H1",
            pitcher_role="STARTER",
            source_label="pa-h1",
        )


def test_hook_surface_requires_support_in_every_preregistered_cell() -> None:
    rows = [
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=8), 40, 0, False, SOURCE_A),
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=7), 40, 3, True, SOURCE_A),
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=6), 90, 0, False, SOURCE_A),
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=5), 90, 3, True, SOURCE_A),
    ]
    hook = fit_hook_hazard_surface(rows, policy=_policy(), source_label="hook-all")
    assert hook.remove_probabilities == ((0.0, 1.0), (0.0, 1.0))

    with pytest.raises(MlbJointPathFitError, match="HOOK_CELL_INSUFFICIENT"):
        fit_hook_hazard_surface(rows[:-1], policy=_policy(), source_label="hook-all")


def test_baserunning_profile_requires_every_declared_opportunity_class() -> None:
    rows = [
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=9), "SINGLE_SECOND_SCORES", True, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=8), "SINGLE_SECOND_SCORES", False, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=7), "SINGLE_FIRST_TO_THIRD", True, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=6), "SINGLE_FIRST_TO_THIRD", True, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=5), "DOUBLE_FIRST_SCORES", False, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=4), "DOUBLE_FIRST_SCORES", True, SOURCE_A),
    ]
    profile = fit_baserunning_profile(rows, policy=_policy(), source_label="baserun")
    assert profile.single_second_scores == 0.5
    assert profile.single_first_to_third == 1.0
    assert profile.double_first_scores == 0.5

    with pytest.raises(MlbJointPathFitError, match="BASERUN_INSUFFICIENT"):
        fit_baserunning_profile(rows[:-1], policy=_policy(), source_label="baserun")


def test_fit_receipt_is_zero_authority_and_deterministic() -> None:
    pa_rows = [_pa(4, "OUT", 3), _pa(3, "OUT", 4), _pa(2, "K", 4), _pa(1, "HR", 5)]
    pa = fit_plate_appearance_profile(
        pa_rows,
        policy=_policy(),
        batter_id="H1",
        pitcher_role="STARTER",
        source_label="pa-h1",
    )
    hook_rows = [
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=8), 40, 0, False, SOURCE_A),
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=7), 40, 3, True, SOURCE_A),
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=6), 90, 0, False, SOURCE_A),
        HistoricalHookOpportunity(CUTOFF - timedelta(minutes=5), 90, 3, True, SOURCE_A),
    ]
    hook = fit_hook_hazard_surface(hook_rows, policy=_policy(), source_label="hook-all")
    baserun_rows = [
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=9), "SINGLE_SECOND_SCORES", True, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=8), "SINGLE_SECOND_SCORES", False, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=7), "SINGLE_FIRST_TO_THIRD", True, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=6), "SINGLE_FIRST_TO_THIRD", True, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=5), "DOUBLE_FIRST_SCORES", False, SOURCE_A),
        HistoricalBaserunningOpportunity(CUTOFF - timedelta(minutes=4), "DOUBLE_FIRST_SCORES", True, SOURCE_A),
    ]
    baserun = fit_baserunning_profile(baserun_rows, policy=_policy(), source_label="baserun")
    first = fit_receipt(policy=_policy(), pa_profiles={"H1:STARTER": pa}, hook_surfaces={"ALL": hook}, baserunning=baserun)
    second = fit_receipt(policy=_policy(), pa_profiles={"H1:STARTER": pa}, hook_surfaces={"ALL": hook}, baserunning=baserun)
    assert first == second
    assert len(first["bundle_sha256"]) == 64
    assert first["dfs_production_ready"] is False
    assert first["model_p_authority"] is False
    assert first["promotion_authority"] is False
