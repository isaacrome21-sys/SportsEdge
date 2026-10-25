"""Paired DK spread/puck-line prices preserve both explicit handicaps."""

from __future__ import annotations

import pytest

from sportsedge.nhl_lines_intake import parse_nhl_lines
from sportsedge.pipeline.intake import SharedIntakeError, parse_issue


CAPTURED = "Captured: 2026-10-25T11:42:40-05:00"


@pytest.mark.parametrize("sport,market_line,expected_market,away_line,a,b", [
    ("NHL", "PL -1.5 +164 +1.5 -198", "PUCK_LINE", -1.5, 164, -198),
    ("NHL", "PL +1.5 -166 -1.5 +140", "PUCK_LINE", 1.5, -166, 140),
    ("NFL", "Spread +3 -110 -3 -110", "spread", 3.0, -110, -110),
    ("CFB", "Spread -6.5 -112 +6.5 -108", "SPREAD", -6.5, -112, -108),
    ("MLB", "RL +1.5 -120 -1.5 +100", "RUN_LINE", 1.5, -120, 100),
    ("NBA", "Spread -4.5 -108 +4.5 -112", "SPREAD", -4.5, -108, -112),
])
def test_four_field_spread_pairs_keep_true_prices(
    sport, market_line, expected_market, away_line, a, b,
) -> None:
    body = "Away @ Home\n" + CAPTURED + "\n" + market_line
    board = parse_issue(body, sport, resolve_teams=False)
    assert board.warnings == []
    assert len(board.games[0].markets) == 1
    market = board.games[0].markets[0]
    assert market.market == expected_market
    assert market.family == "spread"
    assert (market.line, market.price_a, market.price_b) == (away_line, a, b)
    assert (market.side_a, market.side_b) == ("AWAY", "HOME")


def test_real_nhl_board_keeps_all_three_markets() -> None:
    body = ("Toronto Maple Leafs @ Calgary Flames\n" + CAPTURED + "\n"
            "<!-- Other DK offers require separate market contracts -->\n"
            "PL -1.5 +164 +1.5 -198\nTotal 6.5 -115 -105\nML -142 +120")
    board = parse_issue(body, "NHL")
    assert [m.market for m in board.games[0].markets] == [
        "PUCK_LINE", "TOTAL", "MONEYLINE"
    ]
    assert board.games[0].captured_at == "2026-10-25T11:42:40-05:00"
    assert board.warnings == []

    # The production NHL phone intake uses strict_unknown=True. This exact
    # four-number PL previously aborted the *entire* game intake.
    tickets = parse_nhl_lines(body)
    assert len(tickets) == 1
    assert [m.market for m in tickets[0].markets] == [
        "PUCK_LINE", "TOTAL", "MONEYLINE"
    ]
    assert tickets[0].markets[0].away_or_over_price == 164
    assert tickets[0].markets[0].home_or_under_price == -198


@pytest.mark.parametrize("bad_line,expected", [
    ("PL -1.5 +164 +2.5 -198", "SPREAD_PAIR_MISMATCH"),
    ("PL -1.5 +164 -1.5 -198", "SPREAD_PAIR_MISMATCH"),
    ("PL -1.5 +164 +1.5", "ODDS_INVALID"),
    ("PL -1.5 +164", "ONE_SIDED_OR_MALFORMED"),
    ("Total 6.5 -110 7.5 -110", "ONE_SIDED_OR_MALFORMED"),
    ("PL -1.5 +164 +1.5 -198 +200", "ONE_SIDED_OR_MALFORMED"),
])
def test_malformed_pairs_refuse_without_guessing(bad_line, expected) -> None:
    body = "Away @ Home\n" + CAPTURED + "\n" + bad_line
    with pytest.raises(SharedIntakeError, match=expected):
        parse_issue(body, "NHL", resolve_teams=False)
