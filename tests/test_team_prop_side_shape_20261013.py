"""TEAM_PROP side-shape contract (Oct 13, 2026).

Root cause pinned by the evening RUN IT of Oct 13: the browser-text
intake's TEAM_PROP parser emitted compound sides ("AWAY_OVER",
"HOME_UNDER") for team-total rows. Every pricing consumer except the
F5 phone pricer requires the canonical shape -- a bare OVER/UNDER side
plus the team identity carried in the row's team/team_side fields --
so free_models.calculate() refused all four CLE/TB full-game team
totals with TEAM_TOTALS_TEAM_OR_SIDE_UNVERIFIED while the ML, spread
and game-total rows from the same board priced normally.

These tests pin:
  1. the parser emitting the canonical shape (bare side + team_side),
  2. parsed team-total rows passing the engine's team/side
     verification (the gate itself is NOT weakened -- see 3),
  3. the engine still refusing unverifiable rows fed to it directly,
     including the old compound shape, a team outside the fixture,
     and a team/selection identity conflict,
  4. an unresolvable TEAM_PROP team never being silently labeled AWAY
     (the pre-fix parser defaulted any non-home team to AWAY).
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "artifacts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


automation = _load("run_it_automation")
free_models = _load("free_models")

NOW = datetime(2026, 10, 13, 15, 19, 30,
               tzinfo=timezone.utc).replace(tzinfo=timezone.utc)
GAME = {"away": "Cleveland Guardians", "home": "Tampa Bay Rays",
        "kickoff": "2026-10-14T00:00:00+00:00"}
CALC_NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)

# Tonight's actual board lines (run_it_20261013_evening/board1_mlb.txt).
CLE_TT = "TEAM_PROP: Cleveland Guardians | TEAM_TOTAL | 3.5 | O (+114) | U (-145)"
TB_TT = "TEAM_PROP: Tampa Bay Rays | TEAM_TOTAL | 3.5 | O (-105) | U (-125)"


def _calc(row):
    return free_models.calculate(row, None, CALC_NOW, auto_context=False)


# ---------------------------------------------------------------------------
# 1. Parser emits the canonical shape.
# ---------------------------------------------------------------------------

def test_team_prop_rows_carry_bare_side_and_team_side():
    rows = automation.parse_team_prop_line(CLE_TT, GAME, "MLB", NOW)
    assert rows is not None and len(rows) == 2
    over, under = rows
    assert over["side"] == "OVER" and over["odds"] == 114
    assert under["side"] == "UNDER" and under["odds"] == -145
    for row in rows:
        assert row["team"] == "Cleveland Guardians"
        assert row["team_side"] == "AWAY"
        assert row["market"] == "TEAM_TOTAL"
        assert row["line"] == 3.5


def test_team_prop_home_team_resolves_home():
    rows = automation.parse_team_prop_line(TB_TT, GAME, "MLB", NOW)
    assert rows and all(r["team_side"] == "HOME" for r in rows)
    assert [r["side"] for r in rows] == ["OVER", "UNDER"]


def test_team_prop_abbreviated_team_still_resolves():
    # Boards have historically abbreviated ("Rays"); a unique
    # containment match keeps those boards binding.
    rows = automation.parse_team_prop_line(
        "TEAM_PROP: Rays | TEAM_TOTAL | 3.5 | O (-105) | U (-125)",
        GAME, "MLB", NOW)
    assert rows and all(r["team_side"] == "HOME" for r in rows)


def test_team_prop_game_level_market_has_no_team_side():
    # Tonight's CFB board carried "TEAM_PROP: Game | TOTAL_1H | ..." --
    # a game-level market whose team token names no team.
    game = {"away": "Delaware", "home": "Middle Tennessee",
            "kickoff": "2026-10-13T23:00:00+00:00"}
    rows = automation.parse_team_prop_line(
        "TEAM_PROP: Game | TOTAL_1H | 23.5 | O (-118) | U (-102)",
        game, "CFB", NOW)
    assert rows and [r["side"] for r in rows] == ["OVER", "UNDER"]
    assert all("team_side" not in r for r in rows)


# ---------------------------------------------------------------------------
# 2. Parsed rows pass the engine's team/side verification.
# ---------------------------------------------------------------------------

def test_parsed_team_total_rows_pass_engine_verification():
    for line in (CLE_TT, TB_TT):
        for row in automation.parse_team_prop_line(line, GAME, "MLB", NOW):
            row = dict(row, commence_time="2026-10-14T00:00:00Z")
            try:
                result = _calc(row)
            except ValueError as exc:
                pytest.fail(f"engine refused a well-formed row: {exc}")
            assert result.get("reason") != "TEAM_TOTALS_TEAM_OR_SIDE_UNVERIFIED"


# ---------------------------------------------------------------------------
# 3. The engine gate is NOT weakened.
# ---------------------------------------------------------------------------

def _engine_row(**kw):
    row = {"sport": "MLB", "away": "Cleveland Guardians",
           "home": "Tampa Bay Rays", "market": "TEAM_TOTAL",
           "line": 3.5, "odds": 114,
           "commence_time": "2026-10-14T00:00:00Z"}
    row.update(kw)
    return row


def test_engine_still_refuses_compound_side():
    with pytest.raises(ValueError, match="TEAM_TOTALS_TEAM_OR_SIDE_UNVERIFIED"):
        _calc(_engine_row(team="Cleveland Guardians", side="AWAY_OVER"))


def test_engine_still_refuses_team_outside_fixture():
    with pytest.raises(ValueError, match="TEAM_TOTALS_TEAM_OR_SIDE_UNVERIFIED"):
        _calc(_engine_row(team="New York Yankees", side="OVER"))


def test_engine_still_refuses_conflicting_team_identity():
    with pytest.raises(ValueError, match="TEAM_TOTALS_CONFLICTING_TEAM_IDENTITY"):
        _calc(_engine_row(team="Cleveland Guardians",
                          selection="Tampa Bay Rays Over"))


def test_engine_still_refuses_missing_team():
    with pytest.raises(ValueError, match="TEAM_TOTALS_TEAM_REQUIRED"):
        _calc(_engine_row(side="OVER"))


# ---------------------------------------------------------------------------
# 4. Unresolvable intake teams fail closed -- never silently AWAY.
# ---------------------------------------------------------------------------

def test_unresolvable_team_gets_no_team_side_and_engine_refuses():
    rows = automation.parse_team_prop_line(
        "TEAM_PROP: New York Yankees | TEAM_TOTAL | 3.5 | O (+100) | U (-120)",
        GAME, "MLB", NOW)
    assert rows, "parser should still emit the row for downstream refusal"
    assert all("team_side" not in r for r in rows)
    for row in rows:
        row = dict(row, commence_time="2026-10-14T00:00:00Z")
        with pytest.raises(ValueError,
                           match="TEAM_TOTALS_TEAM_OR_SIDE_UNVERIFIED"):
            _calc(row)
