import unittest

from sportsedge.source_range import SourceRangeError, partition_schedule_games


def payload(*rows):
    return {"dates": [{"date": "2026-08-01", "games": list(rows)}]}


class SourceRangeTests(unittest.TestCase):
    def test_out_of_request_final_is_removed_before_model_loader(self):
        data = payload(
            {"gamePk": 1, "officialDate": "2026-08-10", "status": {"abstractGameState": "Final"}},
            {"gamePk": 2, "officialDate": "2026-08-11", "status": {"abstractGameState": "Final"}},
            {"gamePk": 3, "officialDate": "2026-09-22", "status": {"abstractGameState": "Final"}},
        )
        accepted, violations = partition_schedule_games(data, start="2026-08-01", end="2026-08-10")
        self.assertEqual([g["gamePk"] for g in accepted], [1])
        self.assertEqual([v["game_pk"] for v in violations], [2, 3])
        self.assertTrue(all(v["reason_code"] == "SOURCE_RANGE_VIOLATION" for v in violations))

    def test_cache_or_http_payload_has_identical_range_behavior(self):
        data = payload(
            {"gamePk": 9, "officialDate": "2026-07-31"},
            {"gamePk": 8, "officialDate": "2026-08-03"},
        )
        first = partition_schedule_games(data, start="2026-08-01", end="2026-08-10")
        second = partition_schedule_games(data, start="2026-08-01", end="2026-08-10")
        self.assertEqual(first, second)

    def test_reversed_range_fails_closed(self):
        with self.assertRaisesRegex(SourceRangeError, "SOURCE_RANGE_REVERSED"):
            partition_schedule_games({}, start="2026-08-10", end="2026-08-01")


if __name__ == "__main__":
    unittest.main()
