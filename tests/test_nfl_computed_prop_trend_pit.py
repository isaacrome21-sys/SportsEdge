from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.computed_prop_trend_pit import (
    StatsAvailabilityProof,
    attest_stat_availability,
    require_complete_pit_provenance,
)
from sportsedge.sports.nfl.computed_prop_trends import (
    ComputedPropTrendError,
    ComputedPropTrendSnapshot,
    GameSettlement,
    SourceProof,
    TrendWindow,
)


CUT = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)
GAME = GameSettlement(
    game_id="2026_01_DAL_PHI",
    kickoff_ts="2026-09-04T00:20:00+00:00",
    season=2026,
    week=1,
    team_id="PHI",
    opponent_team_id="DAL",
    value=5.0,
    outcome="WIN",
)


def _snapshot() -> ComputedPropTrendSnapshot:
    return ComputedPropTrendSnapshot(
        contract="NFL_COMPUTED_PROP_TRENDS_V1",
        as_of=CUT,
        player_id="00-0030000",
        opponent_team_id="DAL",
        market_id="RECEPTIONS",
        side="OVER",
        line=3.5,
        stat_field="receptions",
        windows=(TrendWindow("L5", 1, 0, 0, 1, 1, 100.0),),
        games=(GAME,),
        player_sources=(
            SourceProof(
                season=2026,
                source_uri="https://example.test/player.csv",
                source_sha256="a" * 64,
            ),
        ),
        schedule_source_uri="https://example.test/schedule.csv",
        schedule_source_sha256="b" * 64,
        content_hash="c" * 64,
    )


def _proof(observed_at: datetime = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)) -> StatsAvailabilityProof:
    return StatsAvailabilityProof(
        game_id=GAME.game_id,
        observed_at=observed_at,
        source_uri="https://archive.example.test/player-week-1.csv",
        source_sha256="d" * 64,
        archive_id="nfl-player-stats-2026-w1-v1",
    )


def test_kickoff_before_cutoff_does_not_imply_stat_availability() -> None:
    envelope = attest_stat_availability(_snapshot(), availability_proofs=[])
    assert envelope.pit_provenance_complete is False
    assert envelope.reasons == (f"STAT_AVAILABILITY_UNPROVEN:{GAME.game_id}",)
    assert envelope.model_p_eligible is False
    assert envelope.truth_gate_eligible is False
    assert envelope.promotion_evidence_eligible is False
    assert envelope.decision_effect == "NONE"
    with pytest.raises(ComputedPropTrendError, match="PIT_STATS_AVAILABILITY_INCOMPLETE"):
        require_complete_pit_provenance(envelope)


def test_stat_observed_after_historical_cutoff_is_not_pit_safe() -> None:
    envelope = attest_stat_availability(
        _snapshot(),
        availability_proofs=[_proof(datetime(2026, 9, 8, 15, 1, tzinfo=timezone.utc))],
    )
    assert envelope.pit_provenance_complete is False
    assert envelope.reasons == (f"STAT_NOT_AVAILABLE_AT_CUTOFF:{GAME.game_id}",)


def test_archived_observation_before_cutoff_completes_availability_only() -> None:
    envelope = attest_stat_availability(_snapshot(), availability_proofs=[_proof()])
    assert envelope.pit_provenance_complete is True
    assert envelope.reasons == ()
    require_complete_pit_provenance(envelope)
    # PIT completeness is not model/promotion eligibility.
    assert envelope.model_p_eligible is False
    assert envelope.truth_gate_eligible is False
    assert envelope.promotion_evidence_eligible is False


def test_duplicate_availability_proof_fails_closed() -> None:
    proof = _proof()
    with pytest.raises(ComputedPropTrendError, match="DUPLICATE_STATS_AVAILABILITY_PROOF"):
        attest_stat_availability(_snapshot(), availability_proofs=[proof, proof])


def test_attestation_cutoff_must_equal_snapshot_cutoff() -> None:
    with pytest.raises(ComputedPropTrendError, match="PIT_CUTOFF_SNAPSHOT_MISMATCH"):
        attest_stat_availability(
            _snapshot(),
            availability_proofs=[_proof()],
            as_of=datetime(2026, 9, 8, 14, 59, tzinfo=timezone.utc),
        )
