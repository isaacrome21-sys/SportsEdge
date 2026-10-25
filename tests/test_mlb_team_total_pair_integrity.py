"""Every recognized MLB team-total piece must carry a full O/U pair."""

from __future__ import annotations

import pytest

from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines


@pytest.mark.parametrize("incomplete", [
    "Team Totals: MIL 4.5 -110 -110; TB 3.5 -105",
    "Team Totals: MIL 4.5 -110; TB 3.5 -110 -110",
    "Team Totals: MIL 4.5 -110 -110; TB 3.5",
    "F5 Team Totals: MIL 2.5 -110 -110; TB 1.5 -105",
    "Team Totals: MIL 4.5 -110 -110; TB 3.5 -99 -110",
    "Team Totals: MIL 4.5 -110 -110;",
])
def test_partial_team_total_piece_blocks_entire_board_even_with_valid_ml(incomplete):
    body = "MIL Brewers @ TB Rays\nML -105 -115\n" + incomplete
    with pytest.raises(LinesIntakeError, match="BLOCKED_PRICING_METHOD"):
        parse_lines(body)


@pytest.mark.parametrize("prefix,expected_market", [
    ("Team Totals", "TEAM_TOTAL"),
    ("F5 Team Totals", "FIRST_FIVE_TEAM_TOTAL"),
])
def test_complete_two_team_totals_preserve_both_exact_pairs(prefix, expected_market):
    rows = parse_lines(
        "MIL Brewers @ TB Rays\nML -105 -115\n"
        + f"{prefix}: MIL 4.5 -110 -110; TB 3.5 -105 -115"
    )
    assert len(rows) == 3
    assert [row.market_type for row in rows[1:]] == [expected_market, expected_market]
    assert [(row.team, row.price, row.paired_price) for row in rows[1:]] == [
        ("MIL", -110, -110), ("TB", -105, -115),
    ]
