from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.defensive_context import build_defensive_matchup_provider, build_defensive_split
from sportsedge.sports.nfl.personnel_coaching_context import build_coaching_provider, build_personnel_provider

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def test_defensive_context_allows_explicit_missing_rates_without_zero_fill():
    row = build_defensive_split({"team_id": "CHI", "position_group": "WR", "sample_plays": 50})
    assert row.pressure_rate is None
    assert row.man_rate is None
    assert row.zone_rate is None


def test_defensive_context_rejects_invalid_rates():
    with pytest.raises(NFLContextError):
        build_defensive_split({"team_id": "CHI", "position_group": "WR", "sample_plays": 50, "pressure_rate": 1.2})


def test_defensive_provider_is_pit_objective_and_missing_when_empty():
    out = build_defensive_matchup_provider(
        game_id="g1", offense_team_id="GB", defense_team_id="CHI", as_of=NOW,
        source_uri="https://example.com/pit-defense", source_sha256=SHA, splits=[]
    )
    assert out["status"] == "MISSING"
    assert out["payload"]["sample_total"] == 0


def test_personnel_provider_preserves_unknown_identity_flags():
    out = build_personnel_provider(
        game_id="g1", as_of=NOW, source_uri="https://example.com/personnel", source_sha256=SHA,
        rows=[{"team_id": "GB", "eleven_personnel_rate": .61}],
    )
    team = out["payload"]["teams"][0]
    assert team["projected_ol_starters_known"] is False
    assert team["starting_secondary_known"] is False
    assert team["twelve_personnel_rate"] is None


def test_coaching_provider_rejects_impossible_rate():
    with pytest.raises(NFLContextError):
        build_coaching_provider(
            game_id="g1", as_of=NOW, source_uri="https://example.com/coaching", source_sha256=SHA,
            rows=[{"team_id": "GB", "neutral_pass_rate": 1.5}],
        )


def test_personnel_and_coaching_sources_require_https():
    with pytest.raises(NFLContextError):
        build_personnel_provider(game_id="g1", as_of=NOW, source_uri="file://bad", source_sha256=SHA, rows=[])
    with pytest.raises(NFLContextError):
        build_coaching_provider(game_id="g1", as_of=NOW, source_uri="file://bad", source_sha256=SHA, rows=[])
