"""NFL strict capture -> PAPER grade -> paired CLV tests (test fixtures only)."""
from __future__ import annotations

import json
import pytest

from scripts.grade_nfl_paper_issue import main as grade_cli
from sportsedge.nfl_final_receipts import bind_espn_final, scoreboard_url

from sportsedge.nfl_paper_grader import (
    NflPaperError, capture_nfl_issue, grade_nfl_issue,
)
from sportsedge.line_snapshots import append_snapshot, build_snapshot, load_snapshots

ISSUE = 742
START = "2026-10-24T23:00:00Z"
TITLE = "[NFL LINES] Chiefs @ Ravens"
RAW_FINAL = json.dumps({"events": [{
    "id": "401123456", "date": START,
    "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
    "competitions": [{"competitors": [
        {"homeAway": "away", "team": {"abbreviation": "KC"}, "score": "20"},
        {"homeAway": "home", "team": {"abbreviation": "BAL"}, "score": "24"},
    ]}],
}]}).encode("utf-8")
FINAL = bind_espn_final(raw=RAW_FINAL, source_url=scoreboard_url(START),
                        fetched_at="2026-10-25T03:00:00Z",
                        away="KC", home="BAL", kickoff=START)


def body(captured: str, away: str = "+125", home: str = "-145") -> str:
    return "\n".join([
        "Chiefs @ Ravens", f"Captured: {captured}", f"ML {away} {home}",
        "Spread +3.5 -108 -112", "Total 47.5 -105 -115",
    ])


def engine(selection: str = "HOME"):
    return {"games": [{
        "away": "KC", "home": "BAL", "commence_time": START,
        "markets": [{
            "market": "moneyline", "team": None, "player": None,
            "lean": {"selection": selection, "price_american": -145},
        }],
    }]}


def stage(tmp_path, captured="2026-10-24T21:00:00Z",
          recorded="2026-10-24T21:01:00Z", chosen=True,
          away="+125", home="-145", selection="HOME"):
    return capture_nfl_issue(
        body=body(captured, away, home), title=TITLE,
        issue_number=ISSUE, game_start=START, recorded_at=recorded,
        engine=engine(selection) if chosen else None, root=tmp_path,
    )


def rows(tmp_path):
    return grade_nfl_issue(load_snapshots("nfl", ISSUE, tmp_path), FINAL)


def test_capture_to_paper_grade_and_distinct_close_clv(tmp_path):
    first = stage(tmp_path)
    assert first["picks"][0]["status"] == "PAPER"
    assert first["picks"][0]["price"] == -145
    stage(tmp_path, captured="2026-10-24T22:30:00Z",
          recorded="2026-10-24T22:31:00Z", chosen=False,
          away="+145", home="-165")
    output = rows(tmp_path)
    assert len(output) == 1
    assert output[0]["result"] == "WIN"
    assert output[0]["status"] == output[0]["ladder_status"] == "PAPER"
    assert output[0]["clv_status"] == "CLV_TRACKED_PAPER"
    assert output[0]["clv_prob"] is not None


def test_team_code_engine_selection_matches_home(tmp_path):
    snap = stage(tmp_path, selection="BAL")
    assert snap["picks"][0]["selection"] == "HOME"


def test_no_close_produces_no_clv(tmp_path):
    stage(tmp_path)
    output = rows(tmp_path)[0]
    assert output["clv_status"] == "NO_DISTINCT_CLOSE"
    assert output["clv_prob"] is None


def test_equal_capture_is_not_distinct_close(tmp_path):
    stage(tmp_path)
    stage(tmp_path, captured="2026-10-24T21:00:00Z",
          recorded="2026-10-24T21:02:00Z", chosen=False,
          away="+145", home="-165")
    output = rows(tmp_path)[0]
    assert output["clv_status"] == "NO_DISTINCT_CLOSE"
    assert output["clv_prob"] is None


