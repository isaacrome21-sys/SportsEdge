"""Tests for sportsedge.live_participation: fail-closed in-game checks.

Network-free: the NFL summary injuries fixture is recorded under
tests/fixtures/live/.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.live_participation import (
    ParticipationError,
    build_football_participation_report,
    check_football_participation,
    mlb_pitcher_participation,
    parse_espn_summary_injuries,
)

FIXTURES = Path(__file__).parent / "fixtures" / "live"
NOW = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 10, 11, 20, 25, tzinfo=timezone.utc)


def load_summary():
    return json.loads(
        (FIXTURES / "nfl_summary_injuries.json").read_text(encoding="utf-8"))


def test_parse_summary_injuries_real_fixture():
    payload = load_summary()
    report = parse_espn_summary_injuries(
        {"injuries": payload["injuries"]},
        home_team="Seattle Seahawks", away_team="San Francisco 49ers",
        checked_at=NOW)
    assert report.source_ok
    assert len(report.signals) > 0
    qbs = [s for s in report.signals if s.position == "QB"]
    assert qbs, "expected QB entries in the recorded fixture"
    sea_qb = [s for s in qbs if s.side == "HOME"]
    assert sea_qb and sea_qb[0].athlete == "Jalen Milroe"
    # Deebo Samuel's Out was timestamped mid-game in the recording.
    deebo = [s for s in report.signals if "Deebo" in s.athlete][0]
    assert deebo.reported_at is not None and deebo.reported_at > KICKOFF


def test_midgame_qb_out_blocks():
    payload = load_summary()
    data = copy.deepcopy(payload)
    # Simulate: Seattle's QB goes Out mid-game.
    for group in data["injuries"]:
        for entry in group["injuries"]:
            if entry["athlete"]["position"] == "QB" and entry["status"] == "Out":
                entry["date"] = (KICKOFF + timedelta(minutes=30)).isoformat()
    report = build_football_participation_report(
        "NFL", "e1", {"injuries": data["injuries"]},
        home_team="Seattle Seahawks", away_team="San Francisco 49ers",
        now=NOW)
    outcome, detail = check_football_participation(report, KICKOFF)
    assert outcome == "LIVE_PARTICIPATION_CHANGE_UNPRICED"
    assert detail["reason"].startswith("LIVE_PARTICIPATION_CHANGE_UNPRICED")
    assert "QB" in detail["reason"]


def test_pregame_qb_out_does_not_block():
    payload = load_summary()
    report = build_football_participation_report(
        "NFL", "e1", {"injuries": payload["injuries"]},
        home_team="Seattle Seahawks", away_team="San Francisco 49ers",
        now=NOW)
    # All QB Outs in the recording predate kickoff (Milroe 19:24Z, Rourke 19:17Z).
    qbs_out = [s for s in report.signals
               if s.position == "QB" and s.is_out]
    assert qbs_out
    assert all(s.reported_at is not None and s.reported_at < KICKOFF
               for s in qbs_out)
    outcome, detail = check_football_participation(report, KICKOFF)
    assert outcome == "PARTICIPATION_OK"
    assert detail["signals_checked"] == len(report.signals)


def test_midgame_non_qb_out_warns_not_blocks():
    # Deebo Samuel (WR) Out at 23:06Z is mid-game but not a QB.
    payload = load_summary()
    report = build_football_participation_report(
        "NFL", "e1", {"injuries": payload["injuries"]},
        home_team="Seattle Seahawks", away_team="San Francisco 49ers",
        now=NOW)
    outcome, detail = check_football_participation(report, KICKOFF)
    assert outcome == "PARTICIPATION_OK"
    assert any("Deebo" in w for w in detail["warnings"])


def test_missing_injuries_section_is_unverified():
    report = build_football_participation_report(
        "CFB", "e1", {"header": {}},  # CFB summaries carry no injuries
        home_team="Home", away_team="Away", now=NOW)
    assert not report.source_ok
    outcome, detail = check_football_participation(report, KICKOFF)
    assert outcome == "LIVE_PARTICIPATION_UNVERIFIED"
    assert detail["reason"].startswith("LIVE_PARTICIPATION_UNVERIFIED")


def test_naive_kickoff_rejected():
    payload = load_summary()
    report = build_football_participation_report(
        "NFL", "e1", {"injuries": payload["injuries"]},
        home_team="H", away_team="A", now=NOW)
    with pytest.raises(ParticipationError):
        check_football_participation(report, datetime(2026, 10, 11, 20, 25))


def test_mlb_pitcher_unchanged_no_warning():
    diag = mlb_pitcher_participation(
        {"id": 1, "fullName": "Ace Starter"}, 1, "Ace Starter", "home", 5)
    assert diag["pitcher_changed"] is False
    assert diag["warning"] is None


def test_mlb_pitcher_early_pull_warns():
    diag = mlb_pitcher_participation(
        {"id": 1, "fullName": "Ace Starter"}, 99, "Reliever Arm", "home", 2)
    assert diag["pitcher_changed"] is True
    assert diag["early_pull_warning"] is True
    assert diag["warning"] is not None
    assert "NOT_WIRED" in diag["pricing_effect"]


def test_mlb_pitcher_late_change_no_early_warning():
    diag = mlb_pitcher_participation(
        {"id": 1, "fullName": "Ace Starter"}, 99, "Reliever Arm", "home", 7)
    assert diag["pitcher_changed"] is True
    assert diag["early_pull_warning"] is False
