import pytest

from sportsedge.nfl_run_it_qualification import (
    NflRunItQualificationError,
    qualification_flags_from_snapshot,
)
from sportsedge.nfl_run_it_scoring import qualification_role_score


def _snapshot(**updates):
    row = {
        "captured_at": "2026-09-24T23:00:00Z",
        "kickoff_at": "2026-09-25T00:15:00Z",
        "source_version": "nfl-features-v1",
        "feature_digest": "abc123",
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": True,
        "matchup_supported": True,
        "injury_context_ready": False,
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }
    row.update(updates)
    return row


def test_score_b_flags_are_pit_safe_and_price_independent():
    flags = qualification_flags_from_snapshot(_snapshot())
    assert qualification_role_score(flags) == 88
    assert flags["injury_context_ready"] is False


@pytest.mark.parametrize(
    "key",
    ["price_american", "american_odds", "market_no_vig_p", "edge", "ev_per_dollar", "fair_probability"],
)
def test_market_economics_are_forbidden_from_score_inputs(key):
    with pytest.raises(NflRunItQualificationError, match="MARKET_INPUT_FORBIDDEN"):
        qualification_flags_from_snapshot(_snapshot(**{key: -110}))


def test_post_kickoff_snapshot_is_rejected():
    with pytest.raises(NflRunItQualificationError, match="PIT_LEAKAGE"):
        qualification_flags_from_snapshot(_snapshot(captured_at="2026-09-25T00:15:00Z"))


def test_missing_provenance_fails_closed():
    with pytest.raises(NflRunItQualificationError, match="FEATURE_DIGEST_REQUIRED"):
        qualification_flags_from_snapshot(_snapshot(feature_digest=""))


def test_flags_must_be_explicit_booleans():
    with pytest.raises(NflRunItQualificationError, match="QUALIFICATION_BOOL_REQUIRED"):
        qualification_flags_from_snapshot(_snapshot(role_stable=1))
