from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, fit_nfl_m2_score_model
from sportsedge.sports.nfl.model_artifact import build_nfl_m2_model_artifact
from sportsedge.sports.nfl.run_machine import run_nfl_machine
from sportsedge.sports.nfl.team_total_handoff import (
    NFLTeamTotalHandoffError,
    build_team_total_distribution_handoff,
    price_verified_team_total_diagnostics,
    verify_team_total_distribution_handoff,
)

CODE_SHA = "a" * 40
TRAINING_SHA = "b" * 64
LIVE_SHA = "c" * 64
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
START = "2026-09-10T13:00:00+00:00"


def _features(*, asof="2026-09-10T11:50:00+00:00", bump=0.0):
    return {
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "qb_id": "qb-1",
        "feature_asof_ts": asof,
        "adj_off_epa": 0.10 + bump,
        "adj_def_epa": -0.02 + bump,
        "pass_epa": 0.14 + bump,
        "rush_epa": 0.03 + bump,
        "pressure_for": 0.31 + bump,
        "pressure_allowed": 0.29 + bump,
        "success_rate": 0.44 + bump,
        "explosive_rate": 0.11 + bump,
        "rest_diff_days": 0.0,
        "travel_miles": 120.0 + bump,
        "timezone_crossings": 0.0,
        "short_week": 0.0,
        "bye_week": 0.0,
        "wind_mph": 6.0 + bump,
        "roof_closed": 0.0,
        "qb_adjustment": 0.02 + bump,
        "prior_efficiency": 0.01 + bump,
        "prior_weight": 0.35,
    }


def _training_row(home, away, season, bump):
    return {
        "season": season,
        "home_features": _features(asof="2025-12-01T12:00:00+00:00", bump=bump),
        "away_features": _features(asof="2025-12-01T12:00:00+00:00", bump=-bump),
        "home_score": home,
        "away_score": away,
    }


def _artifact():
    model = fit_nfl_m2_score_model([
        _training_row(21, 17, 2023, 0.00),
        _training_row(31, 14, 2023, 0.01),
        _training_row(17, 24, 2024, 0.02),
        _training_row(27, 27, 2024, 0.03),
        _training_row(20, 30, 2025, 0.04),
    ])
    return build_nfl_m2_model_artifact(
        model,
        code_git_sha=CODE_SHA,
        source_manifest_sha256=TRAINING_SHA,
    )


def _artifact_hash(artifact):
    raw = json.dumps(
        artifact,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _live():
    return {
        "sport": "nfl",
        "source_manifest_sha256": LIVE_SHA,
        "asof_ts": "2026-09-10T11:58:00+00:00",
        "games": [{
            "game_id": "nfl-2026-01-gb-chi",
            "game_start_ts": START,
            "home_team": "CHI",
            "away_team": "GB",
            "provider_home_team": "Chicago Bears",
            "provider_away_team": "Green Bay Packers",
            "home_features": _features(bump=0.02),
            "away_features": _features(bump=-0.01),
        }],
    }


def _odds(*, spread=-2.5, total=44.5):
    return {
        "source": "fixture",
        "observed_at": "2026-09-10T11:59:00+00:00",
        "events": [{
            "id": "provider-event-1",
            "sport_key": "americanfootball_nfl",
            "commence_time": START,
            "home_team": "Chicago Bears",
            "away_team": "Green Bay Packers",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Chicago Bears", "price": -125},
                        {"name": "Green Bay Packers", "price": 105},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Chicago Bears", "point": spread, "price": -110},
                        {"name": "Green Bay Packers", "point": -spread, "price": -110},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": total, "price": -108},
                        {"name": "Under", "point": total, "price": -112},
                    ]},
                ],
            }],
        }],
    }


def _canonical(artifact, *, spread=-2.5, total=44.5):
    return run_nfl_machine(
        mode="MANUAL",
        model_artifact=artifact,
        expected_model_artifact_sha256=_artifact_hash(artifact),
        runtime_code_git_sha=CODE_SHA,
        now=NOW,
        live_features=_live(),
        odds_snapshot=_odds(spread=spread, total=total),
    )


def _handoff(artifact, live=None):
    return build_team_total_distribution_handoff(
        model_artifact=artifact,
        expected_model_artifact_sha256=_artifact_hash(artifact),
        runtime_code_git_sha=CODE_SHA,
        live_features=_live() if live is None else live,
        now=NOW,
    )


