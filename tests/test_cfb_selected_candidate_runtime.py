from __future__ import annotations

import copy
from datetime import datetime, timezone
import unittest

from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS
from sportsedge.sports.cfb.candidate_registry_v2 import EQUAL, RELIABILITY, BLEND, GAMES
from sportsedge.sports.cfb.joint_model import simulate_cfb_joint_distribution
from sportsedge.sports.cfb.selected_candidate_model import (
    fit_cfb_selected_candidate_score_model,
    simulate_cfb_selected_candidate_distribution,
)
from sportsedge.sports.cfb.selected_candidate_runtime import (
    build_selected_candidate_runtime_adapter,
    run_selected_candidate_cfb_machine,
)
from sportsedge.sports.cfb.source import CFBGame


def metrics(team: str, season: int, through_week: int, source: str, value: float, games: int, asof: str):
    out = {key: float(value + idx * 0.003) for idx, key in enumerate(TEAM_METRIC_KEYS)}
    out.update({
        "team": team,
        "season": season,
        "through_week": through_week,
        "sample_source": source,
        "games_in_sample": games,
        "feature_asof_ts": asof,
        "source_contract": "CFB_AUTO_SOURCE_V1",
    })
    return out


def training_row(i: int, *, week: int = 4):
    games = max(0, week - 1)
    prior_h = metrics("H", 2024, 99, "PRIOR_SEASON_FALLBACK", 0.10 + i * 0.002, 0, "2025-01-01T00:00:00+00:00")
    prior_a = metrics("A", 2024, 99, "PRIOR_SEASON_FALLBACK", 0.16 + i * 0.001, 0, "2025-01-01T00:00:00+00:00")
    current_h = metrics("H", 2025, week - 1, "CURRENT_SEASON_PRIOR_WEEKS", 0.24 + i * 0.004, games, "2025-09-01T00:00:00+00:00")
    current_a = metrics("A", 2025, week - 1, "CURRENT_SEASON_PRIOR_WEEKS", 0.20 + i * 0.003, games, "2025-09-01T00:00:00+00:00")
    row = {
        "season": 2025,
        "week": week,
        "neutral_site": bool(i % 5 == 0),
        "weather": {"game_indoor": True},
        "home_metrics": copy.deepcopy(current_h),
        "away_metrics": copy.deepcopy(current_a),
        "home_prior_metrics": prior_h,
        "away_prior_metrics": prior_a,
        "home_current_metrics": current_h,
        "away_current_metrics": current_a,
        "home_score": 20 + (i * 7) % 31,
        "away_score": 13 + (i * 5) % 28,
    }
    if i == 0:
        row.update({
            "regulation_home_score": 24,
            "regulation_away_score": 24,
            "home_score": 31,
            "away_score": 24,
        })
    return row


def live_fixture():
    asof = "2026-09-18T14:00:00+00:00"
    prior_h = metrics("Home", 2025, 99, "PRIOR_SEASON_FALLBACK", 0.18, 0, "2026-01-01T00:00:00+00:00")
    prior_a = metrics("Away", 2025, 99, "PRIOR_SEASON_FALLBACK", 0.15, 0, "2026-01-01T00:00:00+00:00")
    current_h = metrics("Home", 2026, 5, "CURRENT_SEASON_PRIOR_WEEKS", 0.27, 5, asof)
    current_a = metrics("Away", 2026, 5, "CURRENT_SEASON_PRIOR_WEEKS", 0.22, 5, asof)
    snapshots = {
        "Home": {"prior": prior_h, "current": current_h},
        "Away": {"prior": prior_a, "current": current_a},
    }
    game = CFBGame(
        game_id="g1",
        season=2026,
        week=6,
        start_ts="2026-09-18T23:00:00+00:00",
        home_team="Home",
        away_team="Away",
        neutral_site=False,
        venue="Test Stadium",
        weather={"game_indoor": True},
    )
    return game, snapshots


class TestCFBSelectedCandidateRuntime(unittest.TestCase):
    def setUp(self):
        self.rows = [training_row(i, week=3 + (i % 5)) for i in range(28)]
        self.game, self.snapshots = live_fixture()

    def test_adapter_distribution_matches_direct_selected_simulator_for_all_families(self):
        incoming = {
            "game_id": self.game.game_id,
            "season": self.game.season,
            "week": self.game.week,
            "neutral_site": self.game.neutral_site,
            "weather": dict(self.game.weather or {}),
        }
        for family in (EQUAL, RELIABILITY, BLEND, GAMES):
            with self.subTest(family=family):
                model = fit_cfb_selected_candidate_score_model(self.rows, family=family, ridge_alpha=10.0)
                adapter, _ = build_selected_candidate_runtime_adapter(
                    model=model,
                    games=[self.game],
                    candidate_snapshots=self.snapshots,
                )
                bound = adapter.candidate_rows_by_game_id[self.game.game_id]
                direct = simulate_cfb_selected_candidate_distribution(model, bound, seed=20260918, n_paths=300)
                canonical = simulate_cfb_joint_distribution(adapter, incoming, seed=20260918, n_paths=300)
                self.assertEqual(direct, canonical)
                self.assertEqual(adapter.artifact_sha256(), model.artifact_sha256())

    def test_manual_selected_runtime_uses_canonical_market_machine_and_stays_blocked(self):
        model = fit_cfb_selected_candidate_score_model(self.rows, family=GAMES, ridge_alpha=10.0)
        quotes = [
            {
                "game_id": "g1", "market": "MONEYLINE", "side": "HOME", "line": 0.0,
                "american_odds": -110, "book_key": "draftkings", "sportsbook": "DraftKings",
                "retrieved_at": "2026-09-18T14:59:00+00:00", "offer_id": "home",
            },
            {
                "game_id": "g1", "market": "MONEYLINE", "side": "AWAY", "line": 0.0,
                "american_odds": -110, "book_key": "draftkings", "sportsbook": "DraftKings",
                "retrieved_at": "2026-09-18T14:59:00+00:00", "offer_id": "away",
            },
        ]
        report = run_selected_candidate_cfb_machine(
            mode="MANUAL",
            season=2026,
            week=6,
            model=model,
            now=datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc),
            games=[self.game],
            candidate_snapshots=self.snapshots,
            quotes=quotes,
            fbs_team_rows=[{"school": "Home"}, {"school": "Away"}],
            n_paths=300,
        )
        self.assertEqual(report.mode, "MANUAL")
        self.assertEqual(len(report.results), 2)
        self.assertTrue(all(row.engine_status == "PRICED" for row in report.results))
        self.assertTrue(all(row.bet_status == "BLOCKED" for row in report.results))
        self.assertTrue(all(row.reason == "CFB_PROMOTION_EVIDENCE_REQUIRED" for row in report.results))
        self.assertTrue(all(row.model_artifact_sha256 == model.artifact_sha256() for row in report.results))


if __name__ == "__main__":
    unittest.main()
