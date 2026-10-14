"""Reproduction + regression tests for the four RUN IT automation-intake
defects documented on Oct 13, 2026:

1. The base intake parser hardcoded sport="NFL" regardless of the board.
2. GAME headers only survived one exact datetime shape; other common
   formats ("Today 7:00 PM") were passed through raw / misparsed instead
   of being parsed or explicitly refused.
3. Prop rows carried no away/home binding to their game.
4. F5 / NRFI (first-inning) prefixed MLB rows were dropped in parsing,
   losing their market identity.

Fixtures are the actual Oct 13 DK board texts (dk_mlb_refresh.txt /
dk_cfb_refresh.txt from the RUN IT session records) plus the documented
NFL board shape from the base parser's own docstring.

The modules under test are loaded from the repo's artifacts/ directory.
Set RUN_IT_INTAKE_DIR to a directory holding the legacy (pre-fix) bridge
copies of run_it_browser.py / run_it_automation.py to demonstrate the
failures against current code.
"""
import importlib.util
import os
from datetime import datetime, timezone
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

# The Oct 13 sessions captured at 10:08 AM CDT == 15:08Z; the board
# QUOTE_TIME lines declare America/Chicago.
NOW = datetime(2026, 10, 13, 15, 8, tzinfo=timezone.utc)

MLB_BOARD = """\
GAME: Cleveland Guardians @ Tampa Bay Rays | Today 7:00 PM
SPREAD: Cleveland Guardians +1.5 (-194) | Tampa Bay Rays -1.5 (+159)
TOTAL: O 7 (+102) | U 7 (-122)
ML: Cleveland Guardians (+119) | Tampa Bay Rays (-143)
F5_ML: Cleveland Guardians (-115) | Tampa Bay Rays (-115)
FIRST_INNING: O 0.5 (+110) | U 0.5 (-145)
TEAM_PROP: Cleveland Guardians | TEAM_TOTAL | 3.5 | O (+120) | U (-154)
TEAM_PROP: Tampa Bay Rays | TEAM_TOTAL | 3.5 | O (-110) | U (-120)
PROP: Parker Messick (Cleveland Guardians) | PITCHER_STRIKEOUTS | 4.5 | O (-150) | U (+117)
PROP: Parker Messick (Cleveland Guardians) | PITCHER_OUTS | 14.5 | O (-126) | U (-105)
PROP: Freddy Peralta (Tampa Bay Rays) | PITCHER_STRIKEOUTS | 3.5 | O (-123) | U (-104)
QUOTE_TIME: 2026-10-13 5:08 AM CDT (America/Chicago)
"""

CFB_BOARD = """\
GAME: Delaware @ Middle Tennessee | Today 6:00 PM
SPREAD: Delaware -1.5 (-102) | Middle Tennessee +1.5 (-118)
TOTAL: O 47.5 (-115) | U 47.5 (-105)
ML: Delaware (-118) | Middle Tennessee (-102)
TEAM_PROP: Delaware | TEAM_TOTAL | 23.5 | O (-135) | U (+100)
TEAM_PROP: Middle Tennessee | TEAM_TOTAL | 23.5 | O (-120) | U (-105)
GAME: FIU @ Jacksonville State | Today 7:00 PM
SPREAD: FIU +3 (-115) | Jacksonville State -3 (-105)
TOTAL: O 43.5 (-112) | U 43.5 (-108)
ML: FIU (+120) | Jacksonville State (-142)
QUOTE_TIME: 2026-10-13 5:08 AM CDT (America/Chicago)
"""

NFL_BOARD = """\
GAME: Buffalo Bills @ Los Angeles Rams | 2026-10-13 20:15 ET
SPREAD: Bills +3.5 (-118) | Rams -3.5 (-102)
TOTAL: O 54.5 (-118) | U 54.5 (-102)
ML: Bills (+150) | Rams (-180)
"""


