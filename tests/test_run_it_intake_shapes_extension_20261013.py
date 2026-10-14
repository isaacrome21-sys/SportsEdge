"""Reproduction + regression tests for the two RUN IT intake repairs
exposed by the Oct 13, 2026 evening live run (held extension of the
Oct 13 intake-defect fix pass):

5. F5 rows carried no sportsbook/source. Every F5 row on the evening
   boards (F5_MONEYLINE / F5_SPREAD / F5_TEAM_TOTAL) stopped at the
   F5 quote-binding gate's first check (F5_SOURCE_MISSING in
   sportsedge/mlb_f5_quote_binding) because the parsed row shape named
   no book -- the board capture's own source declaration never reached
   the rows. Fix: a board-level SOURCE header declaration (or the
   caller's explicit board_book) is stamped onto every parsed row as
   `book`, the field the binding gate reads. A capture that declares
   no source stamps nothing, and its F5 rows keep failing closed.

6. Single-price TEAM_PROP lines for first-half spread / moneyline
   produced zero rows. The documented TEAM_PROP shape is an O/U pair;
   tonight's CFB boards carried `TEAM_PROP: <Team> | SPREAD_1H |
   <line> | <odds>` and `TEAM_PROP: <Team> | ML_1H | <odds>`, which
   matched no shape and were silently skipped. Fix: those two shapes
   parse into bound rows (side AWAY/HOME from the game header, the
   convention run_it_full's phone rows use for SPREAD_1H / ML_1H).
   Any other single-price market keeps returning None.

Fixtures are tonight's actual board texts
(sportsedge/run_it_20261013_evening/board{1,2,3}_*.txt), with a
SOURCE header added where a test exercises the declared-source path.
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
QUOTE_MLB = datetime(2026, 10, 13, 15, 19, 30, tzinfo=CT)
QUOTE_CFB = datetime(2026, 10, 13, 15, 20, 30, tzinfo=CT)

# Tonight's Board 1 (ALCS Game 2), verbatim from the run record.
MLB_BOARD = """\
QUOTE_TIME: 2026-10-13T15:19:30-05:00
GAME: Cleveland Guardians @ Tampa Bay Rays | 2026-10-13 19:00 CT
SPREAD: Cleveland Guardians +1.5 (-199) | Tampa Bay Rays -1.5 (+163)
TOTAL: O 7 (+102) | U 7 (-122)
ML: Cleveland Guardians (+110) | Tampa Bay Rays (-132)
F5_ML: Cleveland Guardians (-105) | Tampa Bay Rays (-125)
F5_SPREAD: Cleveland Guardians -1.5 (+250) | Tampa Bay Rays +1.5 (-345)
F5_SPREAD: Cleveland Guardians -0.5 (+135) | Tampa Bay Rays +0.5 (-175)
F5_SPREAD: Cleveland Guardians +0.5 (-145) | Tampa Bay Rays -0.5 (+114)
F5_SPREAD: Cleveland Guardians +1.5 (-270) | Tampa Bay Rays -1.5 (+200)
FIRST_INNING: O 0.5 (+105) | U 0.5 (-135)
FIRST_INNING: O 1.5 (+255) | U 1.5 (-340)
TEAM_PROP: Cleveland Guardians | TEAM_TOTAL | 3.5 | O (+114) | U (-145)
TEAM_PROP: Tampa Bay Rays | TEAM_TOTAL | 3.5 | O (-105) | U (-125)
TEAM_PROP: Cleveland Guardians | F5_TEAM_TOTAL | 1.5 | O (-115) | U (-115)
TEAM_PROP: Tampa Bay Rays | F5_TEAM_TOTAL | 1.5 | O (-130) | U (+100)
TEAM_PROP: Tampa Bay Rays | F5_TEAM_TOTAL | 2.5 | O (-238) | U (+180)
TEAM_PROP: Tampa Bay Rays | F5_TEAM_TOTAL | 3.5 | O (-130) | U (+100)
TEAM_PROP: Tampa Bay Rays | F5_TEAM_TOTAL | 4.5 | O (+135) | U (-175)
"""

MLB_BOARD_DECLARED = "SOURCE: DraftKings\n" + MLB_BOARD

# Tonight's Board 2 (Delaware @ Middle Tennessee), verbatim.
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

# Tonight's Board 3 (FIU @ Jacksonville State), verbatim.
CFB_BOARD_FIU = """\
QUOTE_TIME: 2026-10-13T15:20:30-05:00
GAME: FIU @ Jacksonville State | 2026-10-13 19:00 CT
SPREAD: FIU +3 (-105) | Jacksonville State -3 (-115)
TOTAL: O 43.5 (-115) | U 43.5 (-105)
ML: FIU (+130) | Jacksonville State (-155)
TEAM_PROP: FIU | TEAM_TOTAL | 20.5 | O (-110) | U (-120)
TEAM_PROP: Jacksonville State | TEAM_TOTAL | 23.5 | O (-110) | U (-120)
TEAM_PROP: Game | TOTAL_1H | 21.5 | O (-118) | U (-102)
TEAM_PROP: FIU | SPREAD_1H | +1.5 | -105
TEAM_PROP: Jacksonville State | SPREAD_1H | -1.5 | -115
TEAM_PROP: FIU | ML_1H | +130
TEAM_PROP: Jacksonville State | ML_1H | -155
"""

F5_MARKETS = ("F5_MONEYLINE", "F5_SPREAD", "F5_TEAM_TOTAL")


def _f5_rows(rows):
    return [r for r in rows if r["market"] in F5_MARKETS]


# ---------------------------------------------------------------------------
# Defect 5: F5 rows carry the board capture's DECLARED source.
# ---------------------------------------------------------------------------

def test_declared_source_stamps_every_f5_row():
    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_DECLARED, sport="MLB", now=QUOTE_MLB)
    f5 = _f5_rows(rows)
    # Tonight's board: 2 F5 ML + 8 F5 spread + 10 F5 team-total rows.
    assert len(f5) == 20
    assert {r["market"] for r in f5} == set(F5_MARKETS)
    assert all(r.get("book") == "DraftKings" for r in f5)


def test_declared_source_stamps_game_rows_the_same_way():
    rows = automation.parse_extended_browser_lines(
        MLB_BOARD_DECLARED, sport="MLB", now=QUOTE_MLB)
    assert rows and all(r.get("book") == "DraftKings" for r in rows)


def test_undeclared_board_stamps_no_source_anywhere():
    rows = automation.parse_extended_browser_lines(
        MLB_BOARD, sport="MLB", now=QUOTE_MLB)
    assert len(_f5_rows(rows)) == 20
    assert all("book" not in r for r in rows)


def test_explicit_board_book_argument_stamps_rows():
    rows = browser.parse_browser_lines(
        MLB_BOARD, sport="MLB", now=QUOTE_MLB, board_book="DraftKings")
    assert _f5_rows(rows) and all(
        r.get("book") == "DraftKings" for r in rows)


def test_explicit_board_book_wins_over_header_declaration():
    board = "SOURCE: SomeOtherBook\n" + MLB_BOARD
    rows = browser.parse_browser_lines(
        board, sport="MLB", now=QUOTE_MLB, board_book="DraftKings")
    assert rows and all(r.get("book") == "DraftKings" for r in rows)


def test_board_source_header_reader():
    assert browser.board_source_from_header(MLB_BOARD_DECLARED) == "DraftKings"
    assert browser.board_source_from_header(MLB_BOARD) is None


def test_f5_binding_gate_accepts_declared_source_row():
    """Binder-level two-direction proof against the real gate."""
    from sportsedge.mlb_f5_quote_binding import F5BindingError, _parse_quote

    declared = automation.parse_extended_browser_lines(
        MLB_BOARD_DECLARED, sport="MLB", now=QUOTE_MLB)
    row = next(r for r in declared if r["market"] == "F5_MONEYLINE")
    with pytest.raises(F5BindingError) as exc:
        _parse_quote(row, now=QUOTE_MLB)
    # Gate 1 (source) passed; the row stops at the NEXT gate, which is
    # about book event identity the text board does not carry.
    assert exc.value.code == "F5_EVENT_ID_MISSING"


def test_f5_binding_gate_still_refuses_undeclared_source_row():
    from sportsedge.mlb_f5_quote_binding import F5BindingError, _parse_quote

    undeclared = automation.parse_extended_browser_lines(
        MLB_BOARD, sport="MLB", now=QUOTE_MLB)
    row = next(r for r in undeclared if r["market"] == "F5_MONEYLINE")
    with pytest.raises(F5BindingError) as exc:
        _parse_quote(row, now=QUOTE_MLB)
    assert exc.value.code == "F5_SOURCE_MISSING"


# ---------------------------------------------------------------------------
# Defect 6: single-price SPREAD_1H / ML_1H TEAM_PROP lines produce rows.
# ---------------------------------------------------------------------------

def _by_market(rows, market):
    return [r for r in rows if r["market"] == market]


def test_delaware_board_first_half_spread_rows():
    rows = automation.parse_extended_browser_lines(
        CFB_BOARD_DEL, sport="CFB", now=QUOTE_CFB)
    spread = _by_market(rows, "SPREAD_1H")
    assert len(spread) == 2
    away = next(r for r in spread if r["side"] == "AWAY")
    home = next(r for r in spread if r["side"] == "HOME")
    assert away["team"] == "Delaware" and float(away["line"]) == -0.5
    assert away["odds"] == 102
    assert home["team"] == "Middle Tennessee" and float(home["line"]) == 0.5
    assert home["odds"] == -122
    for r in spread:
        assert r["away"] == "Delaware" and r["home"] == "Middle Tennessee"
        assert r["kickoff"] == "2026-10-13T23:00:00+00:00"
        assert r["sport"] == "CFB"


def test_delaware_board_first_half_moneyline_rows():
    rows = automation.parse_extended_browser_lines(
        CFB_BOARD_DEL, sport="CFB", now=QUOTE_CFB)
    ml = _by_market(rows, "ML_1H")
    assert len(ml) == 2
    away = next(r for r in ml if r["side"] == "AWAY")
    home = next(r for r in ml if r["side"] == "HOME")
    assert away["team"] == "Delaware" and away["odds"] == -120
    assert home["team"] == "Middle Tennessee" and home["odds"] == 100
    assert all("line" not in r for r in ml)
    assert all(r["kickoff"] == "2026-10-13T23:00:00+00:00" for r in ml)


def test_fiu_board_first_half_rows():
    rows = automation.parse_extended_browser_lines(
        CFB_BOARD_FIU, sport="CFB", now=QUOTE_CFB)
    spread = _by_market(rows, "SPREAD_1H")
    assert len(spread) == 2
    away = next(r for r in spread if r["side"] == "AWAY")
    home = next(r for r in spread if r["side"] == "HOME")
    assert away["team"] == "FIU" and float(away["line"]) == 1.5
    assert away["odds"] == -105
    assert home["team"] == "Jacksonville State" and float(home["line"]) == -1.5
    assert home["odds"] == -115
    ml = _by_market(rows, "ML_1H")
    assert len(ml) == 2
    assert {r["odds"] for r in ml} == {130, -155}
    assert all(r["kickoff"] == "2026-10-14T00:00:00+00:00" for r in ml + spread)


def test_first_half_total_pair_shape_canonical_bare_sides():
    # PIN RETIRED under coordinator ruling (B), Oct 13 2026. This test
    # previously pinned the baseline compound shape (AWAY_OVER /
    # AWAY_UNDER) as a scope guard from the shapes-extension build. The
    # team-prop root-cause work proved compound sides are the defect
    # itself: free_models.calculate() requires a bare OVER/UNDER side
    # plus a resolvable team, and team_half_pricing's side check accepts
    # only bare sides, so compound pair rows priced through NEITHER
    # canonical consumer. The pin preserved a scope guard, not a
    # contract; the canonical TEAM_PROP pair shape is the bare one
    # pinned here.
    rows = automation.parse_extended_browser_lines(
        CFB_BOARD_DEL, sport="CFB", now=QUOTE_CFB)
    total_1h = _by_market(rows, "TOTAL_1H")
    assert len(total_1h) == 2
    assert {r["side"] for r in total_1h} == {"OVER", "UNDER"}
    assert {r["odds"] for r in total_1h} == {-118, -102}
    assert all(float(r["line"]) == 23.5 for r in total_1h)


def test_single_price_team_prop_before_any_game_refused():
    for line in ("TEAM_PROP: Delaware | SPREAD_1H | -0.5 | +102\n",
                 "TEAM_PROP: Delaware | ML_1H | -120\n"):
        with pytest.raises(
                ValueError, match="INTAKE_TEAM_PROP_UNBOUND_NO_GAME_CONTEXT"):
            automation.parse_extended_browser_lines(
                line, sport="CFB", now=QUOTE_CFB)


def test_unsupported_single_price_markets_still_produce_no_rows():
    board = (
        "GAME: Delaware @ Middle Tennessee | 2026-10-13 18:00 CT\n"
        "SPREAD: Delaware -1.5 (-105) | Middle Tennessee +1.5 (-115)\n"
        "TEAM_PROP: Delaware | SPREAD_2H | -0.5 | +102\n"
        "TEAM_PROP: Delaware | ANYTIME_TD | +150\n"
        "TEAM_PROP: Delaware | TOTAL_2H | 24.5 | -110\n"
    )
    rows = automation.parse_extended_browser_lines(
        board, sport="CFB", now=QUOTE_CFB)
    assert rows  # the game rows still parse
    assert not [r for r in rows
                if r["market"] in ("SPREAD_2H", "ANYTIME_TD", "TOTAL_2H")]


def test_parse_team_prop_line_single_price_units():
    game = {"away": "Delaware", "home": "Middle Tennessee",
            "kickoff": "2026-10-13T23:00:00+00:00"}
    out = automation.parse_team_prop_line(
        "TEAM_PROP: Delaware | SPREAD_1H | -0.5 | +102",
        game, "CFB", QUOTE_CFB)
    assert out is not None and len(out) == 1
    assert out[0]["side"] == "AWAY" and out[0]["odds"] == 102
    out = automation.parse_team_prop_line(
        "TEAM_PROP: Middle Tennessee | ML_1H | +100",
        game, "CFB", QUOTE_CFB)
    assert out is not None and len(out) == 1
    assert out[0]["side"] == "HOME" and "line" not in out[0]
    # Still no shape: unsupported market and malformed lines return None.
    assert automation.parse_team_prop_line(
        "TEAM_PROP: Delaware | SPREAD_2H | -0.5 | +102",
        game, "CFB", QUOTE_CFB) is None
    assert automation.parse_team_prop_line(
        "TEAM_PROP: not a real line", game, "CFB", QUOTE_CFB) is None
