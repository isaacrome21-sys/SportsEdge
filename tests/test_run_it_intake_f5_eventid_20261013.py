"""Tests for the F5 event-ID intake extension (Oct 13, 2026).

Background: the SOURCE extension (test_run_it_intake_shapes_extension)
got text-board F5 rows past the F5 quote-binding gate's first check
(F5_SOURCE_MISSING) by stamping the board capture's declared source as
`book`. Every F5 row then stopped at the binder's second check,
F5_EVENT_ID_MISSING (sportsedge/mlb_f5_quote_binding._parse_quote reads
`row["event_id"]` or `row["source_event_id"]`), because a text capture
carried no DraftKings event ID.

The event ID is a fact of the capture, in the same provenance class as
the SOURCE declaration: tonight's live capture read it off the event
page URL (…/event/cle-guardians-%40-tb-rays/34817298). This extension
adds the board header that carries it:

    EVENT_ID: <draftkings event id>

with the capture convention that its provenance is recorded on the
board itself as a NOTE line naming the event page URL it was read
from, e.g.:

    NOTE: EVENT_ID 34817298 read from the DraftKings event page
    https://sportsbook.draftkings.com/event/cle-guardians-%40-tb-rays/34817298

Contract proven here:
- A declared, well-formed EVENT_ID is stamped as `event_id` on the
  board's F5 rows ONLY (F5_MONEYLINE / F5_SPREAD / F5_TOTAL /
  F5_TEAM_TOTAL) -- the rows the binder's gate 2 reads. Game rows,
  full-game team totals and the first-inning pair are unchanged.
- An explicit board_event_id argument wins over the header, exactly
  as board_book does for the source.
- No EVENT_ID anywhere -> rows are byte-identical to the pre-extension
  shape (no `event_id` key) and the binder still refuses them with
  F5_EVENT_ID_MISSING.
- A present-but-malformed EVENT_ID (non-numeric, empty, whitespace,
  duplicated declaration) refuses the parse with
  INTAKE_EVENT_ID_UNPARSEABLE -- the intake's strictness for declared
  identity facts (the kickoff convention), never a silent guess.
- An EVENT_ID detached from a parsed fixture refuses: a board whose
  GAME header fails to parse raises the header/kickoff refusal as
  before; a board with no GAME header at all raises
  INTAKE_EVENT_ID_UNBOUND_NO_GAME_CONTEXT; a second GAME header under
  one declared EVENT_ID raises INTAKE_EVENT_ID_MULTIPLE_FIXTURES (one
  book event ID names exactly one fixture).
- Against the REAL binder: a declared-source + declared-event F5 row
  passes gate 2 and stops at the binder's NEXT check, verbatim
  F5_FIXTURE_BINDING_MISSING (the row carries no verified MLB gamePk;
  supplying fixture identity is a separate capture-format piece, not
  improvised here).
- F5 totals: the `F5_TOTAL:` line syntax already parses (base
  parser); its rows are F5 rows for stamping, and the binder
  normalizes them to F5_TOTALS, its verified-settlement consumer
  market.
"""
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTAKE_DIR = Path(os.environ.get("RUN_IT_INTAKE_DIR") or (ROOT / "artifacts"))
for _p in (str(ROOT), str(ROOT / "artifacts"), str(INTAKE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, INTAKE_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


browser = _load("run_it_browser")
automation = _load("run_it_automation")

CT = timezone(timedelta(hours=-5))
QUOTE_MLB = datetime(2026, 10, 13, 18, 24, 35, tzinfo=CT)
QUOTE_CFB = datetime(2026, 10, 13, 15, 20, 30, tzinfo=CT)
EVENT_ID = "34817298"
EVENT_URL = ("https://sportsbook.draftkings.com/event/"
             "cle-guardians-%40-tb-rays/34817298")

# Tonight's 6:30 PM board (Guardians @ Rays, ALCS Game 2), verbatim
# from the run record (run_it_20261013_mlb630/board_cle_tb.txt),
# minus its NOTE line; the F5-total section the page offered is
# carried as the F5_TOTAL line the parser already documents.
MLB_BOARD = """\
QUOTE_TIME: 2026-10-13T18:24:35-05:00
SOURCE: DraftKings
GAME: Cleveland Guardians @ Tampa Bay Rays | 2026-10-13 19:00 CT
SPREAD: Cleveland Guardians +1.5 (-189) | Tampa Bay Rays -1.5 (+155)
TOTAL: O 6.5 (-120) | U 6.5 (+100)
ML: Cleveland Guardians (+117) | Tampa Bay Rays (-131)
F5_ML: Cleveland Guardians (+100) | Tampa Bay Rays (-130)
F5_SPREAD: Cleveland Guardians -1.5 (+250) | Tampa Bay Rays +1.5 (-345)
F5_SPREAD: Cleveland Guardians -0.5 (+140) | Tampa Bay Rays +0.5 (-180)
F5_SPREAD: Cleveland Guardians +0.5 (-140) | Tampa Bay Rays -0.5 (+110)
F5_SPREAD: Cleveland Guardians +1.5 (-270) | Tampa Bay Rays -1.5 (+200)
F5_TOTAL: O 3.5 (-125) | U 3.5 (-105)
FIRST_INNING: O 0.5 (+105) | U 0.5 (-135)
FIRST_INNING: O 1.5 (+255) | U 1.5 (-340)
TEAM_PROP: Cleveland Guardians | TEAM_TOTAL | 2.5 | O (-154) | U (+120)
TEAM_PROP: Tampa Bay Rays | TEAM_TOTAL | 3.5 | O (-105) | U (-125)
TEAM_PROP: Cleveland Guardians | F5_TEAM_TOTAL | 1.5 | O (-110) | U (-120)
TEAM_PROP: Tampa Bay Rays | F5_TEAM_TOTAL | 1.5 | O (-130) | U (+100)
"""

MLB_BOARD_WITH_EVENT = (
    f"EVENT_ID: {EVENT_ID}\n"
    f"NOTE: EVENT_ID {EVENT_ID} read from the DraftKings event page "
    f"{EVENT_URL}\n" + MLB_BOARD)

# Tonight's Board 2 (Delaware @ Middle Tennessee), verbatim from the
# shapes battery.
CFB_BOARD_DEL = """\
QUOTE_TIME: 2026-10-13T15:20:30-05:00
GAME: Delaware @ Middle Tennessee | 2026-10-13 18:00 CT
SPREAD: Delaware -1.5 (-105) | Middle Tennessee +1.5 (-115)
TOTAL: O 48.5 (-108) | U 48.5 (-112)
ML: Delaware (-115) | Middle Tennessee (-105)
TEAM_PROP: Delaware | TEAM_TOTAL | 24.5 | O (+100) | U (-130)
TEAM_PROP: Middle Tennessee | TEAM_TOTAL | 24.5 | O (+105) | U (-135)
TEAM_PROP: Game | TOTAL_1H | 23.5 | O (-118) | U (-102)
TEAM_PROP: Delaware | SPREAD_1H | -0.5 | +102
TEAM_PROP: Middle Tennessee | SPREAD_1H | +0.5 | -122
TEAM_PROP: Delaware | ML_1H | -120
TEAM_PROP: Middle Tennessee | ML_1H | +100
"""

F5_MARKETS = ("F5_MONEYLINE", "F5_SPREAD", "F5_TOTAL", "F5_TEAM_TOTAL")


def _f5_rows(rows):
    return [r for r in rows if r["market"] in F5_MARKETS]


# ---------------------------------------------------------------------------
# Header reader: declared / absent / malformed.
# ---------------------------------------------------------------------------

def test_event_id_header_reader():
    assert browser.board_event_id_from_header(MLB_BOARD_WITH_EVENT) == EVENT_ID
    assert browser.board_event_id_from_header(MLB_BOARD) is None


@pytest.mark.parametrize("bad", [
    "34817A298",        # non-numeric
    "34817 298",        # embedded whitespace
    "34817298.0",       # not a bare integer ID
    "",                 # EVENT_ID: with no value
    "   ",              # EVENT_ID: whitespace only
])
def test_event_id_header_malformed_refuses(bad):
    board = f"EVENT_ID: {bad}\n" + MLB_BOARD
    with pytest.raises(ValueError) as exc:
        browser.board_event_id_from_header(board)
    assert str(exc.value).startswith("INTAKE_EVENT_ID_UNPARSEABLE")


def test_event_id_header_duplicated_refuses():
    board = f"EVENT_ID: {EVENT_ID}\nEVENT_ID: {EVENT_ID}\n" + MLB_BOARD
    with pytest.raises(ValueError) as exc:
        browser.board_event_id_from_header(board)
    assert str(exc.value).startswith("INTAKE_EVENT_ID_UNPARSEABLE")


# ---------------------------------------------------------------------------
# Stamping: F5 rows only; everything else unchanged.
# ---------------------------------------------------------------------------

def test_event_id_stamps_every_f5_row():
    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_WITH_EVENT, sport="MLB", now=QUOTE_MLB)
    f5 = _f5_rows(rows)
    # Tonight's board + its F5 total: 2 F5 ML + 8 F5 spread + 2 F5
    # total + 4 F5 team-total rows.
    assert len(f5) == 16
    assert {r["market"] for r in f5} == set(F5_MARKETS)
    assert all(r.get("event_id") == EVENT_ID for r in f5)
    # The SOURCE stamp is independent and still lands on every row.
    assert all(r.get("book") == "DraftKings" for r in rows)


def test_event_id_leaves_non_f5_rows_unchanged():
    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_WITH_EVENT, sport="MLB", now=QUOTE_MLB)
    non_f5 = [r for r in rows if r["market"] not in F5_MARKETS]
    # 6 game rows + 2 first-inning rungs x2 + 4 full-game team totals.
    assert len(non_f5) == 14
    assert all("event_id" not in r for r in non_f5)
    assert {r["market"] for r in non_f5} == {
        "SPREAD", "TOTAL", "MONEYLINE", "YRFI", "NRFI", "TEAM_TOTAL"}


