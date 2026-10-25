"""Truncated explicit run-line pairs must block production intake."""

import pytest

from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines


@pytest.mark.parametrize("bad", [
    "Alt RL -4.5 +620 / +4.5",
    "Alt RL -4.5 +620 / +4.5 +99",
    "RL -1.5 +170 / +1.5",
    "F5 RL -0.5 +135 / +0.5",
    "first five run line -0.5 +135 / +0.5",
])
def test_explicit_missing_counterpart_refuses_even_with_other_valid_market(bad):
    body = "MIL Brewers @ TB Rays\nML -105 -115\n" + bad
    with pytest.raises(LinesIntakeError, match="BLOCKED_PRICING_METHOD"):
        parse_lines(body)


def test_complete_explicit_pair_remains_admitted_with_exact_prices():
    rows = parse_lines(
        "MIL Brewers @ TB Rays\nML -105 -115\n"
        "Alt RL -4.5 +620 / +4.5 -1260"
    )
    assert len(rows) == 2
    assert (rows[1].market_type, rows[1].line, rows[1].price, rows[1].paired_price) == (
        "RUN_LINE", -4.5, 620, -1260,
    )
