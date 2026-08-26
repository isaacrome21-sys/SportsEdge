import pytest

from sportsedge.pga.live_inputs import build_golfer_inputs


def test_build_golfer_inputs_maps_normalized_rows():
    golfers = build_golfer_inputs(
        [
            {
                "player": "Example Golfer",
                "strokes_to_par": -4,
                "long_term_sg": 1.1,
                "current_event_t2g_sg": 1.6,
                "recent_form_sg": 0.9,
                "course_fit_sg": 0.4,
                "approach_sg": 1.2,
                "gir_rate": 0.78,
            }
        ]
    )
    assert len(golfers) == 1
    state = golfers[0].to_state()
    assert state.player == "Example Golfer"
    assert state.leaderboard_strokes_to_par == pytest.approx(-4.0)
    assert state.approach_sg == pytest.approx(1.2)
    assert state.gir_rate == pytest.approx(0.78)


def test_build_golfer_inputs_requires_core_model_fields():
    with pytest.raises(ValueError, match="missing required fields"):
        build_golfer_inputs([{"player": "Incomplete"}])
