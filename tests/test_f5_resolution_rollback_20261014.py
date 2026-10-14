"""Synthetic regressions for all-or-nothing fixture-resolution receipts."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge import mlb_f5_fixture_resolution as resolution


class ResolutionRollbackTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
        self.rows = [dict(sport='MLB', market='F5_TOTAL', away='A', home='B', kickoff='2030-01-01T18:00:00Z'),
                     dict(sport='MLB', market='F5_TOTAL', away='C', home='D', kickoff='2030-01-01T19:00:00Z')]
        self.games = [SimpleNamespace(away_name='A', home_name='B', game_date='2030-01-01T18:00:00Z', game_pk=1),
                      SimpleNamespace(away_name='C', home_name='D', game_date='2030-01-01T19:00:00Z', game_pk=2)]

    def test_later_failure_discards_provisional_success_receipts(self):
        self.games[1].game_date = 'malformed'
        with patch.object(resolution, 'fetch_schedule', return_value=self.games):
            out, receipts = resolution.stamp_f5_game_pks(self.rows, opener=object(), resolved_at=self.now)
        self.assertTrue(all(a is b for a, b in zip(out, self.rows)))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['status'], 'RESOLUTION_UNAVAILABLE')
        self.assertEqual(receipts[0]['rows_stamped'], 0)
        self.assertTrue(all('game_pk' not in row for row in self.rows))

    def test_invalid_clocks_refuse_before_fetch(self):
        for clock in ('2030-01-01T00:00:00Z', 0, False, {}, datetime(2030, 1, 1)):
            with self.subTest(clock=clock), patch.object(resolution, 'fetch_schedule') as fetch:
                out, receipts = resolution.stamp_f5_game_pks(self.rows, resolved_at=clock)
                self.assertEqual(out, self.rows)
                self.assertEqual(receipts[0]['status'], 'RESOLUTION_UNAVAILABLE')
                self.assertIn('RESOLUTION_CLOCK_INVALID', receipts[0]['detail'])
                fetch.assert_not_called()

    def test_success_preserves_per_fixture_receipts_and_input(self):
        with patch.object(resolution, 'fetch_schedule', return_value=self.games):
            out, receipts = resolution.stamp_f5_game_pks(self.rows, opener=object(), resolved_at=self.now)
        self.assertEqual([row['game_pk'] for row in out], [1, 2])
        self.assertEqual([r['rows_stamped'] for r in receipts], [1, 1])
        self.assertTrue(all(r['status'] == 'RESOLVED' for r in receipts))
        self.assertTrue(all('game_pk' not in row for row in self.rows))


if __name__ == '__main__':
    unittest.main()
