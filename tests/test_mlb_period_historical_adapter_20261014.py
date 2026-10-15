"""Synthetic evidence-shape tests; not historical outcome claims."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_period_historical_adapter import (
    load_historical_inning_export, evaluate_historical_export,
)


def _export(n=24):
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return {"schema": "MLB_HISTORICAL_INNING_EXPORT_V1",
            "source_url": "https://example.org/synthetic-only",
            "observed_at": "2026-10-01T00:00:00Z",
            "games": [{"game_id": str(i),
                       "start_time": (start + timedelta(days=i)).isoformat(),
                       "result_available_at": (start + timedelta(days=i, hours=4)).isoformat(),
                       "result_available_at": (start + timedelta(days=i, hours=4)).isoformat(),
             "inning_runs": [i % 2, 1, 0, 0, 0, 0, 0, 0, 0]}
                      for i in range(n)]}


def _write(tmp_path, data):
    p = tmp_path / "history.json"
    p.write_text(json.dumps(data))
    return p


def test_adapter_to_chronological_evaluator(tmp_path):
    report = evaluate_historical_export(_write(tmp_path, _export()), innings=3)
    assert report["forward_predictions"] == 4
    assert report["source_kind"] == "LOCAL_HISTORICAL_EXPORT"
    assert report["play_authorized"] is False


def test_future_relative_to_observation_refused(tmp_path):
    data = _export()
    data["games"][-1]["start_time"] = "2026-10-02T00:00:00Z"
    with pytest.raises(ValueError, match="GAME_AFTER_OBSERVATION"):
        load_historical_inning_export(_write(tmp_path, data))


def test_duplicate_ids_refused(tmp_path):
    data = _export()
    data["games"][-1]["game_id"] = "0"
    with pytest.raises(ValueError, match="DUPLICATE_GAME_ID"):
        load_historical_inning_export(_write(tmp_path, data))


def test_missing_source_refused(tmp_path):
    data = _export()
    data.pop("source_url")
    with pytest.raises(ValueError, match="MISSING_SOURCE_URL"):
        load_historical_inning_export(_write(tmp_path, data))


def test_incomplete_innings_refused(tmp_path):
    data = _export()
    data["games"][-1]["inning_runs"] = [1, 0, 0]
    with pytest.raises(ValueError, match="INCOMPLETE_OR_INVALID_INNINGS"):
        load_historical_inning_export(_write(tmp_path, data))


def test_explicitly_unverified_attestation_refused(tmp_path):
    data = _export()
    data["availability_attestation_authenticity_verified"] = False
    with pytest.raises(ValueError, match="UNVERIFIED_AVAILABILITY_ATTESTATION"):
        evaluate_historical_export(_write(tmp_path, data), innings=3)


def test_self_asserted_authenticity_refused_without_verifier(tmp_path):
    data = _export()
    data["availability_attestation_authenticity_verified"] = True
    with pytest.raises(ValueError, match="UNSUPPORTED_AUTHENTICITY_CLAIM"):
        evaluate_historical_export(_write(tmp_path, data), innings=3)
