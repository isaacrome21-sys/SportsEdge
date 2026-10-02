from __future__ import annotations

from sportsedge.cfb_lines_intake import parse_cfb_lines
from sportsedge.nba_lines_intake import parse_nba_lines


def test_nba_parses_two_way_lines() -> None:
    games = parse_nba_lines("Celtics @ Knicks\nML +110 -130\nSpread +3.5 -110 -110\nTotal 224.5 -108 -112\n")
    assert len(games) == 1
    assert [m.market for m in games[0].markets] == ["MONEYLINE", "SPREAD", "TOTAL"]


def test_cfb_parses_two_way_lines() -> None:
    games = parse_cfb_lines("Ohio State @ Penn State\nML +150 -180\nSpread +6.5 -110 -110\nTotal 48.5 -108 -112\n")
    assert len(games) == 1
    assert games[0].markets[1].line == 6.5
