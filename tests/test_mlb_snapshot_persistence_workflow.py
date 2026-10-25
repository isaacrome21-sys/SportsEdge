"""MLB issue workflow evidence persistence contract; network-free."""
from pathlib import Path

from scripts.record_line_snapshot import main as record_snapshot
from sportsedge.line_snapshots import load_snapshots
from tests.test_mlb_card_clv import card


BODY = """TB Rays @ MIL Brewers
Captured: 2026-10-24T15:00:00-05:00
ML +100 -120
Total 7.5 -110 -110
"""
TITLE = "[MLB LINES] TB Rays @ MIL Brewers"


def _run(tmp_path, body):
    body_file = tmp_path / "body.txt"
    card_file = tmp_path / "card.md"
    body_file.write_text(body, encoding="utf-8")
    card_file.write_text(card(1, [("Moneyline Home", -120, "ACTIONABLE")]), encoding="utf-8")
    return record_snapshot([
        "--sport", "mlb", "--issue", "123456",
        "--body-file", str(body_file), "--title", TITLE,
        "--card-md", str(card_file),
        "--root", str(tmp_path / "ledger"),
    ])


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
    assert _run(tmp_path, newer) == 0
    text = (tmp_path / "ledger/mlb/123456.jsonl").read_text(encoding="utf-8")
    assert text.startswith(first)
    assert len(load_snapshots("mlb", 123456, tmp_path / "ledger")) == 2


def test_missing_captured_never_emits_evidence(tmp_path):
    assert _run(tmp_path, BODY.replace("Captured:", "Timestamp:")) == 2
    assert load_snapshots("mlb", 123456, tmp_path / "ledger") == []


def test_workflow_writes_only_isolated_review_branch():
    workflow = Path(".github/workflows/mlb-lines-issue.yml").read_text(encoding="utf-8")
    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
    assert "Preserve MLB PAPER snapshot via draft evidence PR" in workflow
    assert "--body-file issue_body.txt" in workflow
    assert "--card-md artifacts/mlb_myspari_ctx/card.md" in workflow
    assert 'branch="automation/mlb-paper-snapshots-issue-$ISSUE"' in workflow
    assert "gh pr create --draft --base main --head" in workflow
    assert 'git push origin "HEAD:refs/heads/$branch"' in workflow
    assert "git push origin main" not in workflow
