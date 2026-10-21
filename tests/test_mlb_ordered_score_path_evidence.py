"""Postgame scoring-event path falsification, never MLB pricing."""
from copy import deepcopy

import pytest

from sportsedge.mlb_ordered_score_path_evidence import (
    MLBScoringPathError, postgame_score_path_labels,
)


def halves_through(n=9, *, bottom_final=True):
    halves = []
    for inning in range(1, n+1):
        halves.append(f"{inning}_TOP")
        if inning < n or bottom_final:
            halves.append(f"{inning}_BOTTOM")
    return halves


def event(index, inning, half, team, runs):
    return {
        "game_pk": 314159, "source_event_id": f"evt{index}",
        "scoring_event_index": index, "inning": inning, "half": half,
        "scoring_team_id": team, "official_runs_scored": runs,
    }


def packet():
    return {
        "game_pk": 314159, "away_team_id": 10, "home_team_id": 20,
        "game_start_utc": "2026-10-10T18:00:00Z",
        "game_completed_utc": "2026-10-10T21:00:00Z",
        "observed_at_utc": "2026-10-10T21:10:00Z",
        "final_status": "FINAL",
        "complete_ordered_score_events": True,
        "played_half_ledger_complete": True,
        "source_snapshot_sha256": "a" * 64,
        "played_half_innings": halves_through(bottom_final=False),
        "expected_scoring_event_count": 2,
        "scoring_events": [
            event(1, 1, "TOP", 10, 2),
            event(2, 1, "BOTTOM", 20, 3),
        ],
        "final_away_runs": 2, "final_home_runs": 3,
    }


def extras_packet():
    p = packet()
    p["played_half_innings"] = halves_through(10)
    p["scoring_events"] = [
        event(1, 1, "TOP", 10, 2),
        event(2, 1, "BOTTOM", 20, 2),
        event(3, 9, "TOP", 10, 1),
        event(4, 9, "BOTTOM", 20, 1),
        event(5, 10, "TOP", 10, 1),
        event(6, 10, "BOTTOM", 20, 2),
    ]
    p["expected_scoring_event_count"] = 6
    p["final_away_runs"] = 4
    p["final_home_runs"] = 5
    return p


def test_base_home_does_not_bat_bottom_ninth_and_partial_inning_unresolved():
    r = postgame_score_path_labels(packet())
    assert not r.home_batted_bottom_ninth
    assert not r.extra_innings_played
    assert not r.regulation_tied_after_nine
    assert (r.through_nine_away_runs, r.through_nine_home_runs) == (2, 3)
    assert r.first_run_inning == r.last_run_inning == 1
    assert r.first_scoring_play_runs == 2
    assert r.first_scoring_event_id == "evt1"
    assert r.race_to_runs[3] == "HOME"
    assert r.race_to_runs[4] == "NEITHER"
    assert r.team_with_highest_scoring_inning == "HOME"
    assert r.most_innings_won_team is None
    assert r.most_innings_won_status == "PARTIAL_INNING_SETTLEMENT_UNVERIFIED"
    assert not r.eligible and not r.source_verified_independently
    assert not r.market_settlement_verified
    assert r.market_test == "NO_MARKET_TEST"


def test_real_ninth_tie_and_extra_run_outcomes_not_final_tie():
    r = postgame_score_path_labels(extras_packet())
    assert r.home_batted_bottom_ninth
    assert r.regulation_tied_after_nine
    assert r.extra_innings_played
    assert (r.through_nine_away_runs, r.through_nine_home_runs) == (3, 3)
    assert (r.final_away_runs, r.final_home_runs) == (4, 5)
    assert r.race_to_runs[3] == "AWAY"
    assert r.race_to_runs[4] == "AWAY"
    assert r.race_to_runs[5] == "HOME"
    assert r.first_run_inning == 1
    assert r.last_run_inning == 10


