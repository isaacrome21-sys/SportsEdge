from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from sportsedge.mlb_objective_depth_sources import (
    summarize_statcast_window,
    summarize_recent_pitching_usage,
    fetch_team_fielding_fallback,
)


class _Resp:
    def __init__(self, payload): self.raw = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class MLBObjectiveDepthTests(unittest.TestCase):
    def test_statcast_skill_and_catcher_proxy_are_explicit(self):
        rows = [
            {"batter":"10","pitcher":"20","fielder_2":"30","description":"swinging_strike","zone":"12","release_speed":"97","release_spin_rate":"2400","pitch_type":"FF","launch_speed":"","estimated_woba_using_speedangle":""},
            {"batter":"10","pitcher":"20","fielder_2":"30","description":"called_strike","zone":"11","plate_x":"0.90","plate_z":"2.0","sz_bot":"1.5","sz_top":"3.5","release_speed":"96","release_spin_rate":"2380","pitch_type":"FF","launch_speed":""},
            {"batter":"10","pitcher":"20","fielder_2":"30","description":"hit_into_play","zone":"5","release_speed":"85","release_spin_rate":"1800","pitch_type":"SL","launch_speed":"101","launch_speed_angle":"6","estimated_woba_using_speedangle":"0.61","estimated_ba_using_speedangle":"0.55","estimated_slg_using_speedangle":"1.1"},
        ]
        out = summarize_statcast_window(rows)
        self.assertAlmostEqual(out["batters"]["10"]["whiff_per_swing"], 0.5)
        self.assertAlmostEqual(out["pitchers"]["20"]["chase_rate"], 0.5)
        self.assertGreater(out["pitchers"]["20"]["pitch_mix"]["FF"], 0.6)
        catcher = out["catchers"]["30"]
        self.assertEqual(catcher["borderline_takes"], 1)
        self.assertEqual(catcher["borderline_called_strike_rate_proxy"], 1.0)
        self.assertEqual(catcher["framing_metric_status"], "RECEIVING_PROXY_NOT_OFFICIAL_FRAMING_RUNS")

    def test_recent_pitching_usage_separates_relief_and_starter_history(self):
        def feed(day, pitchers):
            players = {}
            for pid, pitches in pitchers:
                players[f"ID{pid}"] = {"person":{"id":pid},"stats":{"pitching":{"pitchesThrown":pitches,"battersFaced":10}}}
            return {
                "gameData":{"datetime":{"originalDate":day},"teams":{"home":{"id":1},"away":{"id":2}}},
                "liveData":{"boxscore":{"teams":{"home":{"pitchers":[pid for pid,_ in pitchers],"players":players},"away":{}}}},
            }
        feeds = [feed("2026-08-29", [(100,85),(101,20)]), feed("2026-08-30", [(102,80),(101,18)])]
        out = summarize_recent_pitching_usage(feeds, team_id=1, as_of=datetime(2026,9,1,tzinfo=timezone.utc))
        self.assertEqual(out["relievers"]["101"]["pitches_thrown"], 38)
        self.assertTrue(out["relievers"]["101"]["pitched_consecutive_calendar_days"])
        self.assertIn("100", out["starters"])
        self.assertEqual(out["high_leverage_status"], "UNAVAILABLE_FROM_BOXSCORE_ONLY")

    def test_fielding_fallback_never_claims_oaa(self):
        payload = {"stats":[{"splits":[{"stat":{"fielding":".987","errors":44,"assists":1200,"putOuts":3300,"doublePlays":110}}]}]}
        row, uri, digest = fetch_team_fielding_fallback(
            team_id=1, season=2026, opener=lambda req, timeout=30: _Resp(payload)
        )
        self.assertEqual(row["fielding_percentage"], ".987")
        self.assertEqual(row["oaa_status"], "UNAVAILABLE_IN_STATSAPI_FIELDING_FALLBACK")
        self.assertEqual(len(digest), 64)
        self.assertIn("group=fielding", uri)


if __name__ == "__main__": unittest.main()
