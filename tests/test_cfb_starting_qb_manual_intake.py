"""Breakage and normalization tests for manual starting-QB intake."""
from datetime import datetime, timezone

from sportsedge.cfb_starting_qb_manual_intake import normalize_manual_rows, example_rows_for_week


def test_url_required_downgrades_high():
    rows = [
        {
            "team": "Georgia",
            "source": "PRESS_BOX_OR_247_DEPTH_CHART",
            "starter_name": "Carson Beck",
            # missing source_url
            "week": 8,
        }
    ]
    out = normalize_manual_rows(rows)
    assert len(out) == 1
    assert out[0].confidence_label == "MODERATE"
    assert "URL_REQUIRED_FOR_HIGH" in (out[0].notes or "")


def test_empty_and_malformed_are_safe():
    out = normalize_manual_rows([])
    assert out == []
    out2 = normalize_manual_rows([{"not_a_team": True}, None, "bad"])  # type: ignore
    assert all(r.starter_name is None or r.confidence == 0.0 for r in out2)


def test_example_rows_shape():
    rows = example_rows_for_week(8)
    assert len(rows) == 1
    assert rows[0]["source_url"].startswith("https://")
    scored = normalize_manual_rows(rows)
    assert scored[0].confidence_label == "CONFIRMED"
