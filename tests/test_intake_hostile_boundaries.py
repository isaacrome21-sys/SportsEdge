"""Hostile-boundary regression tests for the lines intakes.

Reproductions from the Oct 27, 2026 adversarial pass: numeric tokens that
Decimal()/float() silently coerce (scientific notation, underscore
separators, non-ASCII digits), duplicate competing market lines in one
snapshot, a note line containing '@' opening a phantom game, and MLB
malformed prices degrading to a warning-only silent drop. Every case must
end in the parser's named refusal, never a coerced value.
"""
import pytest

from sportsedge.mlb_lines_intake import LinesIntakeError, parse_lines
from sportsedge.nfl_lines_intake import NflLinesIntakeError, parse_nfl_lines
from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines
from sportsedge.pipeline.intake import SharedIntakeError, parse_issue

CAP = "Captured: 2026-10-25T11:58:30-05:00"
NFL_HDR = f"Chiefs @ Ravens\n{CAP}\n"
NHL_HDR = f"Bruins @ Rangers\n{CAP}\n"
MLB_HDR = "TB Rays @ MIL Brewers\n"


# --- numeric coercion: shared parser -------------------------------------

@pytest.mark.parametrize("token", ["1e2", "1E2", "1_10", "１１０", "١١٠", "+1e2"])
def test_odds_coercion_refused(token):
    with pytest.raises(NflLinesIntakeError, match="ODDS_INVALID"):
        parse_nfl_lines(f"{NFL_HDR}ML {token} -145")


@pytest.mark.parametrize("token", ["4_7.5", "1e2", "４７.５", "47_5"])
def test_line_coercion_refused(token):
    with pytest.raises(NflLinesIntakeError, match="LINE_INVALID"):
        parse_nfl_lines(f"{NFL_HDR}Total {token} -108 -112")


def test_nhl_odds_scientific_refused():
    with pytest.raises(NhlLinesIntakeError, match="ODDS_INVALID"):
        parse_nhl_lines(f"{NHL_HDR}ML 1e2 -145")


def test_integral_decimal_price_contract_preserved():
    market = parse_nfl_lines(f"{NFL_HDR}ML -110.0 +120.0")[0].markets[0]
    assert (market.away_or_over_price, market.home_or_under_price) == (-110, 120)


def test_plain_transcriptions_still_parse():
    games = parse_nfl_lines(
        f"{NFL_HDR}ML +125 -145\nSpread +3.5 -110 -110\nTotal 47.5 -108 -112\n"
        'Prop "Lamar Jackson" Pass Yards 245.5 -110 -110'
    )
    assert [m.market for m in games[0].markets] == [
        "moneyline", "spread", "total", "passing_yards"]


# --- duplicate competing markets ------------------------------------------

def test_duplicate_moneyline_refused():
    with pytest.raises(NflLinesIntakeError, match="DUPLICATE_MARKET"):
        parse_nfl_lines(f"{NFL_HDR}ML +125 -145\nML +130 -150")


def test_duplicate_identical_line_refused():
    with pytest.raises(NflLinesIntakeError, match="DUPLICATE_MARKET"):
        parse_nfl_lines(f"{NFL_HDR}ML +125 -145\nML +125 -145")


def test_duplicate_total_refused():
    with pytest.raises(NflLinesIntakeError, match="DUPLICATE_MARKET"):
        parse_nfl_lines(f"{NFL_HDR}Total 47.5 -108 -112\nTotal 48.5 -110 -110")


def test_duplicate_prop_refused():
    body = (f"{NFL_HDR}"
            'Prop "Lamar Jackson" Pass Yards 245.5 -110 -110\n'
            'Prop "Lamar Jackson" Pass Yards 255.5 -110 -110')
    with pytest.raises(NflLinesIntakeError, match="DUPLICATE_MARKET"):
        parse_nfl_lines(body)


def test_team_totals_for_both_teams_are_not_duplicates():
    games = parse_nfl_lines(
        f"{NFL_HDR}TeamTotal Chiefs 24.5 -110 -110\nTeamTotal Ravens 23.5 -110 -110")
    assert len(games[0].markets) == 2


def test_same_market_in_two_games_is_not_a_duplicate():
    body = (f"{NFL_HDR}ML +125 -145\n"
            f"Eagles @ Cowboys\n{CAP}\nML +130 -150")
    games = parse_nfl_lines(body)
    assert len(games) == 2


def test_yrfi_and_nrfi_lines_are_the_same_market():
    body = f"TB Rays @ MIL Brewers\n{CAP}\nYRFI +105 -135\nNRFI -135 +105"
    with pytest.raises(SharedIntakeError, match="DUPLICATE_MARKET"):
        parse_issue(body, "MLB")


# --- phantom game from a note line -----------------------------------------

def test_note_line_with_at_and_number_opens_no_phantom_game():
    body = ("Alabama @ Georgia\n" + CAP + "\nML +125 -145\n"
            "Mahomes @ 50 percent health\nSpread +3.5 -110 -110")
    board = parse_issue(body, "CFB")
    assert len(board.games) == 1
    assert [m.market for m in board.games[0].markets] == ["MONEYLINE", "SPREAD"]


def test_trailing_game_number_header_still_parses():
    board = parse_issue(f"Alabama @ Georgia Game 7\n{CAP}\nML +125 -145", "CFB")
    assert len(board.games) == 1


def test_numeric_team_name_header_still_parses():
    board = parse_issue(f"76ers @ Celtics\n{CAP}\nML +125 -145", "CFB")
    assert board.games[0].away == "76ers"


# --- MLB intake -------------------------------------------------------------

@pytest.mark.parametrize("line", ["ML １２５ -145", "ML ١٢٥ -145", "Total ８.5 -110 -110"])
def test_mlb_non_ascii_digits_refused(line):
    with pytest.raises(LinesIntakeError, match="BAD_PRICE"):
        parse_lines(f"{MLB_HDR}{line}")


def test_mlb_duplicate_moneyline_refused():
    with pytest.raises(LinesIntakeError, match="DUPLICATE_MARKET"):
        parse_lines(f"{MLB_HDR}ML +125 -145\nML +130 -150")


def test_mlb_doubleheader_second_game_is_a_distinct_instance():
    rows = parse_lines(f"{MLB_HDR}ML +125 -145\n{MLB_HDR}ML +130 -150")
    assert len(rows) == 2


@pytest.mark.parametrize("line", ["ML +100000 -145", "ML -50 -145", "ML +125 -145 extra"])
def test_mlb_malformed_core_market_price_fails_closed(line):
    with pytest.raises(LinesIntakeError, match="BLOCKED_PRICING_METHOD"):
        parse_lines(f"{MLB_HDR}{line}")


def test_mlb_controls_still_parse():
    rows = parse_lines(
        f"{MLB_HDR}ML +125 -145\nTotal 8.5 -110 -110\nNRFI -135 / YRFI +105\n"
        "Team totals: TB Rays 3.5 -110 -110; MIL Brewers 4.5 -110 -110")
    assert {r.market_type for r in rows} == {
        "MONEYLINE", "GAME_TOTAL", "FIRST_INNING_TOTAL", "TEAM_TOTAL"}
