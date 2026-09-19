import json
from pathlib import Path

import pytest

from sportsedge.sports.mlb.historical_event_request_plan import (
    MLBHistoricalRequestPlanError,
    build_historical_event_request_plan,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "mlb_replay_policy_v1.json").read_text(encoding="utf-8"))


def _obs(**overrides):
    row = {
        "observation_key": "obs-1",
        "market": "HITS",
        "quote_ts": "2026-06-05T22:30:00Z",
        "first_pitch_ts": "2026-06-06T00:10:00Z",
        "source_event_id": "provider-game-1",
        "source_home_team_name": "Home",
        "source_away_team_name": "Away",
    }
    row.update(overrides)
    return row


def test_direct_market_generates_exact_decision_and_close_requests():
    plan = build_historical_event_request_plan([_obs()], replay_policy=POLICY)
    assert plan["request_count"] == 2
    assert plan["source_gap_count"] == 0
    assert plan["estimated_max_usage_credits"] == 20
    decision, close = plan["requests"]
    assert decision["kind"] == "DECISION"
    assert decision["requested_at"] == "2026-06-05T22:30:00Z"
    assert decision["provider_market"] == "batter_hits"
    assert decision["event_id"] == "provider-game-1"
    assert "apiKey" not in decision["query_without_api_key"]
    assert close["kind"] == "CLOSE"
    assert close["requested_at"].startswith("2026-06-06T00:09:59.999999")
    assert plan["rules"]["timestamps_rounded"] is False
    assert plan["rules"]["replay_freshness_must_be_judged_from_provider_timestamp"] is True


def test_no_direct_market_is_explicit_gap_not_synthesized():
    plan = build_historical_event_request_plan([_obs(market="NRFI")], replay_policy=POLICY)
    assert plan["request_count"] == 0
    assert plan["source_gap_count"] == 1
    assert plan["source_gaps"][0]["market"] == "NRFI"
    assert "DO_NOT_DERIVE" in plan["source_gaps"][0]["reason"]


def test_nway_market_is_not_acquired_as_v1_promotion_evidence():
    plan = build_historical_event_request_plan([_obs(market="FIRST_HOME_RUN")], replay_policy=POLICY)
    assert plan["request_count"] == 0
    assert plan["source_gaps"] == [{
        "observation_key": "obs-1",
        "market": "FIRST_HOME_RUN",
        "reason": "N_WAY_UNAUTHORIZED_V1",
        "request_generated": False,
    }]


def test_exact_event_identity_can_request_provider_id_resolution():
    row = _obs(source_event_id="")
    plan = build_historical_event_request_plan([row], replay_policy=POLICY)
    assert plan["request_count"] == 2
    assert all(request["identity_resolution_required"] for request in plan["requests"])
    assert plan["requests"][0]["event_identity"] == {
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2026-06-06T00:10:00Z",
    }
    assert plan["estimated_max_usage_credits"] == 22


def test_missing_provider_id_and_event_identity_fails_closed():
    with pytest.raises(MLBHistoricalRequestPlanError, match="PROVIDER_EVENT_ID_OR_EXACT_EVENT_IDENTITY_REQUIRED"):
        build_historical_event_request_plan([
            _obs(source_event_id="", source_home_team_name="", source_away_team_name="")
        ], replay_policy=POLICY)
