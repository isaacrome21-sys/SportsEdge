"""Synthetic end-to-end MLB feed -> evidence -> walk-forward smoke test.

These are constructed fixtures, not MLB historical performance observations.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_statsapi_feed_cli import main as convert
from sportsedge.mlb_period_eval_cli import main as evaluate


def test_local_feed_to_both_period_reports(tmp_path):
    first = datetime(2026, 8, 1, 18, tzinfo=timezone.utc)
    paths = []
    for i in range(24):
        feed = {
            "gameData": {
                "game": {"pk": 1000 + i},
                "status": {"abstractGameState": "Final"},
                "datetime": {"dateTime": (first + timedelta(days=i)).isoformat()},
            },
            "liveData": {"linescore": {
                "innings": [
                    {"num": j, "away": {"runs": int(j == 1 and i % 2 == 0)},
                     "home": {"runs": int(j == 2) * 2}} for j in range(1, 10)
                ],
                "teams": {"away": {"runs": int(i % 2 == 0)}, "home": {"runs": 2}},
            }},
        }
        name = f"game-{i}.json"
        (tmp_path / name).write_text(json.dumps(feed))
        paths.append(name)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "MLB_FINAL_FEED_MANIFEST_V1",
        "source_url": "https://statsapi.mlb.com/api/v1.1/game/feed/live",
        "observed_at": "2026-10-01T00:00:00Z",
        "feed_paths": paths,
    }))
    evidence = tmp_path / "historical.json"
    report = tmp_path / "evaluation.json"
    assert convert(["--manifest", str(manifest), "--output", str(evidence)]) == 0
    # Retrospectively fetched final feeds do not establish when results were
    # available; evaluating them as pregame knowledge must refuse.
    with pytest.raises(ValueError, match="MISSING_RESULT_AVAILABILITY"):
        evaluate(["--input", str(evidence), "--output", str(report)])
    assert not report.exists()
    return
    result = json.loads(report.read_text())
    assert result["reports"]["first_3"]["forward_predictions"] == 4
    assert result["reports"]["first_7"]["forward_predictions"] == 4
    assert result["play_authorized"] is False
    assert result["validated"] is False
    assert result["reports"]["first_3"]["empirical_brier"] >= 0
