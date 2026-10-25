import copy
import json

import pytest

from scripts.grade_nfl_snapshots import grade_snapshot_pick, main
from scripts.capture_nfl_final_scores import SCHEMA
from sportsedge.line_snapshots import build_snapshot, append_snapshot

FINAL = dict(game_id="1", away_team="Chicago Bears", home_team="New England Patriots",
             away_points=24, home_points=17, status="STATUS_FINAL", start_ts="2026-10-25T17:00:00Z")
PICK = dict(pick="OVER 40.5", market="total", selection="OVER", line=40.5, price=-110)


def receipts():
    out = []
    for time, prices, picks in [("15:00:00", "-110 -110", [PICK]), ("16:00:00", "-120 +100", [])]:
        at = "2026-10-25T" + time + "Z"
        out.append(build_snapshot(sport="nfl", issue_number=7,
            body=f"Chicago Bears @ New England Patriots\nCaptured: {at}\nTotal 40.5 {prices}",
            title=None, game={}, board=[], picks=picks, recorded_at=at))
    return out


def test_capture_to_final_cli_end_to_end(tmp_path):
    for snap in receipts():
        append_snapshot(snap, tmp_path / "snapshots")
    finals, output = tmp_path / "finals.json", tmp_path / "grades.json"
    finals.write_text(json.dumps(dict(schema=SCHEMA, games=[FINAL])))
    args = ["--issue", "7", "--game-id", "1", "--finals", str(finals),
            "--snapshot-root", str(tmp_path / "snapshots"), "--output", str(output)]
    assert main(args) == 0
    row = json.loads(output.read_text())["rows"][0]
    assert row["status"] == "GRADED_PAPER" and row["outcome"] == "WIN"
    assert row["units"] == pytest.approx(100 / 110)
    assert row["clv"] > 0 and row["ladder_status"] == "PAPER"
    assert main(args) == 0


@pytest.mark.parametrize("mutation,reason", [
    ("late_record", "NO_DISTINCT_CLOSE"),
    ("future_capture", "NO_DISTINCT_CLOSE"),
    ("same_time", "NO_DISTINCT_CLOSE"),
    ("missing_record", "NO_DISTINCT_CLOSE"),
    ("entry_price", "ENTRY_PRICE_MISMATCH"),
    ("moved_line", "PAIRED_MARKET_MISSING"),
    ("other_game", "GAME_MISMATCH"),
    ("duplicate_capture", "CAPTURED_AT_DUPLICATE"),
])
def test_invalid_evidence_never_counts(mutation, reason):
    snaps = copy.deepcopy(receipts())
    if mutation == "late_record": snaps[1]["recorded_at"] = "2026-10-25T17:01:00Z"
    if mutation == "future_capture": snaps[1]["recorded_at"] = "2026-10-25T15:59:59Z"
    if mutation == "same_time": snaps[1]["captured_at"] = snaps[0]["captured_at"]
    if mutation == "missing_record": snaps[1].pop("recorded_at")
    if mutation == "entry_price": snaps[0]["picks"][0]["price"] = -115
    if mutation == "moved_line": snaps[1]["body"] = snaps[1]["body"].replace("40.5", "41.5")
    if mutation == "other_game": snaps[1]["body"] = snaps[1]["body"].replace("Chicago Bears", "Green Bay Packers")
    if mutation == "duplicate_capture": snaps[1]["body"] += "\nCaptured: 2026-10-25T16:01:00Z"
    row = grade_snapshot_pick(snaps, PICK["pick"], FINAL)
    assert row["status"] == "BLOCKED" and reason in row["reason"]
    assert row["units"] is None and row["clv"] is None


@pytest.mark.parametrize("override", [dict(status="STATUS_IN_PROGRESS"), dict(away_points=float("nan")),
    dict(away_points=True), dict(start_ts=None), dict(start_ts="2026-10-25T17:00:00")])
def test_unusable_final_blocks(override):
    row = grade_snapshot_pick(receipts(), PICK["pick"], {**FINAL, **override})
    assert row["status"] == "BLOCKED" and row["units"] is None