def test_home_already_ahead_after_top_ninth_cannot_hit_bottom_ninth():
    p = packet()
    p["played_half_innings"].append("9_BOTTOM")
    p["scoring_events"].append(event(3, 9, "BOTTOM", 20, 1))
    p["expected_scoring_event_count"] = 3
    p["final_home_runs"] = 4
    with pytest.raises(MLBScoringPathError,
                       match="HOME_LED_AFTER_TOP_NINTH_CANNOT_BAT"):
        postgame_score_path_labels(p)


def test_score_and_regulation_tie_invariants():
    p = packet()
    p["final_away_runs"] = 3
    with pytest.raises(MLBScoringPathError, match="TERMINAL_MLB_SCORE_CANNOT_TIE"):
        postgame_score_path_labels(p)
    p = packet()
    p["final_home_runs"] = 4
    with pytest.raises(MLBScoringPathError,
                       match="SCORING_PLAY_RUNS_DO_NOT_MATCH_FINAL_SCORE"):
        postgame_score_path_labels(p)
    p = extras_packet()
    p["scoring_events"][3]["official_runs_scored"] = 2
    p["final_home_runs"] = 6
    with pytest.raises(MLBScoringPathError,
                       match="EXTRA_INNING_REGULATION_TIE_INVARIANT"):
        postgame_score_path_labels(p)


@pytest.mark.parametrize("change,error", [
    (lambda p: p.update({"complete_ordered_score_events": False}),
     "COMPLETE_OFFICIAL_PATH_NOT_ATTESTED"),
    (lambda p: p.update({"expected_scoring_event_count": 3}),
     "ORDERED_SCORING_EVENT_COUNT_MISMATCH"),
    (lambda p: p.update({"source_snapshot_sha256": "NOT_A_HASH"}),
     "OFFICIAL_SCORE_PATH_SOURCE_SHA_REQUIRED"),
    (lambda p: p["scoring_events"][0].update({"scoring_team_id": 20}),
     "SCORING_TEAM_HALF_IDENTITY_MISMATCH"),
    (lambda p: p["scoring_events"][0].update({"source_event_id": "evt2"}),
     "MISSING_OR_DUPLICATE_SOURCE_SCORING_EVENT"),
    (lambda p: p["scoring_events"][1].update({"scoring_event_index": 3}),
     "OUT_OF_ORDER_SCORING_EVENT_INDEX"),
    (lambda p: p["scoring_events"][0].update({"official_runs_scored": -1}),
     "SCORING_RUN_DELTA_INTEGER_REQUIRED"),
    (lambda p: p["played_half_innings"].remove("9_TOP"),
     "NO_COMPLETED_REGULATION_TOP_NINTH"),
])
def test_missing_or_impossible_scoring_path_refuses(change, error):
    p = packet()
    change(p)
    with pytest.raises(MLBScoringPathError, match=error):
        postgame_score_path_labels(p)


def test_event_path_hash_binds_run_delta_and_half_ledger():
    a = postgame_score_path_labels(packet())
    assert a.source_path_sha256 == postgame_score_path_labels(packet()).source_path_sha256
    p = packet()
    p["scoring_events"][0]["official_runs_scored"] = 1
    p["final_away_runs"] = 1
    assert postgame_score_path_labels(p).source_path_sha256 != a.source_path_sha256


def test_no_score_path_projection_or_undocumented_market_price():
    result = postgame_score_path_labels(packet())
    assert not hasattr(result, "odds_american")
    assert not hasattr(result, "estimate_p")
    assert not hasattr(result, "staking_units")
    from sportsedge.mlb_exotics_gates import exotic_blocked_row
    for market in ("RACE_TO_3_RUNS", "INNING_OF_FIRST_RUN", "GRAND_SLAM"):
        blocked = exotic_blocked_row({"market": market, "selection": "HOME"})
        assert blocked["blocker"] == "NO_ENGINE"
        assert blocked["research_only"] is True
