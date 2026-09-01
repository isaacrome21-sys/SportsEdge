from datetime import datetime, timezone
import hashlib

import pytest

from sportsedge.sports.nfl.context_autopull import (
    CONTEXT_CLASSES,
    NFLContextError,
    collect_auto_context,
    make_observation,
    manual_context,
    merge_hybrid_context,
    missing_context_classes,
    run_context_mode,
)

NOW = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _provider(name: str, value):
    def inner(game_id, as_of):
        return {
            "status": "AVAILABLE",
            "payload": value,
            "source_name": name,
            "source_uri": f"https://example.test/{name}",
            "source_sha256": _sha(name),
            "observed_at": as_of,
        }
    return inner


def _manual(context_class: str, payload, operator_id="tester"):
    return make_observation(
        context_class=context_class,
        status="AVAILABLE",
        payload=payload,
        source_name="OFFICIAL_TEAM_REPORT",
        source_uri="https://example.test/manual",
        source_sha256=_sha(context_class + str(payload)),
        source_type="MANUAL",
        collection_mode="MANUAL",
        observed_at=NOW,
        pit_as_of=NOW,
        operator_id=operator_id,
        justification="confirmed official update",
    )


def test_auto_attempts_all_context_classes_and_never_promotes():
    bundle = collect_auto_context(
        game_id="2026_01_AWAY_HOME",
        as_of=NOW,
        providers={"weather": _provider("NWS", {"wind_mph": 18})},
    )
    assert bundle["collection_mode"] == "AUTO"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
    assert set(bundle["observations"]) == set(CONTEXT_CLASSES)
    assert bundle["observations"]["weather"]["status"] == "AVAILABLE"
    assert bundle["observations"]["venue_surface"]["status"] == "MISSING_PROVIDER"


def test_manual_requires_operator_and_stays_outside_model():
    with pytest.raises(NFLContextError):
        make_observation(
            context_class="injury_availability",
            status="AVAILABLE",
            payload={"player": "QB1", "status": "OUT"},
            source_name="OFFICIAL_TEAM_REPORT",
            source_uri="https://example.test/injury",
            source_sha256=_sha("injury"),
            source_type="MANUAL",
            collection_mode="MANUAL",
            observed_at=NOW,
            pit_as_of=NOW,
        )
    row = _manual("injury_availability", {"player": "QB1", "status": "OUT"})
    assert row.model_p_eligible is False
    assert row.truth_gate_eligible is False
    assert row.operator_id == "tester"


def test_social_public_betting_and_market_fields_are_rejected():
    bad_payloads = [
        {"social_pick": "HOME"},
        {"public_betting": {"ticket_pct": 80}},
        {"sportsbook": "DK"},
        {"market_probability": 0.60},
    ]
    for payload in bad_payloads:
        with pytest.raises(NFLContextError):
            _manual("weather", payload)


def test_hybrid_manual_override_wins_with_audit_trail():
    auto = collect_auto_context(
        game_id="G1",
        as_of=NOW,
        providers={"weather": _provider("NWS", {"roof_closed": False, "wind_mph": 16})},
    )
    manual = manual_context(
        game_id="G1",
        as_of=NOW,
        observations=[_manual("weather", {"roof_closed": True, "wind_mph": 0})],
    )
    merged = merge_hybrid_context(auto_bundle=auto, manual_bundle=manual)
    weather = merged["observations"]["weather"]
    assert merged["collection_mode"] == "HYBRID"
    assert weather["source_type"] == "MANUAL"
    assert weather["collection_mode"] == "HYBRID"
    assert weather["payload"]["roof_closed"] is True
    assert merged["audit_log"][0]["action"] == "MANUAL_OVERRIDE"
    assert merged["audit_log"][0]["auto_source_sha256"]
    assert merged["audit_log"][0]["manual_source_sha256"]


def test_manual_mode_does_not_invent_missing_context():
    bundle = run_context_mode(
        mode="MANUAL",
        game_id="G2",
        as_of=NOW,
        manual_observations=[_manual("injury_availability", {"status": "QUESTIONABLE"})],
    )
    missing = missing_context_classes(bundle)
    assert "injury_availability" not in missing
    assert "weather" in missing
    assert "defensive_matchup" in missing


def test_hybrid_mode_keeps_auto_base_and_manual_fill():
    bundle = run_context_mode(
        mode="HYBRID",
        game_id="G3",
        as_of=NOW,
        providers={"weather": _provider("NWS", {"wind_mph": 9})},
        manual_observations=[_manual("injury_availability", {"QB1": "ACTIVE"})],
    )
    assert bundle["observations"]["weather"]["source_type"] == "AUTO"
    assert bundle["observations"]["injury_availability"]["source_type"] == "MANUAL"
    assert bundle["audit_log"][0]["action"] == "MANUAL_OVERRIDE"
