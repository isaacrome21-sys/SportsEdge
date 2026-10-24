"""Breakage and normalization tests for manual starting-QB intake."""
from datetime import datetime, timezone

from sportsedge.cfb_starting_qb_manual_intake import normalize_manual_rows, example_rows_for_week


def test_url_required_downgrades_high():
    rows = [
        {
            "team": "Georgia",
            "source": "PRESS_BOX_OR_247_DEPTH_CHART",
            "starter_name": "Carson Beck",
            "week": 8,
        }
    ]
    out = normalize_manual_rows(rows)
    assert len(out) == 1
    assert out[0].confidence_label == "MODERATE"
    assert "URL_REQUIRED_FOR_HIGH" in (out[0].notes or "")
    assert out[0].play_authority is False
    assert out[0].promotion_authority is False


def test_empty_and_malformed_are_safe():
    out = normalize_manual_rows([])
    assert out == []
    out2 = normalize_manual_rows([{"not_a_team": True}, {"team": "X"}])
    assert len(out2) == 2
    assert all(r.play_authority is False for r in out2)


def test_example_rows_shape():
    rows = example_rows_for_week(8)
    assert len(rows) == 1
    assert rows[0]["source_url"].startswith("https://")
    scored = normalize_manual_rows(rows)
    assert scored[0].confidence_label == "CONFIRMED"
    assert scored[0].play_authority is False


def test_authority_cannot_be_smuggled():
    # Even if a future caller tries to set flags, normalize forces them off
    rows = [{
        "team": "Alabama",
        "source": "OFFICIAL_TEAM_OR_CONFERENCE",
        "starter_name": "Test",
        "source_url": "https://example.com",
        "promotion_authority": True,
        "play_authority": True,
    }]
    out = normalize_manual_rows(rows)
    assert out[0].promotion_authority is False
    assert out[0].play_authority is False
