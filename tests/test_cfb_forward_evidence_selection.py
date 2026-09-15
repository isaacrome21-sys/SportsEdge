from __future__ import annotations

from sportsedge.sports.cfb.forward_evidence import _nearest


def _row(lead: float, capture_id: str) -> dict[str, object]:
    return {
        "lead_minutes": lead,
        "captured_at": f"2026-09-12T00:{capture_id[-2:]}:00Z",
        "capture_id": capture_id,
    }


def test_market_target_never_selects_after_target() -> None:
    # Symmetric nearest would incorrectly choose T-55 over T-66 for a T-60 target.
    rows = [_row(55.0, "cap55"), _row(66.0, "cap66")]
    selected = _nearest(rows, 60.0, early_only=True)
    assert selected is not None
    assert selected["capture_id"] == "cap66"


def test_market_target_fails_closed_when_only_late_rows_exist() -> None:
    rows = [_row(59.9, "cap59"), _row(55.0, "cap55")]
    assert _nearest(rows, 60.0, early_only=True) is None


def test_weather_can_keep_nearest_prestart_behavior() -> None:
    rows = [_row(12.0, "cap12"), _row(20.0, "cap20")]
    selected = _nearest(rows, 15.0)
    assert selected is not None
    assert selected["capture_id"] == "cap12"
