"""Regression tests for the Oct 13, 2026 SEA@DEN TNF yardage-prop
intake gap.

What happened (run record: run_it_20261013_tnf/): the DraftKings
transcription carried BOTH prices for all 19 receiving/rushing
yardage mains (e.g. Smith-Njigba O 94.5 -112 / U 94.5 -112), but the
board text written from it carried a single price per yardage line
under a non-canonical PLAYER_PROP: prefix. A per-run staging driver
converted those malformed lines into side-less intake rows, which the
engine then refused with SIDE_MUST_BE_OVER_UNDER (15 of the 19; the
other 4 died earlier at player resolution). The Under side was lost
at board emission, and no layer named the actual defect.

The canonical contract (DK_BROWSER_PROMPT in run_it_automation.py)
has always been: PROP: <Player> (<Team>) | <Market> | <Line> |
O (<odds>) | U (<odds>) -- the pair is mandatory; there is no
single-price shape for an O/U stat market. These tests pin the
canonical layer's side of that contract:

1. The TNF yardage mains, written in the established paired syntax,
   produce BOTH the OVER and the UNDER row, bound to the right
   player / market / line / game.
2. A prop line carrying the prop structure but only ONE side's
   price (a bare price, an O-only segment, or a U-only segment, in
   either the PROP: or the PLAYER_PROP: spelling) is refused with
   BOARD_LINE_ONE_SIDED -- a board-syntax defect, named as such, so
   it can never again be mistaken for a market absence or flow
   downstream as a side-less row.
3. Genuinely one-sided line families stay untouched: ANYTIME_TD
   ladders (single-price by design, a different prefix entirely)
   and TEAM_PROP's documented single-price shapes (SPREAD_1H /
   ML_1H) neither raise nor change behavior.

Prices below are the run record's own: lines and OVER prices from
board_sea_den.txt; UNDER prices from the same capture's DraftKings
transcription. Player names use the transcription's full forms
(the board abbreviated two of them: "Wilson" = Emanuel Wilson,
"AJ Barner" = A.J. Barner); team tokens use the canonical full
names the established syntax carries.
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

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)

HEADER = """\
GAME: Seattle Seahawks @ Denver Broncos | 2026-10-16T00:15:00Z
QUOTE_TIME: 2026-10-13T22:13:26-05:00
"""

# (player, team, market, line, over_odds, under_odds) -- the TNF
# receiving/rushing yardage mains from the Oct 13 capture.
YARDAGE_MAINS = [
    ("Jaxon Smith-Njigba", "Seattle Seahawks", "RECEIVING_YARDS", 94.5, -112, -112),
    ("Jaylen Waddle", "Denver Broncos", "RECEIVING_YARDS", 49.5, -111, -113),
    ("Courtland Sutton", "Denver Broncos", "RECEIVING_YARDS", 31.5, -116, -109),
    ("Rashid Shaheed", "Seattle Seahawks", "RECEIVING_YARDS", 22.5, -109, -115),
    ("Evan Engram", "Denver Broncos", "RECEIVING_YARDS", 21.5, -115, -109),
    ("A.J. Barner", "Seattle Seahawks", "RECEIVING_YARDS", 21.5, -111, -113),
    ("Cooper Kupp", "Seattle Seahawks", "RECEIVING_YARDS", 21.5, -110, -114),
    ("RJ Harvey", "Denver Broncos", "RECEIVING_YARDS", 20.5, -116, -108),
    ("Troy Franklin", "Denver Broncos", "RECEIVING_YARDS", 17.5, -108, -116),
    ("Marvin Mims", "Denver Broncos", "RECEIVING_YARDS", 11.5, -110, -114),
    ("Emanuel Wilson", "Seattle Seahawks", "RECEIVING_YARDS", 9.5, -118, -106),
    ("George Holani", "Seattle Seahawks", "RECEIVING_YARDS", 7.5, -121, -104),
    ("Tory Horton", "Seattle Seahawks", "RECEIVING_YARDS", 4.5, -116, -108),
    ("Emanuel Wilson", "Seattle Seahawks", "RUSHING_YARDS", 66.5, -113, -111),
    ("JK Dobbins", "Denver Broncos", "RUSHING_YARDS", 48.5, -109, -115),
    ("Bo Nix", "Denver Broncos", "RUSHING_YARDS", 16.5, -111, -113),
    ("RJ Harvey", "Denver Broncos", "RUSHING_YARDS", 14.5, -107, -117),
    ("George Holani", "Seattle Seahawks", "RUSHING_YARDS", 12.5, -113, -111),
    ("Sam Darnold", "Seattle Seahawks", "RUSHING_YARDS", 4.5, -113, -111),
]

# The yardage lines exactly as the Oct 13 board carried them
# (board_sea_den.txt): one price, PLAYER_PROP: prefix.
AS_RUN_ONE_SIDED_LINES = [
    "PLAYER_PROP: Jaxon Smith-Njigba (SEA) | RECEIVING_YARDS | 94.5 | -112",
    "PLAYER_PROP: Jaylen Waddle (DEN) | RECEIVING_YARDS | 49.5 | -111",
    "PLAYER_PROP: Courtland Sutton (DEN) | RECEIVING_YARDS | 31.5 | -116",
    "PLAYER_PROP: Rashid Shaheed (SEA) | RECEIVING_YARDS | 22.5 | -109",
    "PLAYER_PROP: Evan Engram (DEN) | RECEIVING_YARDS | 21.5 | -115",
    "PLAYER_PROP: AJ Barner (SEA) | RECEIVING_YARDS | 21.5 | -111",
    "PLAYER_PROP: Cooper Kupp (SEA) | RECEIVING_YARDS | 21.5 | -110",
    "PLAYER_PROP: RJ Harvey (DEN) | RECEIVING_YARDS | 20.5 | -116",
    "PLAYER_PROP: Troy Franklin (DEN) | RECEIVING_YARDS | 17.5 | -108",
    "PLAYER_PROP: Marvin Mims (DEN) | RECEIVING_YARDS | 11.5 | -110",
    "PLAYER_PROP: Wilson (SEA) | RECEIVING_YARDS | 9.5 | -118",
    "PLAYER_PROP: George Holani (SEA) | RECEIVING_YARDS | 7.5 | -121",
    "PLAYER_PROP: Tory Horton (SEA) | RECEIVING_YARDS | 4.5 | -116",
    "PLAYER_PROP: Wilson (SEA) | RUSHING_YARDS | 66.5 | -113",
    "PLAYER_PROP: JK Dobbins (DEN) | RUSHING_YARDS | 48.5 | -109",
    "PLAYER_PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | -111",
    "PLAYER_PROP: RJ Harvey (DEN) | RUSHING_YARDS | 14.5 | -107",
    "PLAYER_PROP: George Holani (SEA) | RUSHING_YARDS | 12.5 | -113",
    "PLAYER_PROP: Sam Darnold (SEA) | RUSHING_YARDS | 4.5 | -113",
]


def _fmt(odds):
    return f"({odds})"


def _paired(player, team, market, line, over_odds, under_odds, prefix="PROP:"):
    return (f"{prefix} {player} ({team}) | {market} | {line} | "
            f"O {_fmt(over_odds)} | U {_fmt(under_odds)}")


# ---------------------------------------------------------------------------
# 1. The TNF yardage mains in established paired syntax keep both sides.
# ---------------------------------------------------------------------------

def test_tnf_yardage_mains_emit_over_and_under_rows():
    board = HEADER + "\n".join(_paired(*m) for m in YARDAGE_MAINS) + "\n"
    rows = automation.parse_extended_browser_lines(board, sport="NFL", now=NOW)
    props = [r for r in rows if r["market"] in ("RECEIVING_YARDS", "RUSHING_YARDS")]
    assert len(props) == 2 * len(YARDAGE_MAINS)
    for player, team, market, line, over_odds, under_odds in YARDAGE_MAINS:
        mine = [r for r in props
                if r["player"] == player and r["market"] == market
                and r["line"] == line]
        assert len(mine) == 2, f"{player} {market}: {mine}"
        by_side = {r["side"]: r for r in mine}
        assert set(by_side) == {"OVER", "UNDER"}
        assert by_side["OVER"]["odds"] == over_odds
        assert by_side["UNDER"]["odds"] == under_odds
        for r in mine:
            assert r["team"] == team
            assert r["away"] == "Seattle Seahawks"
            assert r["home"] == "Denver Broncos"


def test_fixture_matches_run_record_over_prices():
    """The board's lone price on each as-run line was the OVER price;
    the paired fixture must agree with it line-for-line (the two
    fixtures list the same mains in the same order)."""
    assert len(AS_RUN_ONE_SIDED_LINES) == len(YARDAGE_MAINS)
    for as_run, main in zip(AS_RUN_ONE_SIDED_LINES, YARDAGE_MAINS):
        parts = [p.strip() for p in as_run.split("|")]
        assert parts[1] == main[2], as_run
        assert float(parts[2]) == main[3], as_run
        assert int(parts[3]) == main[4], as_run


# ---------------------------------------------------------------------------
# 2. One-sided prop lines are refused by name: BOARD_LINE_ONE_SIDED.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", AS_RUN_ONE_SIDED_LINES)
def test_as_run_one_sided_yardage_lines_refused_by_name(line):
    with pytest.raises(ValueError, match="BOARD_LINE_ONE_SIDED"):
        automation.parse_extended_browser_lines(HEADER + line + "\n",
                                                sport="NFL", now=NOW)


@pytest.mark.parametrize("tail", ["-112", "O (-112)", "U (-112)"])
def test_one_sided_prop_line_variants_refused(tail):
    line = ("PROP: Jaxon Smith-Njigba (Seattle Seahawks) | "
            f"RECEIVING_YARDS | 94.5 | {tail}")
    with pytest.raises(ValueError, match="BOARD_LINE_ONE_SIDED"):
        automation.parse_extended_browser_lines(HEADER + line + "\n",
                                                sport="NFL", now=NOW)


def test_one_sided_refusal_names_the_offending_line():
    line = AS_RUN_ONE_SIDED_LINES[0]
    with pytest.raises(ValueError) as excinfo:
        automation.parse_extended_browser_lines(HEADER + line + "\n",
                                                sport="NFL", now=NOW)
    assert "RECEIVING_YARDS" in str(excinfo.value)
    assert "94.5" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. PLAYER_PROP: spelling: same strict parser, same refusal.
# ---------------------------------------------------------------------------

def test_player_prop_prefix_paired_line_emits_both_rows():
    board = HEADER + _paired("Jaxon Smith-Njigba", "Seattle Seahawks",
                             "RECEIVING_YARDS", 94.5, -112, -112,
                             prefix="PLAYER_PROP:") + "\n"
    rows = automation.parse_extended_browser_lines(board, sport="NFL", now=NOW)
    props = [r for r in rows if r["market"] == "RECEIVING_YARDS"]
    assert {(r["side"], r["odds"]) for r in props} == {("OVER", -112),
                                                       ("UNDER", -112)}


# ---------------------------------------------------------------------------
# 4. Genuinely one-sided families are untouched.
# ---------------------------------------------------------------------------

def test_anytime_td_and_team_prop_single_price_shapes_unaffected():
    board = HEADER + (
        "ANYTIME_TD: Jaxon Smith-Njigba (SEA) (+105)\n"
        "TEAM_PROP: Denver Broncos | SPREAD_1H | -0.5 | -110\n"
        "TEAM_PROP: Seattle Seahawks | ML_1H | -135\n"
    )
    rows = automation.parse_extended_browser_lines(board, sport="NFL", now=NOW)
    markets = {r["market"] for r in rows}
    assert "RECEIVING_YARDS" not in markets
    assert "SPREAD_1H" in markets and "ML_1H" in markets


def test_unstructured_prop_line_stays_silent_none():
    """The refusal is precise: a PROP: line that is not recognizably a
    structured prop line at all keeps the legacy no-rows behavior --
    BOARD_LINE_ONE_SIDED is only for a structured line missing a side."""
    board = HEADER + "PROP: promo banner scrawl with no structure\n"
    rows = automation.parse_extended_browser_lines(board, sport="NFL", now=NOW)
    assert isinstance(rows, list)
