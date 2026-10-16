"""Re-audit (67753d3c): the MLB full board must not display Lane A
probability/EV/fair odds for retired-lane diagnostics (t207u)."""
from test_mlb_phone_full_board import NOW, run_full, sample


def _items(board):
    out = []
    def walk(x):
        if isinstance(x, dict):
            out.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(board)
    return out


def test_full_board_suppresses_lane_a_probability_ev_fair():
    result = run_full({"lines": [sample()]}, now=NOW, auto_context=False)
    assert result["evaluated_rows"][0]["status"] == "RESEARCH_DIAGNOSTIC_LANE_A_RETIRED"
    board = result["mlb_full_board"]
    for item in _items(board):
        for key in ("model_p", "estimate_p", "ev", "ev_per_dollar",
                    "estimated_ev", "fair_odds", "fair_american", "probability"):
            assert item.get(key) is None, (key, item)
    assert board["input_coverage"]["priced_research_market_count"] == 0
    assert board["input_coverage"]["lane_a_diagnostic_market_count"] == 1