def _game_board(kickoff, sport="NFL"):
    return (
        f"GAME: Buffalo Bills @ Los Angeles Rams | {kickoff}\n"
        "SPREAD: Bills +3.5 (-118) | Rams -3.5 (-102)\n"
        "TOTAL: O 54.5 (-118) | U 54.5 (-102)\n"
        "ML: Bills (+150) | Rams (-180)\n"
    )


# ---------------------------------------------------------------------------
# Defect 1: sport is taken from the board/context, never hardcoded.
# ---------------------------------------------------------------------------

def test_mlb_board_rows_all_carry_board_sport():
    rows = automation.parse_extended_browser_lines(MLB_BOARD, sport="MLB", now=NOW)
    assert rows, "MLB board parsed to nothing"
    assert {r["sport"] for r in rows} == {"MLB"}
    # The Oct 13 automation card literally carried NFL rows for this game.
    game_rows = [r for r in rows if r["market"] in ("ML", "MONEYLINE", "SPREAD", "TOTAL")]
    assert game_rows and all(r["sport"] == "MLB" for r in game_rows)


def test_cfb_board_rows_all_carry_board_sport():
    rows = automation.parse_extended_browser_lines(CFB_BOARD, sport="CFB", now=NOW)
    assert rows
    assert {r["sport"] for r in rows} == {"CFB"}


def test_base_parser_labels_rows_with_given_sport():
    rows = browser.parse_browser_lines(NFL_BOARD, sport="CFB", now=NOW)
    assert rows and {r["sport"] for r in rows} == {"CFB"}


def test_base_parser_requires_sport_argument():
    with pytest.raises(TypeError):
        browser.parse_browser_lines(NFL_BOARD)


def test_extended_parser_requires_sport():
    with pytest.raises((TypeError, ValueError)):
        automation.parse_extended_browser_lines(NFL_BOARD, now=NOW)


def test_unknown_sport_refused_with_named_reason():
    with pytest.raises(ValueError, match="INTAKE_SPORT_UNRECOGNIZED"):
        browser.parse_browser_lines(NFL_BOARD, sport="XFL", now=NOW)
    with pytest.raises(ValueError, match="INTAKE_SPORT_UNRECOGNIZED"):
        automation.parse_extended_browser_lines(NFL_BOARD, sport="XFL", now=NOW)


def test_execute_plan_without_sport_fails_closed(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("run_model must not be reached without a sport")

    monkeypatch.setattr(automation, "run_model", _boom)
    plan = {"command": {"sport": None, "raw": "run it", "teams": [],
                        "scope": "all sports"}}
    with pytest.raises(ValueError, match="INTAKE_SPORT_UNRESOLVED"):
        automation.execute_run_it_plan(plan, NFL_BOARD)


# ---------------------------------------------------------------------------
# Defect 2: GAME header datetimes are parsed from the documented formats
# or explicitly refused -- never passed through raw to be guessed at.
# ---------------------------------------------------------------------------

def test_mlb_today_header_resolves_against_board_zone():
    rows = automation.parse_extended_browser_lines(MLB_BOARD, sport="MLB", now=NOW)
    # "Today 7:00 PM" in America/Chicago (QUOTE_TIME) on Oct 13 == 00:00Z.
    assert {r["kickoff"] for r in rows} == {"2026-10-14T00:00:00+00:00"}


def test_cfb_today_headers_resolve_per_game():
    rows = automation.parse_extended_browser_lines(CFB_BOARD, sport="CFB", now=NOW)
    by_home = {}
    for r in rows:
        by_home.setdefault(r["home"], set()).add(r["kickoff"])
    assert by_home["Middle Tennessee"] == {"2026-10-13T23:00:00+00:00"}
    assert by_home["Jacksonville State"] == {"2026-10-14T00:00:00+00:00"}


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-13 20:15 ET", "2026-10-14T00:15:00+00:00"),
    ("2026-10-13T20:15:00-04:00", "2026-10-14T00:15:00+00:00"),
    ("2026-10-13T20:15:00Z", "2026-10-13T20:15:00+00:00"),
    ("Oct 13, 2026 8:15 PM ET", "2026-10-14T00:15:00+00:00"),
    ("Tomorrow 1:05 PM ET", "2026-10-14T17:05:00+00:00"),
    ("Today 7:00 PM CT", "2026-10-14T00:00:00+00:00"),
])
def test_kickoff_documented_formats(raw, expected):
    rows = browser.parse_browser_lines(_game_board(raw), sport="NFL", now=NOW)
    assert rows and {r["kickoff"] for r in rows} == {expected}


