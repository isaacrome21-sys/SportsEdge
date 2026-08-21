from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.pga.live_model import (
    LiveWeights,
    PlayerLiveState,
    evaluate_live_truth_gate,
    live_expected_sg_per_round,
    simulate_remaining_tournament,
)


def _player(name: str, start: float, skill: float) -> PlayerLiveState:
    return PlayerLiveState(
        player=name,
        leaderboard_strokes_to_par=start,
        long_term_sg=skill,
        current_event_t2g_sg=skill,
        recent_form_sg=skill,
        course_fit_sg=skill,
        round_sd=2.0,
    )


def test_live_weights_sum_to_one_after_normalization():
    w = LiveWeights().normalized()
    total = (
        w.long_term_skill
        + w.current_event_ball_striking
        + w.recent_form
        + w.course_fit
        + w.putting_scrambling_sustainability
        + w.weather_tee_wave
        + w.volatility_error_profile
    )
    assert total == pytest.approx(1.0)


def test_current_event_ball_striking_moves_live_mean_without_overwriting_prior():
    state = PlayerLiveState(
        player="Player A",
        leaderboard_strokes_to_par=-2,
        long_term_sg=1.0,
        current_event_t2g_sg=3.0,
        recent_form_sg=1.0,
        course_fit_sg=1.0,
    )
    mu = live_expected_sg_per_round(state)
    assert mu > 1.0
    assert mu < 3.0


def test_simulation_starts_from_actual_leaderboard_and_rewards_skill():
    players = [
        _player("Leader", -6, 1.2),
        _player("Chaser", -4, 0.8),
        _player("Back", 1, 0.2),
    ]
    out = simulate_remaining_tournament(players, rounds_remaining=3, n_sims=20_000, seed=7)
    assert out["Leader"].win_prob > out["Back"].win_prob
    assert out["Leader"].expected_finish < out["Back"].expected_finish


def test_truth_gate_distinguishes_missing_from_stale_and_blocks_both():
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    result = evaluate_live_truth_gate(
        leaderboard_timestamp=None,
        tee_time_timestamp=now - timedelta(hours=1),
        weather_timestamp=now - timedelta(minutes=90),
        market_timestamp=now - timedelta(minutes=2),
        has_shot_level_data=True,
        wd_status_verified=True,
        market_rules_verified=True,
        edge=0.05,
        expected_value=0.06,
        min_edge=0.02,
        min_ev=0.02,
        now=now,
    )
    assert not result.passed
    assert "missing_leaderboard" in result.reasons
    assert any(reason.startswith("stale_weather:") for reason in result.reasons)


def test_missing_shot_level_data_only_downgrades_confidence():
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    result = evaluate_live_truth_gate(
        leaderboard_timestamp=now - timedelta(minutes=1),
        tee_time_timestamp=now - timedelta(hours=1),
        weather_timestamp=now - timedelta(minutes=10),
        market_timestamp=now - timedelta(minutes=2),
        has_shot_level_data=False,
        wd_status_verified=True,
        market_rules_verified=True,
        edge=0.05,
        expected_value=0.06,
        min_edge=0.02,
        min_ev=0.02,
        now=now,
    )
    assert result.passed
    assert result.confidence_tier == "B"
    assert "shot_level_missing_confidence_downgrade" in result.reasons
