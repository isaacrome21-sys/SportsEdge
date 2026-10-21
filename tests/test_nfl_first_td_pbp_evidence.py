"""NFL first TD scorer evidence, not an NFL player projection model."""
from copy import deepcopy
import pytest

from sportsedge.nfl_first_td_pbp_evidence import (
    FirstTDEvidenceError, first_td_from_complete_pbp,
)


def packet():
    return {
        "game_id": "NFL-2026-TEST-01",
        "away_team_id": "NFL-CHI", "home_team_id": "NFL-NE",
        "scheduled_start_utc": "2026-10-22T20:00:00Z",
        "completed_at_utc": "2026-10-22T23:30:00Z",
        "observed_at_utc": "2026-10-22T23:45:00Z",
        "source_snapshot_sha256": "a" * 64,
        "final_status": "FINAL", "complete_play_by_play": True,
        "expected_play_count": 4,
        "plays": [
            {"source_game_id": "NFL-2026-TEST-01", "source_event_id": "p1",
             "play_index": 1, "period": 1, "is_touchdown": False},
            {"source_game_id": "NFL-2026-TEST-01", "source_event_id": "p2",
             "play_index": 2, "period": 1, "is_touchdown": True,
             "credited_player_id": "NFL-PLAYER-RECEIVER",
             "credited_team_id": "NFL-CHI",
             "touchdown_type": "RECEIVING"},
            {"source_game_id": "NFL-2026-TEST-01", "source_event_id": "p3",
             "play_index": 3, "period": 2, "is_touchdown": False},
            {"source_game_id": "NFL-2026-TEST-01", "source_event_id": "p4",
             "play_index": 4, "period": 3, "is_touchdown": True,
             "credited_player_id": "NFL-PLAYER-RETURNER",
             "credited_team_id": "NFL-NE",
             "touchdown_type": "INTERCEPTION_RETURN"},
        ],
    }


def test_first_officially_credited_receiver_not_quarterback():
    p = packet()
    p["plays"][1]["passer_player_id"] = "NFL-PLAYER-QB"
    result = first_td_from_complete_pbp(p)
    assert result.credited_player_id == "NFL-PLAYER-RECEIVER"
    assert result.scoring_team_id == "NFL-CHI"
    assert result.first_touchdown_play_index == 2
    assert result.touchdown_type == "RECEIVING"
    assert not result.eligible and result.research_only
    assert not result.complete_official_attribution_verified
    assert result.market_test == "NO_MARKET_TEST"


def test_defense_or_return_td_can_be_first():
    p = packet()
    p["plays"][1].update({
        "credited_player_id": "NFL-PLAYER-DB",
        "credited_team_id": "NFL-NE",
        "touchdown_type": "INTERCEPTION_RETURN",
    })
    first = first_td_from_complete_pbp(p)
    assert first.credited_player_id == "NFL-PLAYER-DB"
    assert first.scoring_team_id == "NFL-NE"


def test_no_td_requires_complete_final_evidence_and_remains_candidate():
    p = packet()
    for play in p["plays"]:
        play["is_touchdown"] = False
    first = first_td_from_complete_pbp(p)
    assert not first.touchdown_found
    assert first.credited_player_id is None
    assert first.status == "POSTGAME_ATTRIBUTION_CANDIDATE_UNVERIFIED"


@pytest.mark.parametrize("mutator,error", [
    (lambda p: p.update({"complete_play_by_play": False}),
     "OFFICIAL_FULL_GAME_PBP_UNCONFIRMED"),
    (lambda p: p.update({"expected_play_count": 3}),
     "FULL_PLAY_SEQUENCE_COUNT_REQUIRED"),
    (lambda p: p["plays"][0].update({"source_game_id": "other"}),
     "CROSS_GAME_OR_NONOBJECT_PLAY"),
    (lambda p: p["plays"][1].update({"play_index": 3}),
     "NONCONTIGUOUS_OR_REORDERED_PLAY"),
    (lambda p: p["plays"][1].update({"source_event_id": "p1"}),
     "DUPLICATE_SOURCE_EVENT"),
    (lambda p: p["plays"][2].update({"period": 0}),
     "PERIOD_ORDER_INVALID"),
    (lambda p: p["plays"][1].update({"credited_player_id": None}),
     "CREDITED_PLAYER_ID_REQUIRED"),
    (lambda p: p["plays"][1].update({"credited_team_id": "NFL-OTHER"}),
     "CREDITED_TEAM_NOT_IN_FIXTURE"),
    (lambda p: p["plays"][1].update({"touchdown_type": "UNKNOWN"}),
     "TOUCHDOWN_TYPE_UNVERIFIED"),
    (lambda p: p["plays"][1].update({"is_touchdown": 1}),
     "TOUCHDOWN_FLAG_REQUIRED"),
    (lambda p: p.update({"observed_at_utc": "2026-10-22T21:00:00Z"}),
     "POSTGAME_OBSERVATION_TIME_INVALID"),
])
def test_hostile_incomplete_or_ambiguous_pbp_refused(mutator, error):
    p = packet()
    mutator(p)
    with pytest.raises(FirstTDEvidenceError, match=error):
        first_td_from_complete_pbp(p)


def test_evidence_hash_changes_when_scoring_credit_changes():
    p = packet()
    original = first_td_from_complete_pbp(p)
    assert original.evidence_sha256 == first_td_from_complete_pbp(p).evidence_sha256
    p["plays"][1]["credited_player_id"] = "NFL-PLAYER-ALT"
    shifted = first_td_from_complete_pbp(p)
    assert original.evidence_sha256 != shifted.evidence_sha256


def test_unverified_attribution_never_contains_price_or_model_p():
    first = first_td_from_complete_pbp(packet())
    assert not hasattr(first, "odds_american")
    assert not hasattr(first, "estimate_p")
    assert not hasattr(first, "ev_per_dollar")
    assert not first.play_authority
    assert not first.staking_authority
