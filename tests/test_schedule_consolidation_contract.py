from pathlib import Path


def _text(name: str) -> str:
    return (Path(".github/workflows") / name).read_text(encoding="utf-8")


def test_auto_mlb_schedule_and_paid_probe_removal_contract():
    text = _text("auto-mlb.yml")
    assert "cron: '*/15 15-23,0-5 * * *'" in text
    assert "probe_odds_http.py" not in text
    assert "probe_game_odds.py" not in text


def test_primary_archive_is_15_minute_cadence():
    text = _text("archive-mlb-game-odds.yml")
    assert "cron: '7,22,37,52 * * * *'" in text


def test_backup_dispatcher_is_manual_only():
    text = _text("archive-mlb-game-odds-backup-dispatch.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text


def test_failover_has_no_unrelated_workflow_run_trigger():
    text = _text("archive-mlb-game-odds-failover.yml")
    assert "workflow_dispatch:" in text
    assert "workflow_run:" not in text


def test_deadman_is_30_minute_and_dispatches_only_on_stale_signal():
    text = _text("mlb-deadman.yml")
    assert "cron: '5,35 * * * *'" in text
    assert "if: steps.heartbeat.outputs.dispatch_rescue == 'true'" in text
    assert "gh workflow run archive-mlb-game-odds-failover.yml --ref main" in text
