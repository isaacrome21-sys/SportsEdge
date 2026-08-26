from __future__ import annotations

from dataclasses import dataclass
import unittest

from sportsedge.sports.cfb import pregame_features as pf


class PregameWindowTests(unittest.TestCase):
    def test_week_one_uses_prior_season_only(self):
        rows = [
            {"game_id":"p1","season":"2023","week":"15","status_type_completed":"TRUE"},
            {"game_id":"c1","season":"2024","week":"1","status_type_completed":"TRUE"},
            {"game_id":"f1","season":"2024","week":"2","status_type_completed":"TRUE"},
        ]
        out = pf.select_history_window(rows, season=2024, through_week=1)
        self.assertEqual(out.source_season, 2023)
        self.assertEqual(out.sample_source, "SPORTSDATAVERSE_PRIOR_SEASON_FALLBACK_V1")
        self.assertEqual([r["game_id"] for r in out.schedules], ["p1"])
        self.assertTrue(all(int(r["season"]) == 2024 for r in out.schedules))

    def test_missing_prior_completed_data_fails_closed(self):
        rows = [
            {"game_id":"p1","season":"2023","week":"15","status_type_completed":"FALSE"},
            {"game_id":"c1","season":"2024","week":"1","status_type_completed":"TRUE"},
        ]
        with self.assertRaisesRegex(pf.CFBPregameFeatureError, "CFB_HISTORICAL_PRIOR_SEASON_REQUIRED"):
            pf.select_history_window(rows, season=2024, through_week=1)

    def test_week_two_stays_same_season(self):
        rows = [
            {"game_id":"p1","season":"2023","week":"15","status_type_completed":"TRUE"},
            {"game_id":"c1","season":"2024","week":"1","status_type_completed":"TRUE"},
            {"game_id":"c2","season":"2024","week":"2","status_type_completed":"TRUE"},
        ]
        out = pf.select_history_window(rows, season=2024, through_week=2)
        self.assertEqual(out.source_season, 2024)
        self.assertEqual(out.delegate_through_week, 2)
        self.assertEqual([r["game_id"] for r in out.schedules], ["c1", "c2"])


@dataclass(frozen=True)
class DummyMetric:
    through_week: int
    sample_source: str
    value: float


class PregameDelegateTests(unittest.TestCase):
    def setUp(self):
        self.original = pf.build_week_to_date_metrics

    def tearDown(self):
        pf.build_week_to_date_metrics = self.original

    def test_target_season_mutation_cannot_reach_week_one_delegate(self):
        seen = []

        def fake_delegate(**kwargs):
            seen.append(tuple((r["game_id"], int(r["season"])) for r in kwargs["schedules"]))
            return {"Alpha": DummyMetric(kwargs["through_week"] - 1, "WTD", 1.0)}

        pf.build_week_to_date_metrics = fake_delegate
        base = [
            {"game_id":"p1","season":"2023","week":"15","status_type_completed":"TRUE"},
            {"game_id":"c1","season":"2024","week":"1","status_type_completed":"TRUE","garbage":"1"},
        ]
        common = dict(
            season=2024, through_week=1, adv_team=[], adv_situational=[], adv_drives=[],
            play_by_play=[], feature_asof_ts="2024-08-20T12:00:00Z",
        )
        first = pf.build_pregame_metrics(schedules=base, **common)
        mutated = [dict(row) for row in base]
        mutated[1]["garbage"] = "999999999"
        second = pf.build_pregame_metrics(schedules=mutated, **common)

        self.assertEqual(first, second)
        self.assertEqual(seen, [(('p1', 2024),), (('p1', 2024),)])
        self.assertEqual(first["Alpha"].through_week, 0)
        self.assertEqual(first["Alpha"].sample_source, "SPORTSDATAVERSE_PRIOR_SEASON_FALLBACK_V1")


if __name__ == "__main__":
    unittest.main()
