import unittest

from sportsedge.mlb_ops import (
    MlbOpsError,
    assert_point_in_time,
    closing_line_value_bps,
    deadman_status,
    fractional_kelly,
    grade_count_market,
    grade_moneyline,
    grade_nrfi_yrfi,
)


class MlbOpsTests(unittest.TestCase):
    def test_point_in_time_accepts_valid_pregame_row(self):
        assert_point_in_time([{
            'source_event_time_utc': '2026-08-16T17:00:00Z',
            'as_of_utc': '2026-08-16T17:05:00Z',
            'first_pitch_utc': '2026-08-16T18:10:00Z',
        }])

    def test_point_in_time_rejects_future_source(self):
        with self.assertRaisesRegex(MlbOpsError, 'POINT_IN_TIME_SOURCE_AFTER_ASOF'):
            assert_point_in_time([{
                'source_event_time_utc': '2026-08-16T17:10:00Z',
                'as_of_utc': '2026-08-16T17:05:00Z',
                'first_pitch_utc': '2026-08-16T18:10:00Z',
            }])

    def test_point_in_time_rejects_same_game_post_start(self):
        with self.assertRaisesRegex(MlbOpsError, 'POINT_IN_TIME_ASOF_NOT_PREGAME'):
            assert_point_in_time([{
                'source_event_time_utc': '2026-08-16T18:00:00Z',
                'as_of_utc': '2026-08-16T18:10:00Z',
                'first_pitch_utc': '2026-08-16T18:10:00Z',
            }])

    def test_positive_clv_when_bettor_beats_close(self):
        self.assertGreater(closing_line_value_bps(taken_odds=120, closing_odds=100), 0)

    def test_fractional_kelly_is_capped(self):
        stake = fractional_kelly(model_probability=0.65, american_odds=100, bankroll=1000, multiplier=1.0, max_fraction=0.05)
        self.assertEqual(stake, 50.0)

    def test_count_grading(self):
        self.assertEqual(grade_count_market(side='OVER', line=1.5, actual_value=2).result, 'WIN')
        self.assertEqual(grade_count_market(side='UNDER', line=1.5, actual_value=2).result, 'LOSS')
        self.assertEqual(grade_count_market(side='OVER', line=2, actual_value=2).result, 'PUSH')

    def test_moneyline_grading(self):
        self.assertEqual(grade_moneyline(selected_team='CHC', winning_team='CHC').result, 'WIN')
        self.assertEqual(grade_moneyline(selected_team='CHC', winning_team='STL').result, 'LOSS')

    def test_first_inning_grading(self):
        self.assertEqual(grade_nrfi_yrfi(market='NRFI', first_inning_runs=0).result, 'WIN')
        self.assertEqual(grade_nrfi_yrfi(market='YRFI', first_inning_runs=1).result, 'WIN')

    def test_deadman(self):
        good = deadman_status(last_success_utc='2026-08-16T20:00:00Z', now_utc='2026-08-16T20:30:00Z', max_age_minutes=45)
        bad = deadman_status(last_success_utc='2026-08-16T19:00:00Z', now_utc='2026-08-16T20:30:00Z', max_age_minutes=45)
        self.assertTrue(good['ok'])
        self.assertFalse(bad['ok'])


if __name__ == '__main__':
    unittest.main()
