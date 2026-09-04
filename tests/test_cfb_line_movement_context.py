from sportsedge.cfb_line_movement_context import normalize_cfb_line_movement, pregame_view


def test_todd_fuhrman_recap_keeps_postgame_results_out_of_pregame_view():
    row = {
        "game": "Massachusetts @ Rutgers",
        "side_open": -30.5,
        "side_current_or_close": -30.0,
        "side_move_points": 0.5,
        "total_open": 55.0,
        "total_current_or_close": 55.0,
        "total_move_points": 0.0,
        "final_score": "37-21",
        "ats_winner": "Massachusetts",
        "ou_result": "Over",
        "move_side_won": True,
    }
    obs = normalize_cfb_line_movement(row, source="@ToddFuhrman")
    assert obs["source_role"] == "CONTEXT_ONLY"
    assert obs["model_p_eligible"] is False
    assert obs["truth_gate_eligible"] is False
    assert obs["postgame_only"]["ats_winner"] == "Massachusetts"

    live = pregame_view(obs)
    assert "postgame_only" not in live
    assert "ats_winner" not in live
    assert live["side_move_points"] == 0.5


def test_move_is_computed_when_not_supplied():
    obs = normalize_cfb_line_movement({
        "game": "UAB @ Illinois",
        "side_open": -27.5,
        "side_current_or_close": -25.5,
        "total_open": 56.5,
        "total_current_or_close": 53.5,
    })
    assert obs["side_move_points"] == 2.0
    assert obs["total_move_points"] == -3.0
