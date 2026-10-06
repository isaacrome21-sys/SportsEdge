from __future__ import annotations

from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts import run_manual_mlb_snapshot as runner


class ManualMlbSharedHistoryOpenerTests(TestCase):
    def test_same_observation_date_reuses_one_history_opener_across_games(self):
        rows = [
            {"game_id": "g1", "observed_at": "2026-10-06T14:00:00Z"},
            {"game_id": "g2", "observed_at": "2026-10-06T14:05:00Z"},
        ]
        seen = []

        def fake_price(game_rows, *, history_cache_dir, schedule, history_opener=None):
            seen.append(history_opener)
            game_id = str(game_rows[0]["game_id"])
            return {
                "resolved_game": {"game_pk": game_id},
                "observed_at_utc": game_rows[0]["observed_at"],
                "market_resolution": [],
                "feature_lineage": [],
                "results": [],
            }

        with TemporaryDirectory() as td, patch.object(runner, "_price_game", side_effect=fake_price):
            payload, blocked = runner._run_canonical_rows(
                rows,
                history_cache_dir=td,
                schedule=None,
            )

        self.assertEqual(blocked, [])
        self.assertEqual(len(payload["games"]), 2)
        self.assertEqual(len(seen), 2)
        self.assertIsNotNone(seen[0])
        self.assertIs(seen[0], seen[1])
        self.assertEqual(str(seen[0].target_date), "2026-10-06")

    def test_different_observation_dates_do_not_share_history_opener(self):
        rows = [
            {"game_id": "g1", "observed_at": "2026-10-06T23:59:00Z"},
            {"game_id": "g2", "observed_at": "2026-10-07T00:01:00Z"},
        ]
        seen = []

        def fake_price(game_rows, *, history_cache_dir, schedule, history_opener=None):
            seen.append(history_opener)
            return {
                "resolved_game": {"game_pk": game_rows[0]["game_id"]},
                "observed_at_utc": game_rows[0]["observed_at"],
                "market_resolution": [],
                "feature_lineage": [],
                "results": [],
            }

        with TemporaryDirectory() as td, patch.object(runner, "_price_game", side_effect=fake_price):
            runner._run_canonical_rows(rows, history_cache_dir=td, schedule=None)

        self.assertEqual(len(seen), 2)
        self.assertIsNot(seen[0], seen[1])
        self.assertEqual(str(seen[0].target_date), "2026-10-06")
        self.assertEqual(str(seen[1].target_date), "2026-10-07")


if __name__ == "__main__":
    import unittest
    unittest.main()
