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
    {"captured_at": None},
    {"captured_at": "not-a-timestamp"},
    {"captured_at": "2026-11-01T17:52:00"},
])
def test_driver_refuses_missing_partial_naive_or_conflicting_side_clocks(changes):
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
