"""Synthetic contract tests for the isolated research-only MLB totals candidate."""
import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.research.mlb_total_offense_defense_challenger import (
    CandidateSpec, MLBTotalCandidateError, predict_total, prequential_backtest,
)


BASE = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)


def sample_games(count=200):
    games = []
    for i in range(count):
        start = BASE + timedelta(days=i)
        if i % 2 == 0:
            away, home, away_runs, home_runs = "A", "B", 8, 2
        else:
            away, home, away_runs, home_runs = "C", "D", 2, 3
        games.append({
            "event_id": f"game-{i}", "game_pk": 700000 + i, "away_id": away, "home_id": home,
            "event_start_ts": start.isoformat(),
            "final_observed_ts": (start + timedelta(hours=4)).isoformat(),
            "status": "FINAL", "away_runs": away_runs, "home_runs": home_runs,
        })
    return games


def index_for(rows):
    """Hash-pinned statsapi-shaped index grounding exactly these rows."""
    from mlb_statsapi_fixture_helpers import pinned_index, raw_game
    docs = []
    for r in rows:
        try:
            start = datetime.fromisoformat(str(r["event_start_ts"]))
        except ValueError:
            continue
        if start.tzinfo is None:
            continue
        docs.append(raw_game(r["game_pk"], r["away_id"], r["home_id"], start,
                             away_runs=r["away_runs"], home_runs=r["home_runs"]))
    return pinned_index(docs)


def target(away="A", home="B", i=200):
    return {"event_id": "target", "away_id": away, "home_id": home,
            "event_start_ts": (BASE + timedelta(days=i)).isoformat()}


class TotalChallengerTests(unittest.TestCase):
    def test_attack_defense_has_total_signal_independent_of_margin_proxy(self):
        history = sample_games()
        high = predict_total(history, target("A", "B"), fixture_index=index_for(history))
        low = predict_total(history, target("C", "D"), fixture_index=index_for(history))
        self.assertGreater(high["candidate_total_mean"], low["candidate_total_mean"])
        self.assertEqual(high["league_only_total_baseline"],
                         low["league_only_total_baseline"])
        self.assertEqual(high["status"], "RESEARCH_ONLY_NOT_VALIDATED")
        self.assertFalse(high["pricing_authorized"])
        self.assertFalse(high["point_in_time_capture_authenticated"])

    def test_future_result_never_leaks_into_pregame_features(self):
        history = sample_games()
        first = predict_total(history, target(), fixture_index=index_for(history))
        future = dict(history[0])
        future.update(event_id="late", game_pk=799001, away_runs=100, home_runs=100,
                      event_start_ts=(BASE + timedelta(days=201)).isoformat(),
                      final_observed_ts=(BASE + timedelta(days=202)).isoformat())
        late_captured = dict(history[0])
        late_captured.update(event_id="old-game-late-ingest", game_pk=799002, away_runs=100,
                             home_runs=100, event_start_ts=(BASE + timedelta(days=100, hours=5)).isoformat(),
                             final_observed_ts=(BASE + timedelta(days=201)).isoformat())
        second = predict_total(history + [future, late_captured], target(),
                               fixture_index=index_for(history + [future, late_captured]))
        self.assertEqual(first["candidate_total_mean"], second["candidate_total_mean"])

    def test_market_input_contamination_refused(self):
        rows = sample_games()
        rows[0]["closing_total"] = 8.5
        with self.assertRaisesRegex(MLBTotalCandidateError, "MARKET_LEAK"):
            predict_total(rows, target(), fixture_index=index_for(sample_games()))

    def test_nonfinal_and_missing_history_refuse(self):
        rows = sample_games()
        rows[0]["status"] = "Scheduled"
        with self.assertRaisesRegex(MLBTotalCandidateError, "ONLY_FINAL"):
            predict_total(rows, target(), fixture_index=index_for(sample_games()))
        with self.assertRaisesRegex(MLBTotalCandidateError, "LEAGUE_HISTORY_INSUFFICIENT"):
            predict_total(sample_games(3), target(), fixture_index=index_for(sample_games(3)))

    def test_bad_identity_and_observation_time_refuse(self):
        rows = sample_games()
        rows.append(dict(rows[0]))
        with self.assertRaisesRegex(MLBTotalCandidateError, "DUPLICATE"):
            predict_total(rows, target(), fixture_index=index_for(sample_games()))
        rows = sample_games()
        rows[0]["final_observed_ts"] = rows[0]["event_start_ts"]
        with self.assertRaisesRegex(MLBTotalCandidateError, "FINAL_OBSERVED"):
            predict_total(rows, target(), fixture_index=index_for(sample_games()))
        rows = sample_games()
        rows[0]["event_start_ts"] = "2026-01-01T18:00:00"
        with self.assertRaisesRegex(MLBTotalCandidateError, "TIMEZONE_REQUIRED"):
            predict_total(rows, target(), fixture_index=index_for(sample_games()))

    def test_walk_forward_is_per_actual_game_without_pseudo_replication(self):
        report = prequential_backtest(
            sample_games(), holdout_from=(BASE + timedelta(days=180)).isoformat(),
            fixture_index=index_for(sample_games()))
        self.assertEqual(report["n_distinct_games"], 20)
        self.assertFalse(report["validated"])
        self.assertEqual(report["paired_market_benchmark"], "MISSING")
        self.assertIn("rmse", report["candidate"])
        self.assertIn("rmse", report["league_only_baseline"])

    def test_frozen_spec_refuses_impossible_parameters(self):
        with self.assertRaisesRegex(MLBTotalCandidateError, "SPEC_INVALID"):
            CandidateSpec(prior_equivalent_games=0)
        with self.assertRaisesRegex(MLBTotalCandidateError, "SPEC_INVALID"):
            CandidateSpec(recent_games=5, min_team_games=10)


if __name__ == "__main__":
    unittest.main()
