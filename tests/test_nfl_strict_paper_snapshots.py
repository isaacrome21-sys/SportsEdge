"""Offline regression tests for strict NFL paper-only grading; no live DK/ESPN calls."""
from __future__ import annotations

import json

import pytest

from scripts.grade_nfl_paper_snapshots import (
    NFLPaperGradeError, append_ledger, grade_issue,
)
from sportsedge.line_snapshots import SnapshotError, build_snapshot
from sportsedge.pipeline.picks import make_pick

ISSUE = 9876
GAME_ID = "401900001"
START = "2026-10-25T17:00:00+00:00"
EARLY = "2026-10-25T14:00:00+00:00"
LATE = "2026-10-25T16:30:00+00:00"
AFTER = "2026-10-25T18:00:00+00:00"


def _snap(
    at: str,
    price: int = -110,
    opposite: int = -110,
    *,
    line: float = -3.5,
    market: str = "spread",
    selection: str = "HOME",
    key: str = "Bears spread",
    recorded: str | None = None,
    game: dict | None = None,
    override: dict | None = None,
):
    pick = make_pick(
        sport="NFL", market=market, selection=selection, line=line,
        dk_price=price, opposite_price=opposite, captured_at=at,
        model_p=0.55, engine="offline-test", ladder_status="PAPER",
        game="Chiefs @ Bears", subject="Chicago Bears",
    )
    row = {**pick.to_dict(), "pick": key, "price": price}
    if override:
        row.update(override)
    body = f"Chiefs @ Bears\nCaptured: {at}\nSpread -3.5 -110 -110\n"
    return build_snapshot(
        sport="nfl", issue_number=ISSUE, body=body, title="[NFL LINES] Chiefs @ Bears",
        game=game if game is not None else {
            "game_id": GAME_ID, "away": "Chiefs", "home": "Bears",
        },
        board=[{"raw": "Spread -3.5 -110 -110"}], picks=[row],
        recorded_at=recorded or at,
    )


def _finals(*, away: str = "Kansas City", home: str = "Chicago",
            status: str = "STATUS_FINAL", game_id: str = GAME_ID):
    return {
        "schema": "NFL_FINAL_SCORES_V1", "source": "ESPN_SCOREBOARD",
        "official": False, "games": [{
            "game_id": game_id, "away_team": away, "home_team": home,
            "away_points": 21, "home_points": 28,
            "status": status, "start_ts": START,
        }],
    }


def test_full_game_graded_with_distinct_paired_close():
    rows = grade_issue(ISSUE, [_snap(EARLY), _snap(LATE, -125, +105)], _finals())
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "PAPER_GRADED"
    assert row["result"] == "WIN"
    assert row["profit_units"] == pytest.approx(100 / 110)
    assert row["clv_status"] == "CLV_PAPER_PAIRED"
    assert row["clv_no_vig"] > 0
    assert row["ladder_status"] == "PAPER" and row["verified"] is False


def test_only_one_snapshot_still_grades_but_never_invents_clv():
    row = grade_issue(ISSUE, [_snap(EARLY)], _finals())[0]
    assert row["result"] == "WIN"
    assert row["clv_status"] == "NO_DISTINCT_CLOSE"
    assert row["clv_no_vig"] is None and row["verified"] is False


@pytest.mark.parametrize("capture,recorded,reason", [
    (AFTER, AFTER, "NO_PRESTART_SNAPSHOT"),
    (EARLY, AFTER, "NO_PRESTART_SNAPSHOT"),
])
def test_poststart_and_recorded_after_start_cannot_backfill(capture, recorded, reason):
    row = grade_issue(ISSUE, [_snap(capture, recorded=recorded)], _finals())[0]
    assert row["status"] == "BLOCKED" and row["reason"] == reason
    assert row["result"] is None and row["profit_units"] is None


def test_future_claimed_capture_is_refused_by_store():
    with pytest.raises(SnapshotError, match="CAPTURE_IN_FUTURE"):
        _snap(AFTER, recorded=EARLY)


@pytest.mark.parametrize("bad_field,bad_value", [
    ("price", -110.5),
    ("dk_price", -110.5),
    ("opposite_price", "-110"),
    ("opposite_price", True),
])
def test_noninteger_dk_pairs_block_settlement(bad_field, bad_value):
    row = grade_issue(ISSUE, [_snap(EARLY, override={bad_field: bad_value})], _finals())[0]
    assert row["status"] == "BLOCKED"
    assert row["reason"] in {"NFL_GRADE_ENTRY_PAIR_INCOMPLETE", "NFL_GRADE_ENTRY_PRICE_MISMATCH"}
    assert row["result"] is None


