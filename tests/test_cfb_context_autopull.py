from datetime import datetime, timezone
import pytest

from sportsedge.sports.cfb.context_autopull import (
    CFBContextError, CONTEXT_CLASSES, collect_auto_context, make_observation,
    merge_hybrid_context, manual_context, missing_context_classes,
)

PIT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def provider(game_id, pit):
    return {"status": "AVAILABLE", "payload": {"game_id": game_id, "fact": 1},
            "source_name": "OBJECTIVE", "source_uri": "https://example.test/objective",
            "source_sha256": SHA, "observed_at": pit}


def test_auto_attempts_every_class_and_stays_ineligible():
    bundle = collect_auto_context(game_id="1", as_of=PIT, providers={"game_metadata": provider})
    assert bundle["sport"] == "CFB"
    assert bundle["subdivision"] == "FBS"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
    assert set(bundle["observations"]) == set(CONTEXT_CLASSES)
    assert bundle["observations"]["game_metadata"]["status"] == "AVAILABLE"
    assert "venue_weather" in missing_context_classes(bundle)


def test_market_and_social_fields_fail_closed():
    for bad in ("sportsbook", "ticket_pct", "market_probability", "social_pick", "odds"):
        with pytest.raises(CFBContextError):
            make_observation(context_class="game_metadata", status="AVAILABLE",
                             payload={bad: 1}, source_name="X", source_uri="https://x.test",
                             source_sha256=SHA, source_type="AUTO", collection_mode="AUTO",
                             observed_at=PIT, pit_as_of=PIT)


def test_hybrid_manual_override_is_audited():
    auto = collect_auto_context(game_id="1", as_of=PIT, providers={"game_metadata": provider})
    manual_row = make_observation(
        context_class="game_metadata", status="AVAILABLE", payload={"verified": True},
        source_name="OPERATOR_OBJECTIVE", source_uri="https://example.test/manual",
        source_sha256="b" * 64, source_type="MANUAL", collection_mode="MANUAL",
        observed_at=PIT, pit_as_of=PIT, operator_id="operator-1", justification="verified correction")
    manual = manual_context(game_id="1", as_of=PIT, observations=[manual_row])
    merged = merge_hybrid_context(auto_bundle=auto, manual_bundle=manual)
    assert merged["collection_mode"] == "HYBRID"
    assert merged["observations"]["game_metadata"]["payload"] == {"verified": True}
    assert merged["audit_log"][0]["auto_source_sha256"] == SHA
    assert merged["audit_log"][0]["manual_source_sha256"] == "b" * 64