def test_backfilled_after_kickoff_cannot_close_clv(tmp_path):
    stage(tmp_path)
    with pytest.raises(NflPaperError, match="NOT_RECORDED_PREKICKOFF"):
        stage(tmp_path, captured="2026-10-24T22:50:00Z",
              recorded="2026-10-24T23:05:00Z", chosen=False)
    first = load_snapshots("nfl", ISSUE, tmp_path)[0]
    forged = build_snapshot(
        sport="nfl", issue_number=ISSUE,
        body=body("2026-10-24T22:55:00Z", "+145", "-165"), title=TITLE,
        game=first["game"],
        board=[{"market": "moneyline", "line": None, "team": None,
                "player": None, "price_a": 145, "price_b": -165}],
        picks=[], recorded_at="2026-10-24T23:05:00Z",
    )
    append_snapshot(forged, tmp_path)
    output = rows(tmp_path)[0]
    assert output["clv_status"] == "NO_DISTINCT_CLOSE"
    assert output["clv_prob"] is None


def test_no_receipt_no_grade(tmp_path):
    stage(tmp_path)
    with pytest.raises(NflPaperError, match="FINAL_RECEIPT"):
        grade_nfl_issue(load_snapshots("nfl", ISSUE, tmp_path),
                        {**FINAL, "sha256": ""})


def test_missing_capture_and_postkickoff_refused(tmp_path):
    with pytest.raises(ValueError):
        capture_nfl_issue(
            body="Chiefs @ Ravens\nML +125 -145", title=TITLE,
            issue_number=ISSUE, game_start=START,
            recorded_at="2026-10-24T21:01:00Z", root=tmp_path,
        )
    with pytest.raises(NflPaperError, match="NOT_RECORDED_PREKICKOFF"):
        stage(tmp_path, captured="2026-10-24T23:01:00Z",
              recorded="2026-10-24T23:02:00Z")


def test_unpriced_prop_quote_does_not_invent_model_pick(tmp_path):
    quote = body("2026-10-24T21:00:00Z") + "\nProp \"Lamar Jackson\" PassYards 245.5 -110 -110"
    snap = capture_nfl_issue(
        body=quote, title=TITLE, issue_number=ISSUE,
        game_start=START, recorded_at="2026-10-24T21:01:00Z",
        engine=None, root=tmp_path,
    )
    assert any(r["market"] == "passing_yards" for r in snap["board"])
    assert snap["picks"] == []
    assert rows(tmp_path) == []


def test_cli_capture_to_final_paper_ledger(tmp_path):
    stage(tmp_path)
    stage(tmp_path, captured="2026-10-24T22:30:00Z",
          recorded="2026-10-24T22:31:00Z", chosen=False,
          away="+145", home="-165")
    receipt = tmp_path / "final_receipt.json"
    receipt.write_text(json.dumps(FINAL), encoding="utf-8")
    source = tmp_path / "source.json"
    source.write_bytes(RAW_FINAL)
    output = tmp_path / "paper_grade.json"
    code = grade_cli(["--issue", str(ISSUE), "--final-receipt", str(receipt),
                      "--source-raw", str(source), "--snapshot-root", str(tmp_path), "--output", str(output)])
    assert code == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["status"] == "PAPER"
    assert saved["final_receipt"]["sha256"] == FINAL["sha256"]
    assert saved["rows"][0]["clv_status"] == "CLV_TRACKED_PAPER"


def test_cli_refuses_unverified_final(tmp_path):
    stage(tmp_path)
    receipt = tmp_path / "bad_final.json"
    receipt.write_text(json.dumps({**FINAL, "url": ""}), encoding="utf-8")
    source = tmp_path / "bad_source.json"
    source.write_bytes(RAW_FINAL)
    output = tmp_path / "should_not_exist.json"
    assert grade_cli(["--issue", str(ISSUE), "--final-receipt", str(receipt),
                      "--source-raw", str(source), "--snapshot-root", str(tmp_path), "--output", str(output)]) == 2
    assert not output.exists()


def test_cli_refuses_source_bytes_not_matching_receipt(tmp_path):
    stage(tmp_path)
    receipt = tmp_path / "final.json"
    receipt.write_text(json.dumps(FINAL), encoding="utf-8")
    source = tmp_path / "tampered.json"
    source.write_bytes(RAW_FINAL + b" ")
    out = tmp_path / "should_not_grade.json"
    assert grade_cli(["--issue", str(ISSUE), "--final-receipt", str(receipt),
                      "--source-raw", str(source), "--snapshot-root", str(tmp_path),
                      "--output", str(out)]) == 2
    assert not out.exists()