@pytest.mark.parametrize("field,value", [
    ("line", float("nan")),
    ("line", "3.5"),
    ("ev", float("inf")),
    ("model_p", float("nan")),
])
def test_nonfinite_or_ambiguous_model_receipt_blocks(field, value):
    row = grade_issue(ISSUE, [_snap(EARLY, override={field: value})], _finals())[0]
    assert row["status"] == "BLOCKED"
    assert "NONFINITE_OR_NONNUMERIC" in row["reason"]


def test_promoted_entry_receipt_not_included_as_research_settlement():
    row = grade_issue(ISSUE, [_snap(EARLY, override={"ladder_status": "VERIFIED"})], _finals())[0]
    assert row["status"] == "BLOCKED" and row["verified"] is False


def test_real_line_move_keeps_result_but_blocks_price_clv():
    entry = _snap(EARLY)
    close = _snap(LATE, -120, +100, line=-4.5)
    row = grade_issue(ISSUE, [entry, close], _finals())[0]
    assert row["status"] == "PAPER_GRADED" and row["result"] == "WIN"
    assert row["clv_no_vig"] is None
    assert "CLV_LINE_MOVED" in row["clv_status"]


def test_props_without_authenticated_stat_receipt_blocked():
    snap = _snap(EARLY, market="player_prop", selection="OVER", line=52.5, key="Player yards")
    row = grade_issue(ISSUE, [snap], _finals())[0]
    assert row["status"] == "BLOCKED"
    assert row["reason"] == "NFL_GRADE_NO_STAT_OR_PERIOD_RECEIPT"


def test_missing_espn_event_id_is_not_inferred_from_names():
    snap = _snap(EARLY, game={"away": "Chiefs", "home": "Bears"})
    with pytest.raises(NFLPaperGradeError, match="EVENT_ID_MISSING"):
        grade_issue(ISSUE, [snap], _finals())


@pytest.mark.parametrize("finals", [
    _finals(home="Green Bay"),
    _finals(status="STATUS_SCHEDULED"),
    _finals(game_id="401900002"),
    {"schema": "NFL_FINAL_SCORES_V1", "source": "UNVERIFIED", "games": []},
    {"schema": "NFL_FINAL_SCORES_V1", "source": "ESPN_SCOREBOARD", "games": None},
])
def test_wrong_or_unverified_finals_refused(finals):
    with pytest.raises(NFLPaperGradeError):
        grade_issue(ISSUE, [_snap(EARLY)], finals)


def test_same_pick_label_case_whitespace_no_duplicate_settlement():
    early = _snap(EARLY, key="Bears  Spread")
    late = _snap(LATE, -125, +105, key="BEARS SPREAD")
    rows = grade_issue(ISSUE, [early, late], _finals())
    assert len(rows) == 1 and rows[0]["clv_status"] == "CLV_PAPER_PAIRED"


def test_market_identity_change_with_same_label_is_refused():
    early = _snap(EARLY, key="Bears spread")
    late = _snap(LATE, market="moneyline", line=None, key="Bears spread")
    with pytest.raises(NFLPaperGradeError, match="AMBIGUOUS_PICK_KEY"):
        grade_issue(ISSUE, [early, late], _finals())


def test_snapshot_content_change_after_capture_is_refused():
    snap = _snap(EARLY)
    snap["picks"][0]["price"] = -125
    with pytest.raises(NFLPaperGradeError, match="HASH_INVALID"):
        grade_issue(ISSUE, [snap], _finals())


def test_immutable_jsonl_ledger_idempotent_and_conflict_refused(tmp_path):
    path = tmp_path / "nfl_paper.jsonl"
    row = grade_issue(ISSUE, [_snap(EARLY)], _finals())[0]
    assert append_ledger(path, [row]) == 1
    assert append_ledger(path, [row]) == 0
    assert len(path.read_text().splitlines()) == 1
    altered = dict(row, result="LOSS")
    with pytest.raises(NFLPaperGradeError, match="IMMUTABLE_CONFLICT"):
        append_ledger(path, [altered])
    assert json.loads(path.read_text().splitlines()[0]) == row
