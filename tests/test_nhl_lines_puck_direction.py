import pytest

from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines


def test_standard_away_plus_1_5_row_is_admitted():
    games = parse_nhl_lines("Rangers @ Bruins\nPL +1.5 -180 +150\n")
    row = games[0].markets[0]
    assert row.market == "PUCK_LINE"
    assert row.line == 1.5
    assert row.away_or_over_price == -180
    assert row.home_or_under_price == 150


def test_away_minus_1_5_row_fails_closed_instead_of_reversing_probability():
    with pytest.raises(
        NhlLinesIntakeError,
        match=r"NHL_INTAKE_PUCK_LINE_DIRECTION_UNSUPPORTED:-1.5",
    ):
        parse_nhl_lines("Rangers @ Bruins\nPL -1.5 +150 -180\n")


def test_nonstandard_puck_line_fails_closed_until_side_specific_binding_exists():
    with pytest.raises(
        NhlLinesIntakeError,
        match=r"NHL_INTAKE_PUCK_LINE_DIRECTION_UNSUPPORTED:\+2.5",
    ):
        parse_nhl_lines("Rangers @ Bruins\nPL +2.5 -240 +195\n")


def test_invalid_puck_line_token_has_explicit_error():
    with pytest.raises(
        NhlLinesIntakeError,
        match=r"NHL_INTAKE_PUCK_LINE_INVALID:favorite",
    ):
        parse_nhl_lines("Rangers @ Bruins\nPL favorite -180 +150\n")
