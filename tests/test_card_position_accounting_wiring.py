"""RED: RUN IT card output must carry correlated-stack position accounting
over the surfaced research rows, so N same-game legs read as 1 position."""
from artifacts.run_it_full import attach_position_accounting


def _card(rows_e, rows_i):
    return {"edges": rows_e, "independent_candidates": rows_i,
            "independent_watchlist": [], "summary": {}}


def test_nine_same_game_leans_are_one_position():
    leans = [{"game": "MIL@LAD", "selection": f"s{i}", "input_index": i} for i in range(9)]
    card = attach_position_accounting(_card([], leans))
    pa = card["position_accounting"]
    assert pa["positions"] == 1 and pa["legs"] == 9
    assert pa["accounting"] == "CORRELATED_STACK_AS_SINGLE_POSITION"
    assert card["summary"]["surfaced_positions"] == 1
    assert card["summary"]["surfaced_legs"] == 9


def test_rows_in_edges_and_candidates_counted_once():
    r = {"game": "G1", "selection": "a", "input_index": 0}
    card = attach_position_accounting(_card([r], [dict(r)]))
    assert card["position_accounting"]["legs"] == 1


def test_two_games_two_positions_and_no_probability_added():
    rows = [{"game": "G1", "selection": "a", "input_index": 0},
            {"game": "G2", "selection": "b", "input_index": 1}]
    card = attach_position_accounting(_card(rows, []))
    assert card["position_accounting"]["positions"] == 2
    for s in card["position_accounting"]["stacks"]:
        for leg in s["legs"]:
            assert set(leg) <= {"game_id", "thesis_id", "selection", "input_index", "result"}


def test_row_without_game_is_reported_not_silently_dropped():
    card = attach_position_accounting(_card([{"selection": "x", "input_index": 3}], []))
    assert card["position_accounting"]["unkeyed_rows"] == [3]
    assert card["position_accounting"]["status"] == "INCOMPLETE_CORRELATION_KEYS"


def test_empty_card():
    card = attach_position_accounting(_card([], []))
    assert card["position_accounting"]["positions"] == 0


def test_run_full_card_carries_accounting():
    from datetime import datetime, timezone
    from artifacts.run_it_full import run_full
    card = run_full({"lines": [], "sport": "MLB"},
                    now=datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc), auto_context=False)
    assert "position_accounting" in card


def test_audit_same_selection_text_in_different_games_not_deduped():
    rows = [{"game": "G1", "selection": "Over 8.5"}, {"game": "G2", "selection": "Over 8.5"}]
    pa = attach_position_accounting(_card(rows, []))["position_accounting"]
    assert pa["legs"] == 2 and pa["positions"] == 2


def test_audit_bad_result_refuses_accounting_without_crashing_card():
    card = attach_position_accounting(_card([{"game": "G1", "selection": "x", "result": "maybe"}], []))
    pa = card["position_accounting"]
    assert pa["status"].startswith("ACCOUNTING_REFUSED")
    assert pa["positions"] is None
    assert card["summary"]["surfaced_positions"] is None
