"""Several players packed on one prop line must fail closed, never mis-attribute."""
import pytest

from sportsedge.nfl_lines_intake import NflLinesIntakeError, parse_nfl_lines

BASE = (
    "Pittsburgh Steelers @ New Orleans Saints\n"
    "Captured: 2026-10-25T03:53:00-05:00\n"
    "Spread -3 -112 -108\n"
    "Total 43.5 -105 -115\n"
    "ML -162 +136\n"
)


def test_semicolon_packed_players_refused():
    body = BASE + "Pass Yards O/U: Aaron Rodgers 225.5 -113/-111; Tyler Shough 216.5 -111/-113\n"
    with pytest.raises(NflLinesIntakeError, match="SUBJECT_MALFORMED"):
        parse_nfl_lines(body)


def test_numeric_token_in_subject_refused():
    body = BASE + 'Prop "Aaron Rodgers 225.5" PassYards 230.5 -113 -111\n'
    with pytest.raises(NflLinesIntakeError, match="SUBJECT_MALFORMED"):
        parse_nfl_lines(body)


def test_one_player_per_line_still_parses_exact_quotes():
    body = (BASE
            + 'Prop "Aaron Rodgers" PassYards 225.5 -113 -111\n'
            + 'Prop "Tyler Shough" PassYards 216.5 -111 -113\n')
    props = [m for m in parse_nfl_lines(body)[0].markets if m.market == "passing_yards"]
    assert [(m.player, m.line, m.away_or_over_price, m.home_or_under_price) for m in props] == [
        ("Aaron Rodgers", 225.5, -113, -111),
        ("Tyler Shough", 216.5, -111, -113),
    ]


def test_game_lines_unchanged():
    markets = parse_nfl_lines(BASE)[0].markets
    assert [(m.market, m.line, m.away_or_over_price, m.home_or_under_price) for m in markets] == [
        ("spread", -3.0, -112, -108),
        ("total", 43.5, -105, -115),
        ("moneyline", None, -162, 136),
    ]
