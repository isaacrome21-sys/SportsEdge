"""Research-only MLB period evaluation CLI regression tests."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_period_eval_cli import main


def _input(tmp_path):
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    payload = {
        "schema": "MLB_HISTORICAL_INNING_EXPORT_V1",
        "source_url": "https://example.org/synthetic-fixture",
        "observed_at": "2026-10-01T00:00:00Z",
        "games": [
            {"game_id": str(i),
             "start_time": (start + timedelta(days=i)).isoformat(),
             "result_available_at": (start + timedelta(days=i, hours=4)).isoformat(),
             "inning_runs": [i % 2, 1, 0, 0, 0, 0, 0, 0, 0]}
            for i in range(24)
        ],
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload))
    return path


def test_cli_writes_both_period_reports(tmp_path):
    source = _input(tmp_path)
    output = tmp_path / "report.json"
    assert main(["--input", str(source), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert set(report["reports"]) == {"first_3", "first_7"}
    assert report["reports"]["first_3"]["forward_predictions"] == 4
    assert report["reports"]["first_7"]["forward_predictions"] == 4
    assert report["play_authorized"] is False
    assert report["validated"] is False


def test_cli_refuses_overwriting_source(tmp_path):
    source = _input(tmp_path)
    with pytest.raises(ValueError, match="OUTPUT_MUST_NOT_OVERWRITE_INPUT"):
        main(["--input", str(source), "--output", str(source)])


def test_cli_refuses_overwriting_report(tmp_path):
    source = _input(tmp_path)
    output = tmp_path / "report.json"
    output.write_text("existing")
    with pytest.raises(FileExistsError, match="OUTPUT_ALREADY_EXISTS"):
        main(["--input", str(source), "--output", str(output)])
    assert output.read_text() == "existing"
