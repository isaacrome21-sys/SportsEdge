"""RED tests: each right-rail file must be bound to its game *identity*.

Content binding (score + shots) leaves real collisions (372 groups in the
2023-10..2026-04 collection).  Require identity anchors from the right-rail
itself: gameReports.gameSummary URL encodes season + game number, and
seasonSeries[] must list this game id.  Period structure must also agree:
last byPeriod periodType == boxscore gameOutcome.lastPeriodType and the
period count == boxscore periodDescriptor.number.  Missing => fail closed.
"""
from __future__ import annotations

import pytest

from tests.test_nhl_official_boxscore_live_shape import _build, _live

GS = "https://www.nhl.com/scores/htmlreports/{}/GS{}.HTM"


def test_genuine_fixture_still_builds():
    payload, rail = _live()
    assert _build(payload, rail).game_id == "2026020001"


def test_game_summary_url_for_other_game_rejected():
    payload, rail = _live()
    rail["gameReports"]["gameSummary"] = GS.format("20262027", "020002")
    with pytest.raises(ValueError, match="gameSummary"):
        _build(payload, rail)


def test_game_summary_url_other_season_rejected():
    payload, rail = _live()
    rail["gameReports"]["gameSummary"] = GS.format("20252026", "020001")
    with pytest.raises(ValueError, match="gameSummary"):
        _build(payload, rail)


@pytest.mark.parametrize("bad", [None, "", "https://evil.example/GS020001.HTM", 123])
def test_game_summary_missing_or_malformed_fails_closed(bad):
    payload, rail = _live()
    if bad is None:
        del rail["gameReports"]["gameSummary"]
    else:
        rail["gameReports"]["gameSummary"] = bad
    with pytest.raises(ValueError, match="gameSummary"):
        _build(payload, rail)


def test_game_reports_missing_fails_closed():
    payload, rail = _live()
    del rail["gameReports"]
    with pytest.raises(ValueError, match="gameSummary"):
        _build(payload, rail)


def test_season_series_without_this_game_rejected():
    payload, rail = _live()
    rail["seasonSeries"] = [{"id": 2026020777}]
    with pytest.raises(ValueError, match="seasonSeries"):
        _build(payload, rail)


@pytest.mark.parametrize("bad", ["missing", [], "notalist"])
def test_season_series_missing_fails_closed(bad):
    payload, rail = _live()
    if bad == "missing":
        del rail["seasonSeries"]
    else:
        rail["seasonSeries"] = bad
    with pytest.raises(ValueError, match="seasonSeries"):
        _build(payload, rail)


def test_last_period_type_mismatch_rejected():
    payload, rail = _live()
    payload["gameOutcome"] = {"lastPeriodType": "SO"}
    with pytest.raises(ValueError, match="lastPeriodType"):
        _build(payload, rail)


def test_game_outcome_missing_fails_closed():
    payload, rail = _live()
    del payload["gameOutcome"]
    with pytest.raises(ValueError, match="lastPeriodType"):
        _build(payload, rail)


def test_period_count_mismatch_rejected():
    payload, rail = _live()
    payload["periodDescriptor"]["number"] = 5
    with pytest.raises(ValueError, match="period count"):
        _build(payload, rail)


def test_period_descriptor_missing_fails_closed():
    payload, rail = _live()
    del payload["periodDescriptor"]
    with pytest.raises(ValueError, match="period count"):
        _build(payload, rail)


def test_by_period_last_type_missing_fails_closed():
    payload, rail = _live()
    del rail["linescore"]["byPeriod"][-1]["periodDescriptor"]["periodType"]
    with pytest.raises(ValueError):
        _build(payload, rail)