def test_kickoff_unparseable_refused_with_named_reason():
    with pytest.raises(ValueError, match="INTAKE_KICKOFF_UNPARSEABLE"):
        browser.parse_browser_lines(_game_board("Whenever, probably"), sport="NFL", now=NOW)


def test_kickoff_naive_iso_refused_with_named_reason():
    with pytest.raises(ValueError, match="INTAKE_KICKOFF_TIMEZONE_REQUIRED"):
        browser.parse_browser_lines(_game_board("2026-10-13T20:15:00"), sport="NFL", now=NOW)


def test_kickoff_today_without_any_zone_refused():
    board = _game_board("Today 7:00 PM")  # no QUOTE_TIME zone, no board_tz
    with pytest.raises(ValueError, match="INTAKE_KICKOFF_TIMEZONE_UNRESOLVED"):
        browser.parse_browser_lines(board, sport="NFL", now=NOW)


def test_kickoff_today_with_explicit_board_zone():
    board = _game_board("Today 7:00 PM")
    rows = browser.parse_browser_lines(board, sport="NFL", now=NOW,
                                       board_tz="America/Chicago")
    assert {r["kickoff"] for r in rows} == {"2026-10-14T00:00:00+00:00"}


def test_game_header_missing_datetime_refused():
    with pytest.raises(ValueError, match="INTAKE_GAME_HEADER_UNPARSEABLE"):
        browser.parse_browser_lines("GAME: Buffalo Bills @ Los Angeles Rams\n",
                                    sport="NFL", now=NOW)


# ---------------------------------------------------------------------------
# Defect 3: prop rows carry explicit away/home binding from their game.
# ---------------------------------------------------------------------------

def test_prop_rows_carry_game_away_home():
    rows = automation.parse_extended_browser_lines(MLB_BOARD, sport="MLB", now=NOW)
    props = [r for r in rows if r.get("player") == "Parker Messick"]
    assert len(props) == 4  # 2 markets x OVER/UNDER
    for r in props:
        assert r["away"] == "Cleveland Guardians"
        assert r["home"] == "Tampa Bay Rays"
    peralta = [r for r in rows if r.get("player") == "Freddy Peralta"]
    assert peralta and all(
        r["away"] == "Cleveland Guardians" and r["home"] == "Tampa Bay Rays"
        for r in peralta)


def test_every_parsed_row_is_bound_to_a_game():
    for board, sport in ((MLB_BOARD, "MLB"), (CFB_BOARD, "CFB")):
        rows = automation.parse_extended_browser_lines(board, sport=sport, now=NOW)
        assert rows
        for r in rows:
            assert r.get("away") and r.get("home"), f"unbound row floated: {r}"


def test_prop_before_any_game_refused_with_named_reason():
    board = ("PROP: Parker Messick (Cleveland Guardians) | "
             "PITCHER_STRIKEOUTS | 4.5 | O (-150) | U (+117)\n")
    with pytest.raises(ValueError, match="INTAKE_PROP_UNBOUND_NO_GAME_CONTEXT"):
        automation.parse_extended_browser_lines(board, sport="MLB", now=NOW)


def test_team_prop_before_any_game_refused_with_named_reason():
    board = "TEAM_PROP: Cleveland Guardians | TEAM_TOTAL | 3.5 | O (+120) | U (-154)\n"
    with pytest.raises(ValueError, match="INTAKE_TEAM_PROP_UNBOUND_NO_GAME_CONTEXT"):
        automation.parse_extended_browser_lines(board, sport="MLB", now=NOW)


