"""MLB issue workflow evidence persistence contract; network-free."""
import json
from pathlib import Path

import pytest

from scripts.record_line_snapshot import verify_snapshot_lag
from sportsedge.line_snapshots import SnapshotError

from scripts.record_line_snapshot import main as record_snapshot
from sportsedge.line_snapshots import load_snapshots
from tests.test_mlb_card_clv import card


BODY = """TB Rays @ MIL Brewers
Captured: 2026-10-24T15:00:00-05:00
ML +100 -120
Total 7.5 -110 -110
"""
TITLE = "[MLB LINES] TB Rays @ MIL Brewers"


def _run(tmp_path, body, *, card_price=-120, bound=None):
    body_file = tmp_path / "body.txt"
    card_file = tmp_path / "card.md"
    body_file.write_text(body, encoding="utf-8")
    card_file.write_text(card(1, [("Moneyline Home", card_price, "ACTIONABLE")]), encoding="utf-8")
    args = [
        "--sport", "mlb", "--issue", "123456",
        "--body-file", str(body_file), "--title", TITLE,
        "--card-md", str(card_file), "--require-card-quote-match",
        "--root", str(tmp_path / "ledger"),
    ]
    if bound is not None:
        input_file = tmp_path / "bound.json"
        input_file.write_text(json.dumps(bound), encoding="utf-8")
        args.extend(["--bound-input-json", str(input_file)])
    return record_snapshot(args)


def test_real_captured_mlb_board_and_pick_append_once(tmp_path):
    assert _run(tmp_path, BODY) == 0
    rows = load_snapshots("mlb", 123456, tmp_path / "ledger")
    assert len(rows) == 1
    first = rows[0]
    assert first["captured_at"] == "2026-10-24T15:00:00-05:00"
    assert first["recorded_at"] != first["captured_at"]
    assert first["picks"][0]["pick"] == "Moneyline Home"
    assert first["picks"][0]["price"] == -120
    assert any(row.get("market_type") == "MONEYLINE" for row in first["board"])
    assert _run(tmp_path, BODY) == 0
    assert len(load_snapshots("mlb", 123456, tmp_path / "ledger")) == 1


def test_new_quote_capture_appends_second_immutable_snapshot(tmp_path):
    assert _run(tmp_path, BODY) == 0
    first = (tmp_path / "ledger/mlb/123456.jsonl").read_text(encoding="utf-8")
    newer = BODY.replace("15:00:00", "16:00:00").replace("ML +100 -120", "ML +105 -125")
    assert _run(tmp_path, newer, card_price=-125) == 0
    text = (tmp_path / "ledger/mlb/123456.jsonl").read_text(encoding="utf-8")
    assert text.startswith(first)
    assert len(load_snapshots("mlb", 123456, tmp_path / "ledger")) == 2


def test_saved_card_price_must_match_exact_captured_pair(tmp_path):
    assert _run(tmp_path, BODY, card_price=-125) == 2
    assert load_snapshots("mlb", 123456, tmp_path / "ledger") == []


def test_missing_captured_never_emits_evidence(tmp_path):
    assert _run(tmp_path, BODY.replace("Captured:", "Timestamp:")) == 2
    assert load_snapshots("mlb", 123456, tmp_path / "ledger") == []


def _bound(*, pk=1, captured="2026-10-24T15:00:00-05:00",
           first_pitch="2099-01-01T00:00:00+00:00"):
    return {"captured_at": captured, "rows": [{
        "game_pk": pk, "book": "draftkings",
        "first_pitch_at": first_pitch,
    }]}


def test_bound_mlb_game_identity_and_clock_are_persisted(tmp_path):
    assert _run(tmp_path, BODY, bound=_bound()) == 0
    row = load_snapshots("mlb", 123456, tmp_path / "ledger")[0]
    assert row["game"]["game_pk"] == 1
    assert row["game"]["first_pitch_at"] == "2099-01-01T00:00:00+00:00"


def test_wrong_card_game_or_schedule_capture_refused(tmp_path):
    assert _run(tmp_path, BODY, bound=_bound(pk=2)) == 2
    assert _run(tmp_path, BODY, bound=_bound(captured="2026-10-24T16:00:00-05:00")) == 2
    assert _run(tmp_path, BODY, bound=_bound(first_pitch="2020-01-01T00:00:00+00:00")) == 2
    assert load_snapshots("mlb", 123456, tmp_path / "ledger") == []


def test_forward_capture_age_bound_rejects_stale_and_future_claims():
    record = {"captured_at": "2026-10-25T16:00:00+00:00",
              "recorded_at": "2026-10-25T16:02:59+00:00"}
    verify_snapshot_lag(record, 180)
    with pytest.raises(SnapshotError, match="STALE"):
        verify_snapshot_lag({**record, "recorded_at": "2026-10-25T16:03:01+00:00"}, 180)
    with pytest.raises(SnapshotError, match="STALE"):
        verify_snapshot_lag({**record, "recorded_at": "2026-10-25T15:59:59+00:00"}, 180)


def test_workflow_writes_only_isolated_review_branch():
    workflow = Path(".github/workflows/mlb-lines-issue.yml").read_text(encoding="utf-8")
    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
    assert "Preserve MLB PAPER snapshot via draft evidence PR" in workflow
    assert "--body-file issue_body.txt" in workflow
    assert "--card-md artifacts/mlb_myspari_ctx/card.md" in workflow
    assert "--require-card-quote-match" in workflow
    assert "--bound-input-json" in workflow
    assert "--max-capture-lag-seconds 180" in workflow
    assert 'branch="automation/mlb-paper-snapshots-issue-$ISSUE"' in workflow
    assert "gh pr create --draft --base main --head" in workflow
    assert 'git push origin "HEAD:refs/heads/$branch"' in workflow
    assert "git push origin main" not in workflow
