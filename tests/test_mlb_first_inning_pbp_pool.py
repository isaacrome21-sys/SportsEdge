"""Synthetic strict first-inning PBP K/BTP evidence tests — NO price or grade."""
from copy import deepcopy

import pytest

from sportsedge.mlb_first_inning_pbp_pool import (
    FirstInningPBPPoolError, build_first_inning_pa_pool,
)

TARGET = {
    "game_pk": 99999, "away_team_id": 1,
    "home_team_id": 2, "scheduled_start_utc": "2026-10-20T20:00:00Z",
}
ASOF = "2026-10-19T19:00:00Z"


def _packets(n=10):
    packets = []
    for j in range(1, n + 1):
        pk = 10000 + j
        plays = []
        for k in range(1, 8):
            top = k <= 3
            plays.append({
                "game_pk": pk,
                "inning": 1, "pa_index": k,
                "source_event_id": f"g{pk}-pa{k}",
                "half": "TOP" if top else "BOTTOM",
                "batter_id": 200 + k,
                "pitcher_id": 10 if top else 11,
                "official_strikeout": k in (2, 5),
                "complete_pa": True,
            })
        packets.append({
            "game_pk": pk, "away_team_id": 1, "home_team_id": 2,
            "home_starter_pitcher_id": 10,
            "away_starter_pitcher_id": 11,
            "game_start_utc": f"2026-10-{j:02d}T16:00:00Z",
            "completed_at_utc": f"2026-10-{j:02d}T19:00:00Z",
            "observed_at_utc": f"2026-10-{j:02d}T19:05:00Z",
            "final_status": "FINAL",
            "both_first_inning_halves_complete": True,
            "source_snapshot_sha256": f"{pk:064x}",
            "expected_first_inning_pa_count": 7,
            "plate_appearances": plays,
        })
    return packets


def _build(packets=None, *, kind="PITCHER_K", subject=10, asof=ASOF):
    return build_first_inning_pa_pool(
        TARGET, _packets() if packets is None else packets,
        subject_kind=kind, subject_id=subject, as_of_utc=asof)


def test_starter_strikeouts_are_exact_completed_pa_counts():
    pool = _build()
    assert pool.subject_kind == "PITCHER_K"
    assert pool.subject_id == 10
    assert pool.observed_counts == (1,) * 10
    assert pool.research_only and not pool.eligible
    assert pool.no_engine and pool.market_test == "NO_MARKET_TEST"
    assert pool.distribution_status == "PIT_HISTORY_ONLY_NO_CALIBRATED_DISTRIBUTION"


def test_team_btp_uses_own_half_not_opponent_pitcher_count():
    away = _build(kind="TEAM_BTP", subject=1)
    home = _build(kind="TEAM_BTP", subject=2)
    assert away.observed_counts == (3,) * 10
    assert home.observed_counts == (4,) * 10
    assert away.evidence_sha256 != home.evidence_sha256


def test_subject_absent_from_historical_game_not_turned_to_zero():
    rows = _packets()
    rows[0]["home_starter_pitcher_id"] = 555
    rows[0]["plate_appearances"][0]["pitcher_id"] = 555
    with pytest.raises(FirstInningPBPPoolError):
        _build(rows)


@pytest.mark.parametrize("field,value,error", [
    ("final_status", "Suspended", "FIRST_INNING_PBP_HALVES_INCOMPLETE"),
    ("both_first_inning_halves_complete", False,
     "FIRST_INNING_PBP_HALVES_INCOMPLETE"),
    ("expected_first_inning_pa_count", 9, "FIRST_INNING_PA_CENSUS_INCOMPLETE"),
    ("source_snapshot_sha256", "not-digest", "PBP_SOURCE_HASH_REQUIRED"),
    ("observed_at_utc", "2026-10-21T00:00:00Z",
     "PBP_NOT_STRICTLY_PRIOR_OR_COMPLETE"),
])
def test_incomplete_future_or_unpinned_packet_refused(field, value, error):
    rows = _packets()
    rows[0][field] = value
    with pytest.raises(FirstInningPBPPoolError, match=error):
        _build(rows)


def test_duplicate_gamepk_or_future_target_game_refused():
    rows = _packets()
    rows[1]["game_pk"] = rows[0]["game_pk"]
    with pytest.raises(FirstInningPBPPoolError, match="PBP_DUPLICATE_OR_TARGET_GAMEPK"):
        _build(rows)
    rows = _packets()
    rows[0]["game_pk"] = TARGET["game_pk"]
    with pytest.raises(FirstInningPBPPoolError, match="PBP_DUPLICATE_OR_TARGET_GAMEPK"):
        _build(rows)


@pytest.mark.parametrize("mutation,error", [
    (lambda p: p["plate_appearances"][1].update({"pa_index": 3}),
     "PBP_NONCONTIGUOUS_PA_INDEX"),
    (lambda p: p["plate_appearances"][1].update({"source_event_id": "g10001-pa1"}),
     "MISSING_OR_DUPLICATE_PBP_EVENT"),
    (lambda p: p["plate_appearances"][0].update({"pitcher_id": 12}),
     "HOME_STARTER_FIRST_PA_MISMATCH"),
    (lambda p: p["plate_appearances"][3].update({"pitcher_id": 12}),
     "AWAY_STARTER_FIRST_PA_MISMATCH"),
    (lambda p: p["plate_appearances"][1].update({"official_strikeout": None}),
     "PBP_PA_RESULT_UNVERIFIED"),
    (lambda p: p["plate_appearances"][1].update({"complete_pa": False}),
     "PBP_PA_RESULT_UNVERIFIED"),
    (lambda p: p["plate_appearances"][0].update({"inning": 2}),
     "CROSS_GAME_OR_NONFIRST_PA"),
    (lambda p: p["plate_appearances"][4].update({"half": "TOP"}),
     "PBP_FIRST_INNING_HALF_ORDER"),
])
def test_corrupted_pa_sequence_or_credit_refused(mutation, error):
    rows = _packets()
    mutation(rows[0])
    with pytest.raises(FirstInningPBPPoolError, match=error):
        _build(rows)


def test_asof_strictly_before_target():
    with pytest.raises(FirstInningPBPPoolError, match="AS_OF_NOT_STRICTLY_PREGAME"):
        _build(asof="2026-10-20T20:00:00Z")


def test_minimum_completed_starts_refused():
    with pytest.raises(FirstInningPBPPoolError,
                       match="INSUFFICIENT_COMPLETE_PRIOR_GAME_PACKETS"):
        _build(_packets(n=9))


def test_observed_source_hash_binds_report_without_claiming_authentication():
    a = _build()
    rows = _packets()
    b = _build(list(reversed(rows)))
    assert a.evidence_sha256 == b.evidence_sha256
    altered = deepcopy(rows)
    altered[0]["source_snapshot_sha256"] = "f" * 64
    assert _build(altered).evidence_sha256 != a.evidence_sha256


def test_no_odds_or_model_output_and_canonical_gates_unchanged():
    from sportsedge.mlb_first_inning_deep_set import deep_set_blocked_row
    p = _build()
    assert not hasattr(p, "estimate_p")
    assert not hasattr(p, "odds_american")
    assert not hasattr(p, "staking_units")
    for market in ("FIRST_INNING_K", "FIRST_INNING_BATTERS_TO_PLATE"):
        row = deep_set_blocked_row({"market": market, "selection": "OVER"})
        assert row["blocker"] == "NO_ENGINE"
        assert row["research_only"]