def test_no_event_id_rows_are_byte_identical():
    with_event = automation.parse_extended_browser_lines(
        MLB_BOARD_WITH_EVENT, sport="MLB", now=QUOTE_MLB)
    without = automation.parse_extended_browser_lines(
        MLB_BOARD, sport="MLB", now=QUOTE_MLB)
    assert len(with_event) == len(without) == 30
    for stamped, plain in zip(with_event, without):
        assert "event_id" not in plain
        expected = dict(plain)
        if stamped["market"] in F5_MARKETS:
            expected["event_id"] = EVENT_ID
        assert stamped == expected


def test_explicit_board_event_id_argument_stamps_f5_rows():
    rows = browser.parse_browser_lines(
        MLB_BOARD, sport="MLB", now=QUOTE_MLB, board_event_id=EVENT_ID)
    f5 = _f5_rows(rows)
    assert f5 and all(r.get("event_id") == EVENT_ID for r in f5)


def test_explicit_board_event_id_wins_over_header():
    board = "EVENT_ID: 99999999\n" + MLB_BOARD
    rows = browser.parse_browser_lines(
        board, sport="MLB", now=QUOTE_MLB, board_event_id=EVENT_ID)
    assert all(r.get("event_id") == EVENT_ID for r in _f5_rows(rows))


