from pathlib import Path


def _text(name: str) -> str:
    return (Path(".github/workflows") / name).read_text(encoding="utf-8")


def test_auto_mlb_is_parked_and_paid_probe_removal_contract():
    text = _text("auto-mlb.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "if: github.event_name == 'workflow_dispatch'" in text
    assert "probe_odds_http.py" not in text
    assert "probe_game_odds.py" not in text


def test_primary_archive_is_manual_only_while_mlb_parked():
    text = _text("archive-mlb-game-odds.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text


def test_backup_dispatcher_is_manual_only():
    text = _text("archive-mlb-game-odds-backup-dispatch.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text


def test_failover_has_no_unrelated_workflow_run_trigger():
    text = _text("archive-mlb-game-odds-failover.yml")
    assert "workflow_dispatch:" in text
    assert "workflow_run:" not in text


def test_deadman_is_manual_only_while_mlb_parked():
    text = _text("mlb-deadman.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "if: steps.heartbeat.outputs.dispatch_rescue == 'true'" in text
    assert "gh workflow run archive-mlb-game-odds-failover.yml --ref main" in text
