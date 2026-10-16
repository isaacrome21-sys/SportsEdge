"""V2 registration must expose the existing failed verdict, never eligibility."""
import pytest

from sportsedge.canonical_coverage import (
    MARKET_RESOLUTIONS, blocked_row_for, coverage_summary, resolve_market,
)
from sportsedge.mlb_family_registry_v2 import settle_pitcher_pitches


@pytest.mark.parametrize("line", [-1, -0.5, 10 ** 1000, -(10 ** 1000)])
@pytest.mark.parametrize("side", ["OVER", "UNDER"])
def test_outside_pitch_count_line_domain_refuses_by_name(line, side):
    with pytest.raises(ValueError, match="^PITCHER_PITCHES_LINE_INVALID$"):
        settle_pitcher_pitches({"numberOfPitches": 90}, line, side)


@pytest.mark.parametrize("side", ["OVER", "UNDER"])
def test_zero_line_retains_integer_push(side):
    assert settle_pitcher_pitches({"numberOfPitches": 0}, 0, side) == "PUSH"


def test_canonical_lookup_names_m29_failure_without_mutating_v1_census():
    resolution = resolve_market("MLB", "PITCHER_PITCHES")
    assert resolution["validation_status"] == "DOES_NOT_BEAT_BASELINE"
    assert resolution["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert resolution["registry_schema"] == "MLB_FAMILY_REGISTRY_V2"
    assert resolution["evidence_group"] == "PITCHER_PITCH_COUNT_V2"
    assert resolution["research_only"] is True
    assert resolution["promotable"] is False
    assert resolution["state"] == "PRICED_PATH"  # existing #2276 research route
    assert ("MLB", "PITCHER_PITCHES") not in MARKET_RESOLUTIONS
    assert coverage_summary()["markets_total"] == 89
    assert blocked_row_for("MLB", "PITCHER_PITCHES", {}) is None
    assert resolve_market("NFL", "PITCHER_PITCHES") is None
    # Callers cannot overwrite the authoritative verdict through a returned dict.
    resolution["validation_status"] = "VALIDATED"
    assert resolve_market("MLB", "PITCHER_PITCHES")["validation_status"] == "DOES_NOT_BEAT_BASELINE"
