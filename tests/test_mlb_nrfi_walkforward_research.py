"""Synthetic PIT and chronology regressions; no live odds or real outcomes."""
import unittest
from sportsedge.mlb_nrfi_walkforward_research import evaluate_nrfi_walkforward


def game(event, home, away, outcome, day, known_hour="23:00:00", cutoff_hour="18:00:00"):
    return {"event_id": event, "home_team": home, "away_team": away,
            "yrfi": outcome, "scheduled_at_utc": f"2026-04-{day:02d}T19:00:00Z",
            "forecast_cutoff_utc": f"2026-04-{day:02d}T{cutoff_hour}Z",
            "result_known_at_utc": f"2026-04-{day:02d}T{known_hour}Z"}


def evaluate(rows):
    return evaluate_nrfi_walkforward(rows, dataset_scope="OPEN_RESEARCH")


class ChronologicalResearchTests(unittest.TestCase):
    def test_same_cutoff_never_sees_peer_result(self):
        a = game("a", "A", "B", True, 1)
        b = game("b", "C", "D", False, 1)
        forward, reverse = evaluate([a, b]), evaluate([b, a])
        self.assertEqual(forward["rows"], reverse["rows"])
        self.assertEqual([r["training_games_known_before_cutoff"] for r in forward["rows"]], [0, 0])
        self.assertEqual([r["league_yrfi_probability"] for r in forward["rows"]], [0.5, 0.5])

    def test_late_result_cannot_backfill_future_forecast(self):
        a = game("a", "A", "B", True, 1)
        a["result_known_at_utc"] = "2026-04-03T23:00:00Z"
        b = game("b", "A", "C", False, 2)
        c = game("c", "A", "D", False, 4)
        out = {r["event_id"]: r for r in evaluate([a, b, c])["rows"]}
        self.assertEqual(out["b"]["training_games_known_before_cutoff"], 0)
        self.assertEqual(out["c"]["training_games_known_before_cutoff"], 2)

    def test_completed_prior_game_enters_only_later_cutoff(self):
        a = game("a", "A", "B", True, 1)
        b = game("b", "C", "D", False, 2)
        out = {r["event_id"]: r for r in evaluate([b, a])["rows"]}
        self.assertEqual(out["b"]["training_games_known_before_cutoff"], 1)
        self.assertAlmostEqual(out["b"]["league_yrfi_probability"], 2 / 3)

    def test_team_shrinkage_comparator_is_distinct_from_league(self):
        rows = [game(f"a{i}", "A", "B", True, i) for i in range(1, 5)]
        rows += [game(f"z{i}", "C", "D", False, i) for i in range(1, 5)]
        rows.append(game("target", "A", "B", True, 6))
        out = {r["event_id"]: r for r in evaluate(rows)["rows"]}["target"]
        self.assertGreater(out["team_shrunk_yrfi_probability"], out["league_yrfi_probability"])
        self.assertLess(out["team_brier"], out["league_brier"])

    def test_rejects_bad_clock_identity_and_scope(self):
        row = game("a", "A", "B", True, 1)
        for field, bad in (("yrfi", 1), ("forecast_cutoff_utc", "2026-04-01T20:00:00Z"),
                           ("forecast_cutoff_utc", "2026-04-01T18:00:00"),
                           ("result_known_at_utc", "2026-04-01T18:30:00Z"),
                           ("home_team", "B")):
            with self.subTest(field=field, bad=bad):
                invalid = dict(row, **{field: bad})
                with self.assertRaises(ValueError):
                    evaluate([invalid])
        with self.assertRaises(ValueError):
            evaluate([row, row])
        for scope in ("SEALED_HOLDOUT", "PROSPECTIVE", None, ""):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                evaluate_nrfi_walkforward([row], dataset_scope=scope)

    def test_all_authority_flags_remain_false(self):
        out = evaluate([game("a", "A", "B", True, 1)])
        for key in ("source_authenticity_verified", "historical_outcome_authenticity_verified",
                    "market_probability_verified", "prospective_grading_verified",
                    "pricing_authority", "play_authority", "staking_authority"):
            self.assertIs(out[key], False)
        self.assertEqual(out["evaluated_games"], 1)
        self.assertIsNotNone(out["metrics"]["league_log_loss"])


if __name__ == "__main__":
    unittest.main()