class NFLTeamTotalHandoffTests(unittest.TestCase):
    def test_handoff_hash_exactly_matches_canonical_run_machine(self):
        artifact = _artifact()
        handoff = _handoff(artifact)
        report = _canonical(artifact)
        verified = verify_team_total_distribution_handoff(handoff, report)
        self.assertEqual(verified["verification_status"], "VERIFIED_SAME_DISTRIBUTION")
        self.assertTrue(verified["ready_for_team_total_diagnostics"])
        self.assertFalse(verified["official_eligible"])
        canonical_hashes = {row.distribution_sha256 for row in report.results}
        self.assertEqual(canonical_hashes, {verified["games"][0]["distribution_sha256"]})

    def test_team_total_lines_are_applied_only_after_verification_and_stay_blocked(self):
        artifact = _artifact()
        verified = verify_team_total_distribution_handoff(
            _handoff(artifact), _canonical(artifact)
        )
        diagnostic = price_verified_team_total_diagnostics(
            verified,
            game_id="nfl-2026-01-gb-chi",
            home_total_line=22.5,
            away_total_line=20.5,
        )
        self.assertEqual(
            diagnostic["engine_status"],
            "DIAGNOSTIC_PRICED_FROM_VERIFIED_CANONICAL_DISTRIBUTION",
        )
        self.assertEqual(diagnostic["bet_status"], "BLOCKED")
        self.assertFalse(diagnostic["official_eligible"])
        self.assertEqual(
            diagnostic["reason"],
            "TEAM_TOTAL_MARKET_SPECIFIC_PROMOTION_EVIDENCE_REQUIRED",
        )

    def test_game_market_line_changes_do_not_change_handoff_distribution(self):
        artifact = _artifact()
        handoff = _handoff(artifact)
        left = verify_team_total_distribution_handoff(
            handoff, _canonical(artifact, spread=-2.5, total=44.5)
        )
        right = verify_team_total_distribution_handoff(
            handoff, _canonical(artifact, spread=-7.0, total=51.5)
        )
        self.assertEqual(
            left["games"][0]["distribution_sha256"],
            right["games"][0]["distribution_sha256"],
        )

    def test_tampered_score_rows_fail_hash_verification(self):
        artifact = _artifact()
        handoff = deepcopy(_handoff(artifact))
        handoff["games"][0]["score_rows"][0]["home_score"] += 1
        with self.assertRaisesRegex(
            NFLTeamTotalHandoffError, "DISTRIBUTION_HASH_MISMATCH"
        ):
            verify_team_total_distribution_handoff(handoff, _canonical(artifact))

    def test_wrong_model_artifact_identity_fails_closed(self):
        artifact = _artifact()
        handoff = deepcopy(_handoff(artifact))
        handoff["model_artifact_sha256"] = "d" * 64
        with self.assertRaisesRegex(
            NFLTeamTotalHandoffError, "IDENTITY_MISMATCH:model_artifact_sha256"
        ):
            verify_team_total_distribution_handoff(handoff, _canonical(artifact))

    def test_wrong_game_identity_fails_closed(self):
        artifact = _artifact()
        handoff = deepcopy(_handoff(artifact))
        handoff["games"][0]["game_id"] = "other-game"
        with self.assertRaisesRegex(
            NFLTeamTotalHandoffError, "GAME_SET_MISMATCH"
        ):
            verify_team_total_distribution_handoff(handoff, _canonical(artifact))

    def test_stale_features_cannot_create_handoff(self):
        artifact = _artifact()
        live = _live()
        live["asof_ts"] = "2026-09-10T09:00:00+00:00"
        with self.assertRaisesRegex(
            NFLTeamTotalHandoffError, "NFL_LIVE_FEATURE_SNAPSHOT_STALE"
        ):
            _handoff(artifact, live=live)

    def test_unverified_handoff_cannot_price_team_totals(self):
        artifact = _artifact()
        with self.assertRaisesRegex(
            NFLTeamTotalHandoffError, "HANDOFF_NOT_VERIFIED"
        ):
            price_verified_team_total_diagnostics(
                _handoff(artifact),
                game_id="nfl-2026-01-gb-chi",
                home_total_line=22.5,
                away_total_line=20.5,
            )


if __name__ == "__main__":
    unittest.main()
