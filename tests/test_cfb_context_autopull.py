from datetime import datetime, timezone
import pytest

from sportsedge.sports.cfb.context_autopull import (
    CFBContextError,
    make_observation,
    run_context_mode,
)

PIT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_auto_attempts_context_classes_and_stays_outside_model_p():
    bundle = run_context_mode(mode="AUTO", game_id="1", as_of=PIT, providers={})
    assert bundle["sport"] == "CFB"
    assert bundle["subdivision"] == "FBS"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
    assert bundle["observations"]["injury_availability"]["status"] == "MISSING_PROVIDER"


def test_market_and_public_betting_fields_are_blocked():
    with pytest.raises(CFBContextError, match="prohibited context field"):
        make_observation(
            context_class="game_metadata",
            status="AVAILABLE",
            payload={"ticket_pct": 73},
            source_name="x",
            source_uri="https://example.test",
            source_sha256="a" * 64,
            source_type="AUTO",
            collection_mode="AUTO",
            observed_at=PIT,
            pit_as_of=PIT,
        )


def test_manual_requires_operator_identity():
    with pytest.raises(CFBContextError, match="operator_id"):
        make_observation(
            context_class="injury_availability",
            status="AVAILABLE",
            payload={"player_id": "1", "status": "OUT"},
            source_name="official-team",
            source_uri="https://example.test",
            source_sha256="b" * 64,
            source_type="MANUAL",
            collection_mode="MANUAL",
            observed_at=PIT,
            pit_as_of=PIT,
        )
