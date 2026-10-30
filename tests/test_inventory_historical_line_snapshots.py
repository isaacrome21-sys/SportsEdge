from scripts.inventory_historical_line_snapshots import inventory
import json


def test_inventory_counts_and_flags_invalid_snapshots(tmp_path):
    path = tmp_path / "mlb" / "123.jsonl"
    path.parent.mkdir()
    good = {"sport": "mlb", "captured_at": "2026-10-01T17:00:00Z",
            "content_sha256": "fixture-hash"}
    bad = {"sport": "mlb", "captured_at": "2026-10-01T17:00:00",
           "content_sha256": "fixture-hash"}
    path.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n")
    result = inventory(tmp_path)
    assert result["snapshot_counts"] == {"mlb": 2}
    assert result["invalid_counts"] == {"mlb:INVALID_SNAPSHOT": 1}
    assert result["historical_model_rows_generated"] == 0
    assert result["backtest_status"].startswith("BLOCKED_")
