from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.context_source_adapters import assert_official_injury_uri
from sportsedge.sports.nfl.run_it_context import build_run_it_context
from sportsedge.sports.nfl.stadium_registry import load_stadium_registry


def test_stadium_registry_is_hash_bound_and_covers_all_teams():
    registry = load_stadium_registry()
    assert registry["version"] == "2026.1"
    assert len(registry["registry_sha256"]) == 64
    assert len(registry["stadiums"]) == 30
    assert len(registry["team_to_stadium"]) == 32
    assert registry["stadiums"]["att"].roof_type == "RETRACTABLE"
    assert registry["stadiums"]["allegiant"].roof_type == "FIXED"


def test_injury_adapter_rejects_non_official_host():
    with pytest.raises(NFLContextError):
        assert_official_injury_uri("https://example.com/injuries")
    assert assert_official_injury_uri("https://www.nfl.com/injuries/").startswith("https://")


def test_run_it_auto_attempts_registered_and_unwired_classes_fail_closed():
    as_of = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    bundle = build_run_it_context(
        mode="AUTO",
        game={"game_id": "2026_01_TEST"},
        as_of=as_of,
    )
    assert bundle["collection_mode"] == "AUTO"
    assert bundle["model_p_eligible"] is False
    assert bundle["truth_gate_eligible"] is False
    # Four registered providers have insufficient runtime inputs and therefore
    # return explicit MISSING. Remaining context classes are MISSING_PROVIDER.
    assert bundle["observations"]["weather"]["status"] == "MISSING"
    assert bundle["observations"]["injury_availability"]["status"] == "MISSING"
    assert bundle["observations"]["rest_travel"]["status"] == "MISSING"
    assert bundle["observations"]["workload_leash"]["status"] == "MISSING"
    assert bundle["observations"]["defensive_matchup"]["status"] == "MISSING_PROVIDER"
