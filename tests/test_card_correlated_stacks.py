"""RED: a card must not count one correlated thesis as N independent positions."""
import pytest

from sportsedge.card_correlation import grade_card_positions, group_correlated_stacks


def _row(game, sel, result=None, thesis=None):
    r = {"game_id": game, "selection": sel}
    if result is not None:
        r["result"] = result
    if thesis is not None:
        r["thesis_id"] = thesis
    return r


def test_same_game_rows_without_thesis_collapse_to_one_stack():
    rows = [_row("G1", f"leg{i}", "LOSS") for i in range(9)]
    stacks = group_correlated_stacks(rows)
    assert len(stacks) == 1
    assert stacks[0]["n_legs"] == 9


def test_nine_leg_one_thesis_grades_as_one_loss_not_nine():
    rows = [_row("G1", f"leg{i}", "LOSS") for i in range(9)]
    rec = grade_card_positions(rows)
    assert rec["positions"] == 1
    assert rec["losses"] == 1
    assert rec["wins"] == 0
    assert rec["legs"] == 9


def test_distinct_games_are_distinct_positions():
    rows = [_row("G1", "a", "WIN"), _row("G2", "b", "LOSS")]
    rec = grade_card_positions(rows)
    assert rec["positions"] == 2 and rec["wins"] == 1 and rec["losses"] == 1


def test_explicit_thesis_spans_games():
    rows = [_row("G1", "a", "WIN", thesis="T"), _row("G2", "b", "WIN", thesis="T")]
    assert grade_card_positions(rows)["positions"] == 1


def test_mixed_stack_is_mixed_not_win():
    rows = [_row("G1", "a", "WIN"), _row("G1", "b", "LOSS")]
    rec = grade_card_positions(rows)
    assert rec["positions"] == 1 and rec["mixed"] == 1 and rec["wins"] == 0


def test_unsettled_leg_makes_stack_pending():
    rows = [_row("G1", "a", "WIN"), _row("G1", "b")]
    rec = grade_card_positions(rows)
    assert rec["pending"] == 1 and rec["wins"] == 0


def test_missing_game_and_thesis_fails_closed():
    with pytest.raises(ValueError):
        group_correlated_stacks([{"selection": "x", "result": "WIN"}])


def test_push_and_void_legs_ignored_when_others_settled():
    rows = [_row("G1", "a", "WIN"), _row("G1", "b", "PUSH")]
    assert grade_card_positions(rows)["wins"] == 1
    rows = [_row("G1", "a", "VOID")]
    assert grade_card_positions(rows)["no_action"] == 1


def test_unknown_result_rejected():
    with pytest.raises(ValueError):
        grade_card_positions([_row("G1", "a", "MAYBE")])
