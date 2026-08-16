import unittest

from sportsedge.v7_baseball_features import (
    V7FeatureError,
    assert_no_market_contamination,
    build_v7_baseball_features,
    bullpen_workload,
    rolling_statcast,
    starter_workload,
)

AS_OF = "2026-08-16T18:00:00Z"


def starter_rows():
    return [
        {"event_time":"2026-08-01T00:00:00Z","is_start":True,"pitches":95},
        {"event_time":"2026-08-07T00:00:00Z","is_start":True,"pitches":101},
        {"event_time":"2026-08-13T00:00:00Z","is_start":True,"pitches":98},
    ]


def bullpen_rows():
    return [
        {"event_time":"2026-08-15T20:00:00Z","is_start":False,"pitches":22,"pitcher_id":"a"},
        {"event_time":"2026-08-14T20:00:00Z","is_start":False,"pitches":18,"pitcher_id":"a"},
        {"event_time":"2026-08-15T21:00:00Z","is_start":False,"pitches":15,"pitcher_id":"b"},
        {"event_time":"2026-08-16T19:00:00Z","is_start":False,"pitches":99,"pitcher_id":"future"},
    ]


def statcast_rows():
    return [
        {"event_time":"2026-08-10T20:00:00Z","xwoba":.40,"hard_hit":1,"barrel":0,"whiff":0},
        {"event_time":"2026-08-15T20:00:00Z","xwoba":.30,"hard_hit":0,"barrel":1,"whiff":1},
        {"event_time":"2026-08-16T19:00:00Z","xwoba":.99,"hard_hit":1,"barrel":1,"whiff":1},
    ]


class V7BaseballFeatureTests(unittest.TestCase):
    def test_post_cutoff_rows_cannot_enter_starter_features(self):
        rows = starter_rows() + [{"event_time":"2026-08-16T19:00:00Z","is_start":True,"pitches":200}]
        a = starter_workload(rows, as_of=AS_OF)
        b = starter_workload(starter_rows(), as_of=AS_OF)
        self.assertEqual(a, b)

    def test_bullpen_windows_and_back_to_back_are_cutoff_safe(self):
        x = bullpen_workload(bullpen_rows(), as_of=AS_OF)
        self.assertEqual(x.relief_pitches_1d, 37)
        self.assertEqual(x.relief_pitches_3d, 55)
        self.assertEqual(x.relievers_back_to_back, 1)

    def test_statcast_future_event_is_excluded(self):
        x = rolling_statcast(statcast_rows(), as_of=AS_OF)
        self.assertEqual(x.pa_7d, 2)
        self.assertAlmostEqual(x.xwoba_14d, .35)
        self.assertAlmostEqual(x.hard_hit_30d, .5)

    def test_market_fields_are_recursively_prohibited(self):
        for payload in (
            {"american_odds": -110},
            {"x":{"bookmaker":"draftkings"}},
            {"x":[{"devig_probability":.5}]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(V7FeatureError):
                    assert_no_market_contamination(payload)

    def test_full_contract_is_deterministic_and_has_no_market_inputs(self):
        kwargs = dict(
            as_of=AS_OF,
            starter_rows=starter_rows(),
            bullpen_rows=bullpen_rows(),
            statcast_rows=statcast_rows(),
            platoon={
                "batter_hand":"L", "pitcher_hand":"R",
                "batter_xwoba_vs_hand":.36,
                "pitcher_xwoba_allowed_vs_hand":.34,
            },
        )
        a = build_v7_baseball_features(**kwargs)
        b = build_v7_baseball_features(**kwargs)
        self.assertEqual(a, b)
        self.assertEqual(len(a["feature_contract_sha256"]), 64)
        self.assertEqual(a["platoon"]["same_side"], 0.0)


if __name__ == "__main__":
    unittest.main()
