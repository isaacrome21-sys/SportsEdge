from datetime import datetime, timezone
import unittest

from scripts.build_nfl_live_feature_rows import _depth_asof, _start


class NFLLiveFeatureAsofTests(unittest.TestCase):
    def test_nflverse_gameday_gametime_uses_eastern_contract(self):
        value=_start({"game_id":"g1","gameday":"2026-09-10","gametime":"20:20"})
        self.assertEqual(value,datetime(2026,9,11,0,20,tzinfo=timezone.utc))

    def test_timestamped_depth_rows_after_asof_are_excluded(self):
        rows=[
            {"gsis_id":"old","dt":"2026-09-10T20:00:00Z"},
            {"gsis_id":"future","dt":"2026-09-10T22:00:00Z"},
            {"gsis_id":"weekly","dt":""},
        ]
        out=_depth_asof(rows,datetime(2026,9,10,21,0,tzinfo=timezone.utc))
        self.assertEqual([r["gsis_id"] for r in out],["old","weekly"])

    def test_naive_explicit_start_fails_closed(self):
        with self.assertRaisesRegex(SystemExit,"NFL_LIVE_GAME_START_INVALID"):
            _start({"game_id":"g1","game_start_ts":"2026-09-10T20:20:00"})


if __name__=="__main__": unittest.main()
