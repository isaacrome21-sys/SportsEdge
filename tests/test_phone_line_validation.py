"""Invalid phone quotes must fail before pricing or serialization."""
from __future__ import annotations

import sys
from typing import get_type_hints

import pytest

from scripts import intake_nfl_lines_issue, intake_nhl_lines_issue, run_nba_lines_issue
from sportsedge.nfl_lines_intake import NflLinesIntakeError, parse_nfl_lines
from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines
from sportsedge.ratings.elo import EloTracker
from sportsedge.sports.nba.lines_card import NBALinesError, parse_lines


PARSERS = [
    pytest.param(parse_lines, NBALinesError, "Celtics @ Knicks", id="nba"),
    pytest.param(parse_nfl_lines, NflLinesIntakeError, "Chiefs @ Ravens", id="nfl"),
    pytest.param(parse_nhl_lines, NhlLinesIntakeError, "Rangers @ Bruins", id="nhl"),
]


@pytest.mark.parametrize("parse,error,header", PARSERS)
@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "1e309"])
@pytest.mark.parametrize("market", ["Spread", "Total"])
def test_nonfinite_lines_are_intake_errors(parse, error, header, value, market):
    # NHL names its spread market PL.
    if parse is parse_nhl_lines and market == "Spread":
        market = "PL"
    with pytest.raises(error, match="LINE_INVALID"):
        parse(f"{header}\n{market} {value} -110 -110")


@pytest.mark.parametrize("parse,error,header", PARSERS)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e309", "-110.9", "100.1"])
def test_prices_are_never_rounded_or_nonfinite(parse, error, header, value):
    with pytest.raises(error, match="ODDS_INVALID"):
        parse(f"{header}\nML {value} -110")


@pytest.mark.parametrize("parse,error,header", PARSERS)
def test_integral_decimal_prices_preserve_the_existing_contract(parse, error, header):
    market = parse(f"{header}\nML -110.0 +120.0")[0].markets[0]
    if parse is parse_lines:
        assert (market.p1, market.p2) == (-110, 120)
    else:
        assert (market.away_or_over_price, market.home_or_under_price) == (-110, 120)


@pytest.mark.parametrize("parse,error,header", PARSERS)
def test_game_header_without_markets_is_refused(parse, error, header):
    with pytest.raises(error, match="GAME_WITHOUT_MARKETS"):
        parse(header)


@pytest.mark.parametrize("parse,error,header", [
    (parse_lines, NBALinesError, "Knicks @ New York Knicks"),
    (parse_nfl_lines, NflLinesIntakeError, "Chiefs @ Kansas City Chiefs"),
    (parse_nhl_lines, NhlLinesIntakeError, "Bruins @ Bruins"),
])
def test_identical_game_participants_are_refused(parse, error, header):
    with pytest.raises(error, match="TEAMS_IDENTICAL"):
        parse(f"{header}\nML +120 -140")


@pytest.mark.parametrize("module,parse,error,header", [
    (run_nba_lines_issue, parse_lines, NBALinesError, "Celtics @ Knicks"),
    (intake_nfl_lines_issue, parse_nfl_lines, NflLinesIntakeError, "Chiefs @ Ravens"),
    (intake_nhl_lines_issue, parse_nhl_lines, NhlLinesIntakeError, "Rangers @ Bruins"),
])
def test_fenced_issue_ignores_source_notes_but_checks_its_market(module, parse, error, header):
    def read(body):
        return parse(body if module is run_nba_lines_issue else module._body_lines(body))

    body = (f"### Lines\n```text\n{header}\nML +120 -140\n```\n"
            "Source: DraftKings, observed 2026-10-20 7:37 PM CT.\n"
            "### Notes\nHistorical record only.\n")
    assert len(read(body)[0].markets) == 1
    with pytest.raises(error):
        read(body.replace("ML +120 -140", "ML +120"))


@pytest.mark.parametrize("module,header,prefix", [
    (run_nba_lines_issue, "Celtics @ Knicks", "NBA"),
    (intake_nfl_lines_issue, "Chiefs @ Ravens", "NFL"),
    (intake_nhl_lines_issue, "Rangers @ Bruins", "NHL"),
])
def test_unclosed_fence_is_reported_by_cli(module, header, prefix, tmp_path, monkeypatch):
    body = tmp_path / "body.txt"
    body.write_text(f"### Lines\n```\n{header}\nML +120 -140\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        module.__file__, "--body-file", str(body),
        "--observed-at", "2026-10-21T00:40:00Z", "--issue", "123",
    ])
    if module is run_nba_lines_issue:
        def no_fetch(*args, **kwargs):
            pytest.fail("Malformed intake must not fetch results")
        monkeypatch.setattr(module, "fetch_results", no_fetch)
    assert module.main() == 2
    assert f"{prefix}_INTAKE_UNCLOSED_FENCE" in (tmp_path / "intake_error.txt").read_text()
    assert not (tmp_path / "manual_inputs").exists()


def test_elo_deserialization_annotations_can_be_resolved():
    assert get_type_hints(EloTracker.from_dict)["data"]
