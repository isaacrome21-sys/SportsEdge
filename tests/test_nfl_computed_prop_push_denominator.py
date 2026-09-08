from sportsedge.sports.nfl.computed_prop_trends import GameSettlement, _settle, _window


def _games(values, *, line: float):
    return [
        GameSettlement(
            game_id=f"g{index}",
            kickoff_ts=f"2025-09-{index:02d}T17:00:00+00:00",
            season=2025,
            week=index,
            team_id="SF",
            opponent_team_id="SEA",
            value=float(value),
            outcome=_settle(float(value), line=line, side="OVER"),
        )
        for index, value in enumerate(values, start=1)
    ]


def test_same_window_half_line_vs_integer_line_has_different_denominator():
    """A result exactly on an integer prop line pushes; it is never a miss.

    The same [4, 5, 3] reception history is 2-1 over 3.5 (three decisions),
    but 1-1-1 over 4.0 (two decisions plus one push).  Hit rate therefore uses
    wins/(wins+losses), not wins/attempts, when a push exists.
    """

    half_line = _window("L5", _games([4, 5, 3], line=3.5))
    integer_line = _window("L5", _games([4, 5, 3], line=4.0))

    assert (
        half_line.wins,
        half_line.losses,
        half_line.pushes,
        half_line.attempts,
        half_line.decisions,
    ) == (2, 1, 0, 3, 3)
    assert half_line.hit_rate_pct == 100.0 * 2 / 3

    assert (
        integer_line.wins,
        integer_line.losses,
        integer_line.pushes,
        integer_line.attempts,
        integer_line.decisions,
    ) == (1, 1, 1, 3, 2)
    assert integer_line.hit_rate_pct == 50.0
    assert integer_line.decisions == integer_line.attempts - integer_line.pushes
