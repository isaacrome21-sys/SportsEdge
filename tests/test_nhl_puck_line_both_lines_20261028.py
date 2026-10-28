"""NHL puck line, explicit both-lines form — regression tests from REAL bodies.

The lines lane posts NHL puck lines as (away line, away price, home line,
home price)::

    PL -1.5 +164 +1.5 -198

The shared parser's SPREAD shape originally accepted only the 3-numeric form
(one line + two prices), so every real NHL body the lane ever posted was
rejected (NHL_INTAKE_UNRECOGNIZED) and no posted NHL game could be priced.
The fixtures below are the verbatim bodies of the GitHub issues named in each
test (fetched 2026-10-28); they are evidence, not reconstructions.

Pair order is positional — (AWAY, HOME), the same side order as every other
market — NOT favourite-first. Issue #2714 is the proof case: the home team is
the favourite there, and the first pair still belongs to the away team.
"""
from __future__ import annotations

import pytest

from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines
from sportsedge.pipeline.intake import parse_issue

ISSUE_2716_BODY = 'Toronto Maple Leafs @ Calgary Flames\nCaptured: 2026-10-25T11:42:40-05:00\n<!-- DK event: 34876476; 60 Min Line: TOR +115 / Draw +320 / CGY +160; First to 5 Shots: TOR -115 / CGY -115; Overtime Yes +290 (other side locked, no price); ML/Total combos: TOR Over 6.5 +225, TOR Under 6.5 +235, CGY Over 6.5 +265, CGY Under 6.5 +295; PL/Total combos: TOR -1.5 Over 6.5 +425, TOR -1.5 Under 6.5 +425, CGY +1.5 Over 6.5 +160, CGY +1.5 Under 6.5 +180; Period Goals Odd/Even: 1P Odd -110 / Even -125, 2P Odd -120 / Even -115, 3P Odd -115 / Even -115; Team to Win from Behind: TOR +250 / CGY +280; Goal in First Five 0.5: Over +160 / Under -205; Goal in First Five 1.5: Over +950 / Under -2500; Power Play Goals CGY 1+ -120 2+ +400 3+ +1700; Power Play Goals TOR 1+ -145 2+ +360 3+ +1400; Shorthanded Goals CGY 1+ +850 2+ +8000; Shorthanded Goals TOR 1+ +800 2+ +7000; Shutout win: TOR +1000, CGY +1200; no team totals tab and no individual player props shown on the event page -->\nPL -1.5 +164 +1.5 -198\nTotal 6.5 -115 -105\nML -142 +120\n'


ISSUE_2624_BODY = 'Florida Panthers @ Chicago Blackhawks\nCaptured: 2026-10-25T11:41:54-05:00\n<!-- DK event: 34876468 -->\nPL -1.5 +136 +1.5 -162\nTotal 6.5 +105 -125\nML -185 +154\n'


ISSUE_2609_BODY = 'Minnesota Wild @ Seattle Kraken\nCaptured: 2026-10-24T20:36:00-05:00\n<!-- DK event: 34876467 -->\nPL -1.5 +145 +1.5 -175\nTotal 6.5 +110 -130\nML -185 +154\n'


ISSUE_2714_BODY = 'Los Angeles Kings @ New York Rangers\nCaptured: 2026-10-25T11:16:38-05:00\n<!-- DK event: 34876474; 60 Min Line: LA Kings +165 / Draw +300 / NY Rangers +120; First to 5 Shots: LA Kings -130 / NY Rangers +100; 1P Goals Odd/Even: Odd -110 / Even -125; 2P Goals Odd/Even: Odd -115 / Even -120; 3P Goals Odd/Even: Odd -115 / Even -120; Goal in First Five 0.5: Over +185 / Under -235; Goal in First Five 1.5: Over +1100 / Under -3500; ML/Total combos: LA Kings Over 5.5 +260, LA Kings Under 5.5 +300, NY Rangers Over 5.5 +205, NY Rangers Under 5.5 +255; PL/Total combos: LA Kings +1.5 Over 5.5 +170, LA Kings +1.5 Under 5.5 +165, NY Rangers -1.5 Over 5.5 +340, NY Rangers -1.5 Under 5.5 +550; Team to Win from Behind: LA Kings +300 / NY Rangers +270; one-sided: Overtime Yes +275; Power Play Goals LA Kings 1+ -105 2+ +500 3+ +2000; Power Play Goals NY Rangers 1+ -160 2+ +310 3+ +1100; Shorthanded Goals LA Kings 1+ +1000; Shorthanded Goals NY Rangers 1+ +800 2+ +7500; Shutout win: NY Rangers +850, LA Kings +1000; no team totals shown; no 1P PL/ML/Total shown -->\nPL +1.5 -230 -1.5 +190\nTotal 5.5 -125 +105\nML +114 -135\n'


def _pl(ticket):
    return next(m for m in ticket.markets if m.market == "PUCK_LINE")