# ---------------------------------------------------------------------------
# Defect 4: F5 / first-inning (NRFI/YRFI) prefixes survive parsing.
# ---------------------------------------------------------------------------

def test_f5_moneyline_rows_preserved_and_distinguishable():
    rows = automation.parse_extended_browser_lines(MLB_BOARD, sport="MLB", now=NOW)
    f5 = [r for r in rows if r["market"] == "F5_MONEYLINE"]
    assert len(f5) == 2
    assert {r["side"] for r in f5} == {"AWAY", "HOME"}
    assert {r["odds"] for r in f5} == {-115}
    assert all(r["away"] == "Cleveland Guardians" for r in f5)
    full_game_ml = [r for r in rows if r["market"] in ("ML", "MONEYLINE")]
    assert full_game_ml and all(r["market"] != "F5_MONEYLINE" for r in full_game_ml)


def test_first_inning_rows_become_nrfi_yrfi_pair():
    rows = automation.parse_extended_browser_lines(MLB_BOARD, sport="MLB", now=NOW)
    nrfi = [r for r in rows if r["market"] == "NRFI"]
    yrfi = [r for r in rows if r["market"] == "YRFI"]
    assert len(nrfi) == 1 and len(yrfi) == 1
    assert nrfi[0]["odds"] == -145 and float(nrfi[0]["line"]) == 0.5
    assert yrfi[0]["odds"] == 110 and float(yrfi[0]["line"]) == 0.5


def test_f5_spread_and_total_shapes_preserved():
    board = (
        "GAME: Cleveland Guardians @ Tampa Bay Rays | 2026-10-13 19:00 ET\n"
        "F5_SPREAD: Cleveland Guardians +0.5 (-150) | Tampa Bay Rays -0.5 (+122)\n"
        "F5_TOTAL: O 4.5 (-110) | U 4.5 (-110)\n"
    )
    rows = browser.parse_browser_lines(board, sport="MLB", now=NOW)
    assert {r["market"] for r in rows} == {"F5_SPREAD", "F5_TOTAL"}
    spread = [r for r in rows if r["market"] == "F5_SPREAD"]
    assert {r["side"] for r in spread} == {"AWAY", "HOME"}
    total = [r for r in rows if r["market"] == "F5_TOTAL"]
    assert {r["side"] for r in total} == {"OVER", "UNDER"}
    assert all(float(r["line"]) == 4.5 for r in total)


def test_nrfi_yrfi_identity_survives_model_normalization():
    for market in ("NRFI", "YRFI"):
        out = automation._normalize_line({"market": market, "selection": ""})
        assert out["market"] == market


def test_unparseable_f5_line_refused_not_dropped():
    board = (
        "GAME: Cleveland Guardians @ Tampa Bay Rays | 2026-10-13 19:00 ET\n"
        "F5_ML: this is not a line\n"
    )
    with pytest.raises(ValueError, match="INTAKE_PERIOD_LINE_UNPARSEABLE"):
        browser.parse_browser_lines(board, sport="MLB", now=NOW)


# ---------------------------------------------------------------------------
# Preserved base behavior (regression guards for the documented shapes).
# ---------------------------------------------------------------------------

def test_documented_nfl_board_shape_still_parses():
    rows = browser.parse_browser_lines(NFL_BOARD, sport="NFL", now=NOW)
    markets = {}
    for r in rows:
        markets.setdefault(r["market"], set()).add(r["side"])
    assert markets["SPREAD"] == {"AWAY", "HOME"}
    assert markets["TOTAL"] == {"OVER", "UNDER"}
    assert markets["MONEYLINE"] == {"AWAY", "HOME"}
    ml = [r for r in rows if r["market"] == "MONEYLINE" and r["side"] == "AWAY"]
    assert ml[0]["odds"] == 150