def test_explicit_board_event_id_malformed_refuses():
    with pytest.raises(ValueError) as exc:
        browser.parse_browser_lines(
            MLB_BOARD, sport="MLB", now=QUOTE_MLB,
            board_event_id="not-an-id")
    assert str(exc.value).startswith("INTAKE_EVENT_ID_UNPARSEABLE")


def test_event_id_on_cfb_board_stamps_nothing():
    board = f"EVENT_ID: {EVENT_ID}\n" + CFB_BOARD_DEL
    rows = automation.parse_extended_browser_lines(
        board, sport="CFB", now=QUOTE_CFB)
    plain = automation.parse_extended_browser_lines(
        CFB_BOARD_DEL, sport="CFB", now=QUOTE_CFB)
    assert len(rows) == len(plain) == 16
    assert all("event_id" not in r for r in rows)
    assert rows == plain


# ---------------------------------------------------------------------------
# Fixture binding: an EVENT_ID detached from a parsed fixture refuses.
# ---------------------------------------------------------------------------

def test_event_id_with_unparseable_game_header_refuses():
    board = (f"EVENT_ID: {EVENT_ID}\n"
             "GAME: Cleveland Guardians @ Tampa Bay Rays | not-a-time\n"
             "F5_ML: Cleveland Guardians (+100) | Tampa Bay Rays (-130)\n")
    with pytest.raises(ValueError) as exc:
        automation.parse_extended_browser_lines(
            board, sport="MLB", now=QUOTE_MLB)
    assert str(exc.value).startswith("INTAKE_KICKOFF_UNPARSEABLE")


def test_event_id_f5_line_without_game_context_refuses():
    board = (f"EVENT_ID: {EVENT_ID}\n"
             "F5_ML: Cleveland Guardians (+100) | Tampa Bay Rays (-130)\n")
    with pytest.raises(ValueError) as exc:
        browser.parse_browser_lines(board, sport="MLB", now=QUOTE_MLB)
    assert str(exc.value).startswith(
        "INTAKE_PERIOD_LINE_UNBOUND_NO_GAME_CONTEXT")


def test_event_id_board_with_no_fixture_refuses():
    board = (f"EVENT_ID: {EVENT_ID}\n"
             "TOTAL: O 6.5 (-120) | U 6.5 (+100)\n")
    with pytest.raises(ValueError) as exc:
        browser.parse_browser_lines(board, sport="MLB", now=QUOTE_MLB)
    assert str(exc.value).startswith("INTAKE_EVENT_ID_UNBOUND_NO_GAME_CONTEXT")


