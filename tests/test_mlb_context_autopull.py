from datetime import datetime, timezone

import pytest

from sportsedge.mlb_context_autopull import (
    CONTEXT_CLASSES,
    MLBContextAutopullError,
    _observation,
    build_autopull_plan,
    missing_context_classes,
)


def test_autopull_plan_covers_all_carty_context_classes_without_social():
    plan = build_autopull_plan()
    assert set(plan) == set(CONTEXT_CLASSES)
    assert all(row["auto_pull"] is True for row in plan.values())
    assert "social_pick" not in plan
    assert "public_betting" not in plan


def test_hybrid_context_observation_is_never_model_p_eligible():
    row = _observation(
        context_class="weather",
        source="NWS_HOURLY",
        observed_at=datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc),
        payload={"temperature_f": 88},
    )
    assert row.lane == "HYBRID_CONTEXT"
    assert row.model_p_eligible is False


def test_social_and_market_context_are_rejected_from_lane():
    now = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
    for prohibited in ("social_pick", "public_betting", "sportsbook_price", "market_probability"):
        with pytest.raises(MLBContextAutopullError):
            _observation(
                context_class=prohibited,
                source="TEST",
                observed_at=now,
                payload={},
            )


def test_missing_context_is_explicit_and_not_inferred():
    bundle = {
        "observations": {
            key: {"status": "AVAILABLE"} for key in CONTEXT_CLASSES
        }
    }
    bundle["observations"]["defense"] = {"status": "MISSING_PROVIDER"}
    bundle["observations"]["umpire"] = {"status": "MISSING"}
    assert missing_context_classes(bundle) == ("umpire", "defense")
