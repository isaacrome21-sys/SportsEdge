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
    price_verified_team_totals,
    run_nfl_machine_with_team_total_handoff,
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


def _kwargs(*, odds=None):
    artifact = _artifact()
    return {
        "mode": "MANUAL",
        "model_artifact": artifact,
        "expected_model_artifact_sha256": _artifact_hash(artifact),
        "runtime_code_git_sha": CODE_SHA,
        "now": NOW,
        "live_features": _live(),
        "odds_snapshot": odds or _odds(),
    }


class NFLTeamTotalDistributionHandoffTests(unittest.TestCase):
    def test_handoff_captures_exact_canonical_distribution_without_changing_report(self):
        kwargs = _kwargs()
        baseline = run_nfl_machine(**kwargs)
        report, handoffs = run_nfl_machine_with_team_total_handoff(**kwargs)
        self.assertEqual(report.to_dict(), baseline.to_dict())
        self.assertEqual(len(handoffs), 1)
        handoff = handoffs[0]
        self.assertEqual(
            handoff["distribution_sha256"],
            report.results[0].distribution_sha256,
        )
        self.assertTrue(handoff["market_blind_boundary"])
        self.assertFalse(handoff["distribution_recomputed_after_market"])
        self.assertTrue(handoff["path_conservation_verified"])
        self.assertTrue(all(value is False for value in handoff["authority"].values()))

    def test_market_lines_do_not_change_handoff_distribution(self):
        left_report, left = run_nfl_machine_with_team_total_handoff(**_kwargs(odds=_odds(spread=-2.5, total=44.5)))
        right_report, right = run_nfl_machine_with_team_total_handoff(**_kwargs(odds=_odds(spread=-7.5, total=51.5)))
        self.assertEqual(left[0]["distribution_sha256"], right[0]["distribution_sha256"])
        self.assertEqual(left[0]["score_rows"], right[0]["score_rows"])
        self.assertEqual(
            {row.distribution_sha256 for row in left_report.results},
            {row.distribution_sha256 for row in right_report.results},
        )

    def test_mismatched_distribution_hash_fails_closed(self):
        report, handoffs = run_nfl_machine_with_team_total_handoff(**_kwargs())
        bad = deepcopy(handoffs[0])
        bad["distribution_sha256"] = "0" * 64
        with self.assertRaisesRegex(NFLTeamTotalHandoffError, "DISTRIBUTION_HASH_MISMATCH"):
            verify_team_total_distribution_handoff(bad, report=report)

    def test_wrong_model_artifact_identity_fails_closed(self):
        report, handoffs = run_nfl_machine_with_team_total_handoff(**_kwargs())
        bad = deepcopy(handoffs[0])
        bad["model_artifact_sha256"] = "0" * 64
        core = dict(bad)
        core.pop("handoff_sha256")
        bad["handoff_sha256"] = sha256(json.dumps(
            core, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()).hexdigest()
        with self.assertRaisesRegex(NFLTeamTotalHandoffError, "REPORT_IDENTITY_MISMATCH:model_artifact_sha256"):
            verify_team_total_distribution_handoff(bad, report=report)

    def test_wrong_game_identity_fails_closed(self):
        report, handoffs = run_nfl_machine_with_team_total_handoff(**_kwargs())
        bad = deepcopy(handoffs[0])
        bad["game_id"] = "wrong-game"
        core = dict(bad)
        core.pop("handoff_sha256")
        bad["handoff_sha256"] = sha256(json.dumps(
            core, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()).hexdigest()
        with self.assertRaisesRegex(NFLTeamTotalHandoffError, "GAME_ID_MISMATCH"):
            verify_team_total_distribution_handoff(bad, report=report)

    def test_path_conservation_tamper_fails_closed(self):
        report, handoffs = run_nfl_machine_with_team_total_handoff(**_kwargs())
        bad = deepcopy(handoffs[0])
        bad["score_rows"][0]["total"] += 1
        with self.assertRaisesRegex(NFLTeamTotalHandoffError, "TOTAL_CONSERVATION_FAILED"):
            verify_team_total_distribution_handoff(bad, report=report)

    def test_verified_handoff_prices_diagnostic_team_totals_but_stays_blocked(self):
        report, handoffs = run_nfl_machine_with_team_total_handoff(**_kwargs())
        diagnostic = price_verified_team_totals(
            handoff=handoffs[0],
            report=report,
            home_total_line=21.5,
            away_total_line=20.5,
        )
        self.assertEqual(diagnostic["engine_status"], "PRICED_DIAGNOSTIC")
        self.assertEqual(diagnostic["bet_status"], "BLOCKED")
        self.assertFalse(diagnostic["official_eligible"])
        self.assertEqual(
            diagnostic["distribution_sha256"],
            report.results[0].distribution_sha256,
        )
        self.assertTrue(all(value is False for value in diagnostic["authority"].values()))


if __name__ == "__main__":
    unittest.main()