def test_event_id_two_fixtures_one_id_refuses():
    board = MLB_BOARD_WITH_EVENT + (
        "\nGAME: New York Yankees @ Boston Red Sox | 2026-10-13 19:05 CT\n"
        "ML: New York Yankees (-110) | Boston Red Sox (-110)\n")
    with pytest.raises(ValueError) as exc:
        browser.parse_browser_lines(board, sport="MLB", now=QUOTE_MLB)
    assert str(exc.value).startswith("INTAKE_EVENT_ID_MULTIPLE_FIXTURES")


# ---------------------------------------------------------------------------
# Real binder: gate 2 passes; the NEXT gate is reported verbatim.
# ---------------------------------------------------------------------------

def test_binder_event_gate_passes_and_next_gate_stops_row():
    from sportsedge.mlb_f5_quote_binding import F5BindingError, _parse_quote

    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_WITH_EVENT, sport="MLB", now=QUOTE_MLB)
    for market in F5_MARKETS:
        row = next(r for r in rows if r["market"] == market)
        with pytest.raises(F5BindingError) as exc:
            _parse_quote(row, now=QUOTE_MLB)
        # Gate 1 (source) and gate 2 (event ID) both passed; the row
        # stops at the fixture-identity check that follows them.
        assert exc.value.code == "F5_FIXTURE_BINDING_MISSING"
        assert "gamePk" in exc.value.detail


def test_binder_event_gate_still_refuses_without_event_id():
    from sportsedge.mlb_f5_quote_binding import F5BindingError, _parse_quote

    rows = automation.parse_extended_browser_lines(
        MLB_BOARD, sport="MLB", now=QUOTE_MLB)
    for market in ("F5_MONEYLINE", "F5_TEAM_TOTAL"):
        row = next(r for r in rows if r["market"] == market)
        with pytest.raises(F5BindingError) as exc:
            _parse_quote(row, now=QUOTE_MLB)
        assert exc.value.code == "F5_EVENT_ID_MISSING"


def test_binder_source_gate_still_first_without_source():
    from sportsedge.mlb_f5_quote_binding import F5BindingError, _parse_quote

    board = MLB_BOARD_WITH_EVENT.replace("SOURCE: DraftKings\n", "")
    rows = automation.parse_extended_browser_lines(
        board, sport="MLB", now=QUOTE_MLB)
    row = next(r for r in rows if r["market"] == "F5_MONEYLINE")
    assert row.get("event_id") == EVENT_ID and "book" not in row
    with pytest.raises(F5BindingError) as exc:
        _parse_quote(row, now=QUOTE_MLB)
    assert exc.value.code == "F5_SOURCE_MISSING"


def test_bind_f5_quotes_reports_next_gate_per_row():
    from sportsedge.mlb_f5_quote_binding import bind_f5_quotes

    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_WITH_EVENT, sport="MLB", now=QUOTE_MLB)
    f5 = _f5_rows(rows)
    bound = bind_f5_quotes(f5, now=QUOTE_MLB, fixture_resolver=None)
    assert bound["pairs"] == []
    assert len(bound["row_results"]) == len(f5)
    assert all(r["status"] == "BLOCKED" for r in bound["row_results"])
    assert {r["reason_code"] for r in bound["row_results"]} == {
        "F5_FIXTURE_BINDING_MISSING"}


# ---------------------------------------------------------------------------
# F5 totals: syntax exists; consumer is the binder's F5_TOTALS market.
# ---------------------------------------------------------------------------

def test_f5_total_rows_carry_event_id_and_reach_binder_as_f5_totals():
    from sportsedge.mlb_f5_quote_binding import (
        F5BindingError, _parse_quote, normalize_f5_market)

    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_WITH_EVENT, sport="MLB", now=QUOTE_MLB)
    totals = [r for r in rows if r["market"] == "F5_TOTAL"]
    assert len(totals) == 2
    assert {r["side"] for r in totals} == {"OVER", "UNDER"}
    assert all(r["line"] == 3.5 for r in totals)
    assert all(r.get("event_id") == EVENT_ID for r in totals)
    # The canonical consumer: the binder normalizes the intake
    # spelling to its verified-settlement F5_TOTALS market.
    assert normalize_f5_market("F5_TOTAL") == "F5_TOTALS"
    with pytest.raises(F5BindingError) as exc:
        _parse_quote(totals[0], now=QUOTE_MLB)
    assert exc.value.code == "F5_FIXTURE_BINDING_MISSING"
