"""Tests for the NFL team-totals driver (operational shell around the
frozen runner): sportsedge/nfl_team_total_driver.py.

Covers the driver's own discipline: schedules-record identity (never
the capture's labels), point-in-time history, raw passthrough of
capture values into the pinned runner's refusal set, create-only
outputs, and the settle path's section 7 dispositions. Lane A runs in
its offline manual mode here, exactly as in the runner's own tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sportsedge import nfl_team_total_dist as eng
from sportsedge import nfl_team_total_driver as driver
from sportsedge import nfl_team_total_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_AT = "2026-10-25T10:53:25-05:00"
NOW = "2026-10-25T10:54:25-05:00"
KICKOFF = "2026-10-25T12:00:00-05:00"
CLOSE_AT = "2026-10-25T11:45:00-05:00"

GAMES_HEADER = ("game_id,season,game_type,week,gameday,away_team,"
                "away_score,home_team,home_score")
GAMES_ROWS = [
    "2025_10_BUF_KC,2025,REG,10,2025-11-02,KC,20,BUF,30",
    "2026_03_BUF_MIA,2026,REG,3,2026-09-27,BUF,31,MIA,13",
    "2026_05_DEN_KC,2026,REG,5,2026-10-11,DEN,19,KC,26",
    "2026_06_SF_SEA,2026,REG,6,2026-10-18,SEA,17,SF,24",
    "2026_06_ATL_BUF,2026,REG,6,2026-10-19,BUF,24,ATL,27",
    # The slate game itself, final already in the schedules record:
    # it must never enter the pricing history snapshot.
    "2026_07_SF_ATL,2026,REG,7,2026-10-25,SF,20,ATL,29",
    # A same-day final: also excluded from the snapshot (gameday is
    # not strictly before the slate's gameday).
    "2026_07_PIT_NO,2026,REG,7,2026-10-25,PIT,10,NO,16",
    # A future scheduled game (no scores): excluded everywhere.
    "2026_09_BUF_KC,2026,REG,9,2026-11-01,BUF,,KC,",
]


def _games_csv(tmp_path: Path) -> Path:
    path = tmp_path / "games.csv"
    path.write_text("\n".join([GAMES_HEADER, *GAMES_ROWS]) + "\n")
    return path


def _tt(line, over, under, at=CAPTURE_AT):
    return {"line": line, "over_price": over, "under_price": under,
            "captured_at": at}


def _entry(team_totals=None, **overrides):
    entry = {
        "status": "CAPTURED", "sport": "NFL", "source": "DraftKings",
        "event": "San Francisco 49ers @ Atlanta Falcons",
        "event_id": 34118095, "kickoff_ct": KICKOFF,
        "season": 2026, "week": 8, "game_id": "2026_08_SF_ATL",
        "game_lines": {
            "total": {"line": 50.5, "over_price": -102,
                      "under_price": -118, "captured_at": CAPTURE_AT},
            "team_totals": team_totals if team_totals is not None else {
                "49ers": _tt(26.5, -115, -110),
                "Falcons": _tt(23.5, -130, 100)},
        },
    }
    entry.update(overrides)
    return entry


def _captures(tmp_path: Path, entries) -> Path:
    path = tmp_path / "captures_all.json"
    path.write_text(json.dumps(entries))
    return path


def _price(tmp_path: Path, entries, now=NOW, slate_date="2026-10-25"):
    captures = _captures(tmp_path, entries)
    out_dir = tmp_path / "runs"
    rc = driver.main(["price", "--captures", str(captures),
                      "--games", str(_games_csv(tmp_path)),
                      "--slate-date", slate_date,
                      "--out-dir", str(out_dir),
                      "--now", now, "--lane-a-mode", "manual"])
    return rc, out_dir


def _read_jsonl(path: Path):
    return [json.loads(x) for x in path.read_text().splitlines() if x]


# ---------------------------------------------------------------------------
# Happy path + create-only discipline + point-in-time history
# ---------------------------------------------------------------------------

def test_price_happy_path_records_pins_and_report(tmp_path):
    rc, out_dir = _price(tmp_path, {"34118095": _entry()})
    assert rc == 0
    records = _read_jsonl(out_dir / "entry_2026-10-25.jsonl")
    assert {r["row_id"] for r in records} == \
        {"2026_07_SF_ATL:SF", "2026_07_SF_ATL:ATL"}
    # Identity comes from the schedules record (week 7), not from the
    # capture's own labels (which claimed week 8 / 2026_08_SF_ATL).
    assert {r["week"] for r in records} == {7}
    engine_sha = hashlib.sha256(
        (REPO_ROOT / "sportsedge" / "nfl_team_total_dist.py")
        .read_bytes()).hexdigest()
    for rec in records:
        assert rec["engine_sha256"] == engine_sha
        assert rec["label"] == "PROSPECTIVE"
        assert rec["pick"] in ("PICKED_OVER", "PICKED_UNDER", "PASSED")
        assert rec["lane_a"]["team_mean"] is not None
    report = json.loads((out_dir / "entry_2026-10-25.report.json")
                        .read_text())
    assert report["records_written"] == 2
    assert report["metrics_computed"] is False
    assert report["runner_refusals"] == []
    assert any(n["note"] == "CAPTURE_GAME_ID_DIFFERS_FROM_SCHEDULES"
               for n in report["notes"])
    # History snapshot = finals strictly before 2026-10-25 only: the
    # slate game itself and the same-day final are excluded.
    schedules = driver.load_schedules(_games_csv(tmp_path))
    expected = driver.history_before(schedules, "2026-10-25")
    assert len(expected) == 5
    assert report["history_snapshot_sha256"] == \
        runner.history_snapshot_sha256(expected)
    assert report["history_games"] == 5


def test_price_is_create_only(tmp_path):
    rc, out_dir = _price(tmp_path, {"34118095": _entry()})
    assert rc == 0
    rc2, _ = _price(tmp_path, {"34118095": _entry()})
    assert rc2 == 2  # RECORD_FILE_EXISTS refusal; nothing rewritten
    records = _read_jsonl(out_dir / "entry_2026-10-25.jsonl")
    assert len(records) == 2


# ---------------------------------------------------------------------------
# Raw passthrough: the runner's refusal codes, never driver coercion
# ---------------------------------------------------------------------------

def test_missing_team_total_is_runner_refusal(tmp_path):
    entry = _entry(team_totals={"49ers": _tt(26.5, -115, -110)})
    rc, out_dir = _price(tmp_path, {"34118095": entry})
    assert rc == 0
    records = _read_jsonl(out_dir / "entry_2026-10-25.jsonl")
    assert [r["team"] for r in records] == ["SF"]
    report = json.loads((out_dir / "entry_2026-10-25.report.json")
                        .read_text())
    assert report["runner_refusals"] == [{
        "row_id": "2026_07_SF_ATL:ATL", "game_id": "2026_07_SF_ATL",
        "team": "ATL", "reason": "ENTRY_CAPTURE_MISSING"}]


def test_malformed_values_pass_through_to_runner_codes(tmp_path):
    cases = [
        (_tt(26.5, -115, None), "ENTRY_SINGLE_SIDED"),
        (_tt(26.5, -50, -110), "PRICE_INVALID"),
        (_tt(-3, -115, -110), "LINE_INVALID"),
    ]
    for bad_tt, code in cases:
        sub = tmp_path / code
        sub.mkdir()
        entry = _entry(team_totals={"49ers": bad_tt,
                                    "Falcons": _tt(23.5, -130, 100)})
        rc, out_dir = _price(sub, {"34118095": entry})
        assert rc == 0
        report = json.loads((out_dir / "entry_2026-10-25.report.json")
                            .read_text())
        reasons = {r["team"]: r["reason"]
                   for r in report["runner_refusals"]}
        assert reasons == {"SF": code}
        records = _read_jsonl(out_dir / "entry_2026-10-25.jsonl")
        assert [r["team"] for r in records] == ["ATL"]


def test_stale_quotes_refuse_all_and_write_no_records(tmp_path):
    rc, out_dir = _price(tmp_path, {"34118095": _entry()},
                         now="2026-10-25T11:30:00-05:00")
    assert rc == 3
    assert not (out_dir / "entry_2026-10-25.jsonl").exists()
    report = json.loads((out_dir / "entry_2026-10-25.report.json")
                        .read_text())
    assert report["records_written"] == 0
    assert {r["reason"] for r in report["runner_refusals"]} == \
        {"QUOTE_STALE_180S"}


# ---------------------------------------------------------------------------
# Driver-level refusals and skips
# ---------------------------------------------------------------------------

def test_schedule_match_missing_refuses_game(tmp_path):
    entry = _entry(kickoff_ct="2026-10-27T19:15:00-05:00")
    rc, out_dir = _price(tmp_path, {"34118095": entry})
    assert rc == 3
    # NO_GAMES_BUILT: the refusal is loud (exit 3 + stdout JSON) and
    # nothing is committed — no records, no report.
    assert not out_dir.exists()


def test_build_slate_games_skips_and_notes(tmp_path):
    captures = {
        "1": _entry(),
        "2": _entry(sport="NBA", event_id=2),
        "3": _entry(status="PENDING", event_id=3),
        "4": _entry(kickoff_ct="2026-10-27T19:15:00-05:00", event_id=4),
    }
    schedules = driver.load_schedules(_games_csv(tmp_path))
    games, refusals, notes = driver.build_slate_games(captures, schedules)
    assert [g.game_id for g in games] == ["2026_07_SF_ATL"]
    assert [r["reason"] for r in refusals] == \
        ["DRIVER_SCHEDULE_MATCH_MISSING"]
    assert {n["note"] for n in notes} >= {"NON_NFL_SKIPPED",
                                          "STATUS_PENDING_SKIPPED"}


def test_unresolvable_team_total_key_refuses_game(tmp_path):
    entry = _entry(team_totals={"Dragons": _tt(9.5, -110, -110),
                                "Falcons": _tt(23.5, -130, 100)})
    schedules = driver.load_schedules(_games_csv(tmp_path))
    games, refusals, _ = driver.build_slate_games(
        {"34118095": entry}, schedules)
    assert games == []
    assert [r["reason"] for r in refusals] == \
        ["DRIVER_TEAM_TOTAL_KEY_UNRESOLVED"]


# ---------------------------------------------------------------------------
# Settle: exactly one section 7 disposition per row, real finals
# ---------------------------------------------------------------------------

def _settle(tmp_path: Path, close_entry, extra_args=()):
    rc, out_dir = _price(tmp_path, {"34118095": _entry()})
    assert rc == 0
    captures = _captures(tmp_path, {"34118095": close_entry})
    out_path = tmp_path / "settlement.jsonl"
    rc = driver.main(["settle",
                      "--records",
                      str(out_dir / "entry_2026-10-25.jsonl"),
                      "--captures", str(captures),
                      "--games", str(_games_csv(tmp_path)),
                      "--out", str(out_path), *extra_args])
    assert rc == 0
    return _read_jsonl(out_path)


def test_settle_readable_graded_with_real_finals(tmp_path):
    close = _entry(team_totals={"49ers": _tt(26.5, -115, -110, CLOSE_AT),
                                "Falcons": _tt(23.5, -130, 100, CLOSE_AT)})
    settled = _settle(tmp_path, close)
    assert len(settled) == 2
    assert {row["close_status"] for row in settled} == {"READABLE"}
    by_team = {row["team"]: row for row in settled}
    assert by_team["ATL"]["final_team_points"] == 29
    assert by_team["SF"]["final_team_points"] == 20
    assert all(row["settlement"] == "GRADED" for row in settled)


def test_settle_line_moved_and_no_close_row(tmp_path):
    moved = _entry(team_totals={
        "49ers": _tt(28.5, -110, -110, CLOSE_AT),
        "Falcons": _tt(23.5, -130, 100, CLOSE_AT)})
    settled = _settle(tmp_path, moved)
    by_team = {row["team"]: row for row in settled}
    assert by_team["SF"]["close_status"] == "LINE_MOVED"
    assert by_team["ATL"]["close_status"] == "READABLE"

    other = tmp_path / "noclose"
    other.mkdir()
    absent = _entry(event="Dallas Cowboys @ Philadelphia Eagles",
                    kickoff_ct="2026-10-26T19:15:00-05:00")
    settled2 = _settle(other, absent)
    assert {row["close_status"] for row in settled2} == {"NO_CLOSE_ROW"}


def test_settle_void(tmp_path):
    close = _entry(team_totals={"49ers": _tt(26.5, -115, -110, CLOSE_AT),
                                "Falcons": _tt(23.5, -130, 100, CLOSE_AT)})
    settled = _settle(tmp_path, close,
                      extra_args=("--void-game", "2026_07_SF_ATL"))
    assert {row["settlement"] for row in settled} == {"VOID"}
