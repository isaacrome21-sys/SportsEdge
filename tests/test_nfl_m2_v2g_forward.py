import copy
import json
from pathlib import Path
import unittest

from sportsedge.sports.nfl.m2_v2g_artifact import artifact_sha256, build_v2g_research_artifact
from sportsedge.sports.nfl.m2_v2g_candidate import NFLM2V2GCandidateModel, NFLV2GTeamState
from sportsedge.sports.nfl.m2_v2g_forward import (
    NFLV2GForwardError,
    build_prospective_prediction,
    validate_prospective_prediction,
)

FREEZE = json.loads(Path("config/research/nfl_v2g_implementation_freeze_2026-09-12.json").read_text())


def _model():
    state = {
        "CHI": NFLV2GTeamState(10, 100, 20, 15, 100, 18, 14),
        "GB": NFLV2GTeamState(10, 102, 24, 12, 101, 22, 13),
    }
    return NFLM2V2GCandidateModel(
        model_id="nfl_m2_scoring_event_v2g_candidate",
        distribution_contract="NFL_M2_V2G_STRUCTURAL_SCORING_EVENT_V1",
        event_contract="NFL_M2_V2G_POSSESSION_EVENT_ROWS_V1",
        train_seasons=(2024, 2025),
        league_drives_per_team_game=10.1,
        league_td_rate=0.21,
        league_fg_rate=0.14,
        team_state=state,
        prior_drives=48.0,
        max_touchdowns=9,
        max_field_goals=9,
    )


def _inputs():
    artifact = build_v2g_research_artifact(
        _model(),
        implementation_freeze=FREEZE,
        training_event_rows_sha256="1" * 64,
        source_manifest_sha256="2" * 64,
    )
    correction = {
        "schema_version": "SPORTSEDGE_NFL_V2G_ARTIFACT_FREEZE_CORRECTION_V1",
        "status": "FROZEN_RESEARCH_ARTIFACT_FOR_PROSPECTIVE_CAPTURE",
        "candidate_id": artifact["candidate_id"],
        "implementation_commit_sha": artifact["implementation_commit_sha"],
        "candidate_source_git_blob_sha1": artifact["candidate_source_git_blob_sha1"],
        "preregistration_commit_sha": artifact["preregistration_commit_sha"],
        "preregistration_timestamp_utc": "2026-09-12T03:47:57Z",
        "source_bound_research_artifact": {"artifact_sha256": artifact_sha256(artifact)},
        "artifact_freeze_may_create_model_p": False,
        "promotion_authority": False,
    }
    return artifact, correction


class NFLV2GForwardTests(unittest.TestCase):
    def test_valid_capture_is_hash_bound_and_non_promotional(self):
        artifact, correction = _inputs()
        row = build_prospective_prediction(
            artifact=artifact,
            implementation_freeze=FREEZE,
            freeze_correction=correction,
            schedule_snapshot_sha256="3" * 64,
            capture_code_git_sha="4" * 40,
            captured_at_utc="2026-09-16T12:00:00Z",
            game_id="2026_02_CHI_GB",
            season=2026,
            week=2,
            kickoff_utc="2026-09-20T17:00:00Z",
            home_team="GB",
            away_team="CHI",
        )
        self.assertEqual(validate_prospective_prediction(row), row["prediction_sha256"])
        self.assertFalse(row["market_prices_consumed"])
        self.assertFalse(row["promotion_authority"])
        self.assertFalse(row["may_create_model_p"])
        self.assertAlmostEqual(
            row["summary"]["home_win_probability"] + row["summary"]["tie_probability"] + row["summary"]["away_win_probability"],
            1.0,
        )

    def test_post_kickoff_capture_is_rejected(self):
        artifact, correction = _inputs()
        with self.assertRaisesRegex(NFLV2GForwardError, "CAPTURE_NOT_PREGAME"):
            build_prospective_prediction(
                artifact=artifact, implementation_freeze=FREEZE, freeze_correction=correction,
                schedule_snapshot_sha256="3" * 64, capture_code_git_sha="4" * 40,
                captured_at_utc="2026-09-20T18:00:00Z", game_id="2026_02_CHI_GB",
                season=2026, week=2, kickoff_utc="2026-09-20T17:00:00Z", home_team="GB", away_team="CHI",
            )

    def test_artifact_identity_drift_is_rejected(self):
        artifact, correction = _inputs()
        correction = copy.deepcopy(correction)
        correction["source_bound_research_artifact"]["artifact_sha256"] = "f" * 64
        with self.assertRaisesRegex(NFLV2GForwardError, "ARTIFACT_SHA_MISMATCH"):
            build_prospective_prediction(
                artifact=artifact, implementation_freeze=FREEZE, freeze_correction=correction,
                schedule_snapshot_sha256="3" * 64, capture_code_git_sha="4" * 40,
                captured_at_utc="2026-09-16T12:00:00Z", game_id="2026_02_CHI_GB",
                season=2026, week=2, kickoff_utc="2026-09-20T17:00:00Z", home_team="GB", away_team="CHI",
            )

    def test_prediction_tampering_is_rejected(self):
        artifact, correction = _inputs()
        row = build_prospective_prediction(
            artifact=artifact, implementation_freeze=FREEZE, freeze_correction=correction,
            schedule_snapshot_sha256="3" * 64, capture_code_git_sha="4" * 40,
            captured_at_utc="2026-09-16T12:00:00Z", game_id="2026_02_CHI_GB",
            season=2026, week=2, kickoff_utc="2026-09-20T17:00:00Z", home_team="GB", away_team="CHI",
        )
        row["summary"]["home_win_probability"] += 0.01
        with self.assertRaisesRegex(NFLV2GForwardError, "PREDICTION_SHA_MISMATCH"):
            validate_prospective_prediction(row)


if __name__ == "__main__":
    unittest.main()
