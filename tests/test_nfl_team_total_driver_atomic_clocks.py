"""Atomic paired team-total clock integrity at the unfrozen driver boundary.

These are synthetic integrity probes only.  They do not authenticate a DK
capture, start a counted clock, or amend the frozen runner's policy.
"""

from types import SimpleNamespace

import pytest

from sportsedge import nfl_team_total_driver as driver
from sportsedge import nfl_team_total_runner as runner


AT = "2026-11-01T17:52:00Z"
SCHED = SimpleNamespace(game_id="2026_09_SF_ATL",
                        home_team="ATL", away_team="SF")


def _quotes(**changes):
    row = {"line": 26.5, "over_price": -110,
           "under_price": -110, "captured_at": AT}
    row.update(changes)
    entry = {"game_lines": {"team_totals": {"49ers": row}}}
    return driver._team_total_quotes(entry, SCHED)


def test_atomic_quote_preserves_its_single_source_clock():
    quote = _quotes()["SF"]
    assert quote.over_captured_at == AT
    assert quote.under_captured_at == AT
    record = {"row_id": "2026_09_SF_ATL:SF",
              "game_id": "2026_09_SF_ATL", "team": "SF",
              "kickoff": "2026-11-01T18:00:00Z",
              "entry": {"line": 26.5}, "gap": 1.0}
    close = runner.evaluate_close(record, [quote])
    assert close["close_status"] == "READABLE"


def test_equivalent_explicit_side_clocks_are_allowed_without_rewriting():
    quote = _quotes(over_captured_at="2026-11-01T12:52:00-05:00",
                    under_captured_at=AT)["SF"]
    assert quote.over_captured_at == AT
    assert quote.under_captured_at == AT


@pytest.mark.parametrize("changes", [
    # This pair is 300 seconds apart, but the old driver rewrote both
    # to 17:52 and manufactured an eligible 0-second pair.
    {"over_captured_at": "2026-11-01T17:45:00Z",
     "under_captured_at": "2026-11-01T17:50:00Z"},
    {"over_captured_at": AT},
    {"under_captured_at": AT},
    {"over_captured_at": AT, "under_captured_at": "not-a-timestamp"},
    {"over_captured_at": AT, "under_captured_at": "2026-11-01T17:52:00"},
    {"over_captured_at": None, "under_captured_at": AT},
    {"captured_at": None, "over_captured_at": AT, "under_captured_at": AT},
    {"captured_at": "not-a-timestamp",
     "over_captured_at": AT, "under_captured_at": AT},
])
def test_driver_refuses_partial_or_conflicting_explicit_side_clocks(changes):
    with pytest.raises(driver.DriverRefusal) as exc:
        _quotes(**changes)
    assert exc.value.code == "DRIVER_CAPTURE_MALFORMED"


def test_invalid_atomic_pair_is_refused_before_runner_on_entry_and_close():
    row = {"line": 26.5, "over_price": -110, "under_price": -110,
           "captured_at": AT,
           "over_captured_at": "2026-11-01T17:45:00Z",
           "under_captured_at": "2026-11-01T17:50:00Z"}
    entry = {"game_lines": {"team_totals": {"49ers": row}}}
    # Both entry construction and close collection call this shared
    # converter.  Neither can manufacture an eligible paired timestamp.
    with pytest.raises(driver.DriverRefusal) as exc:
        driver._team_total_quotes(entry, SCHED)
    assert exc.value.code == "DRIVER_CAPTURE_MALFORMED"


@pytest.mark.parametrize("bad_clock", [
    None, "not-a-timestamp", "2026-11-01T17:52:00",
])
def test_missing_or_naive_atomic_clock_is_runner_refused_per_row(bad_clock):
    # Without explicit side clocks the driver must preserve per-team
    # isolation: the pinned runner refuses this team's malformed close.
    quote = _quotes(captured_at=bad_clock)["SF"]
    assert quote.over_captured_at == bad_clock
    assert quote.under_captured_at == bad_clock
    record = {"row_id": "2026_09_SF_ATL:SF",
              "game_id": "2026_09_SF_ATL", "team": "SF",
              "kickoff": "2026-11-01T18:00:00Z",
              "entry": {"line": 26.5}, "gap": 1.0}
    assert runner.evaluate_close(record, [quote])["close_status"] == (
        "CLOSE_NOT_PREKICKOFF")


def test_settle_isolates_missing_atomic_clock_to_affected_team(tmp_path):
    # Regression for Claude's exact-head CHANGES-NEEDED review: the old
    # patch raised DriverRefusal while converting ATL and aborted both
    # settlements.  A valid SF close must survive the malformed ATL clock.
    import json

    game_id = "2026_09_SF_ATL"
    kickoff = "2026-11-01T18:00:00Z"
    games = tmp_path / "games.csv"
    games.write_text(
        "game_id,season,game_type,week,gameday,away_team,away_score,"
        "home_team,home_score\n"
        "2026_09_SF_ATL,2026,REG,9,2026-11-01,SF,20,ATL,29\n")
    captures = tmp_path / "captures.json"
    captures.write_text(json.dumps({"1": {
        "sport": "NFL",
        "event": "San Francisco 49ers @ Atlanta Falcons",
        "kickoff_ct": kickoff,
        "game_lines": {"team_totals": {
            "49ers": {"line": 26.5, "over_price": -110,
                      "under_price": -110, "captured_at": AT},
            "Falcons": {"line": 23.5, "over_price": -110,
                        "under_price": -110},
        }},
    }}))
    records = tmp_path / "records.jsonl"
    records.write_text("".join(json.dumps({
        "row_id": f"{game_id}:{team}", "game_id": game_id,
        "team": team, "kickoff": kickoff,
        "entry": {"line": line}, "gap": 1.0,
    }) + "\n" for team, line in (("SF", 26.5), ("ATL", 23.5))))
    output = tmp_path / "settled.jsonl"
    args = SimpleNamespace(records=str(records), captures=str(captures),
                           games=str(games), out=str(output), void_game=None)
    assert driver.cmd_settle(args) == 0
    settled = {row["team"]: row for row in
               (json.loads(line) for line in output.read_text().splitlines())}
    assert settled["SF"]["close_status"] == "READABLE"
    assert settled["ATL"]["close_status"] == "CLOSE_NOT_PREKICKOFF"
    assert all(row["settlement"] == "GRADED" for row in settled.values())
