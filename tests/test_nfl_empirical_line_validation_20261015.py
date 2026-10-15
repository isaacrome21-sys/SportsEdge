import pytest

from sportsedge.nfl_player_empirical import NFLEmpiricalError, price_nfl_player_market


@pytest.mark.parametrize("line,reason", [
    (None, "LINE_INVALID"),
    ("not-a-number", "LINE_INVALID"),
    (float("inf"), "LINE_NONFINITE"),
    (float("nan"), "LINE_NONFINITE"),
])
def test_malformed_line_refuses_by_name(line, reason):
    with pytest.raises(NFLEmpiricalError, match=reason):
        price_nfl_player_market(market="PLAYER_RECEIVING_YARDS", side="OVER",
                                line=line, game_history=[])


def test_valid_line_still_prices_empirical_history():
    history = [{"receiving_yards": x} for x in [20, 30, 40, 50, 60]]
    outcome = price_nfl_player_market(market="PLAYER_RECEIVING_YARDS", side="OVER",
                                      line=35.5, game_history=history)
    assert outcome["model_p"] == pytest.approx(0.6)
    assert outcome["push_p"] == 0.0