def test_real_body_2716_toronto_at_calgary_parses():
    ticket = parse_nhl_lines(ISSUE_2716_BODY)[0]
    assert (ticket.away, ticket.home) == ("Toronto Maple Leafs", "Calgary Flames")
    assert ticket.captured_at == "2026-10-25T11:42:40-05:00"
    pl = _pl(ticket)
    # Toronto is the ML favourite (-142); its puck line is -1.5 at +164.
    assert (pl.line, pl.away_or_over_price, pl.home_or_under_price) == (-1.5, 164, -198)
    ml = next(m for m in ticket.markets if m.market == "MONEYLINE")
    assert (ml.away_or_over_price, ml.home_or_under_price) == (-142, 120)
    total = next(m for m in ticket.markets if m.market == "TOTAL")
    assert (total.line, total.away_or_over_price, total.home_or_under_price) == (6.5, -115, -105)


def test_real_body_2624_florida_at_chicago_parses():
    ticket = parse_nhl_lines(ISSUE_2624_BODY)[0]
    assert (ticket.away, ticket.home) == ("Florida Panthers", "Chicago Blackhawks")
    pl = _pl(ticket)
    assert (pl.line, pl.away_or_over_price, pl.home_or_under_price) == (-1.5, 136, -162)


def test_real_body_2609_minnesota_at_seattle_parses():
    ticket = parse_nhl_lines(ISSUE_2609_BODY)[0]
    assert (ticket.away, ticket.home) == ("Minnesota Wild", "Seattle Kraken")
    pl = _pl(ticket)
    assert (pl.line, pl.away_or_over_price, pl.home_or_under_price) == (-1.5, 145, -175)


def test_real_body_2714_home_favourite_keeps_away_first_pairs():
    # NY Rangers (home) are the ML favourite (-135), yet the first PL pair is
    # still the AWAY team's: Los Angeles holds +1.5 at -230. A favourite-first
    # reading would silently put -1.5 on Los Angeles; this fixture locks the
    # positional (away, home) semantics.
    ticket = parse_nhl_lines(ISSUE_2714_BODY)[0]
    assert (ticket.away, ticket.home) == ("Los Angeles Kings", "New York Rangers")
    pl = _pl(ticket)
    assert (pl.line, pl.away_or_over_price, pl.home_or_under_price) == (1.5, -230, 190)
    ml = next(m for m in ticket.markets if m.market == "MONEYLINE")
    assert (ml.away_or_over_price, ml.home_or_under_price) == (114, -135)


def test_shared_parser_both_lines_shape_and_sides():
    board = parse_issue(ISSUE_2624_BODY, "NHL")
    pl = next(m for m in board.games[0].markets if m.family == "spread")
    assert (pl.market, pl.line, pl.side_a, pl.price_a, pl.side_b, pl.price_b) == (
        "PUCK_LINE", -1.5, "AWAY", 136, "HOME", -162)


def test_legacy_three_numeric_form_still_parses():
    ticket = parse_nhl_lines("Rangers @ Bruins\nML +124 -148\nPL +1.5 -180 +150\nTotal 5.5 -110 -110")[0]
    pl = _pl(ticket)
    assert (pl.line, pl.away_or_over_price, pl.home_or_under_price) == (1.5, -180, 150)


_HEADER = "Rangers @ Bruins\nCaptured: 2026-10-25T11:58:30-05:00\nML +124 -148\n{row}\nTotal 5.5 -110 -110"


@pytest.mark.parametrize("row", [
    "PL -1.5 +164 +2.5 -198",   # lines are not mirrors
    "PL -1.5 +164 -1.5 -198",   # both pairs carry the favourite's line
    "PL +2.5 -198 -1.5 +164",   # mirror magnitudes disagree the other way
])
def test_non_mirrored_pairs_fail_closed(row):
    with pytest.raises(NhlLinesIntakeError, match="SPREAD_LINES_NOT_MIRRORED"):
        parse_nhl_lines(_HEADER.format(row=row))


@pytest.mark.parametrize("row", [
    "PL -1.5 +1.5 -162",            # missing a price: a line sits in a price slot
    "PL -1.5 +164 +1.5 -198 +200",  # five numerics
    "PL -1.5 +50 +1.5 -198",        # implausible American price
    "PL -1.5 +164",                 # one side only
])
def test_malformed_both_lines_rows_fail_closed(row):
    with pytest.raises(NhlLinesIntakeError, match="NHL_INTAKE_"):
        parse_nhl_lines(_HEADER.format(row=row))


def test_team_prefixed_pl_row_is_refused_not_reassigned():
    # A PL row carrying a team subject (the wrong team's side written into the
    # row) must fail closed, never be silently attached to the current game.
    body = _HEADER.format(row="Bruins PL -1.5 +164 +1.5 -198")
    with pytest.raises(NhlLinesIntakeError, match="NHL_INTAKE_"):
        parse_nhl_lines(body)
