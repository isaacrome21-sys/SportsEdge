import unittest

from sportsedge.mlb_pitcher_k_workload_candidate import (
    AUTHORITY,
    PitcherKWorkloadCandidateError,
    build_workload_bundle,
)


def _start(*, bf=24, pitches=92, ks=7, ip="6.0"):
    return {
        "stat": {
            "gamesStarted": 1,
            "battersFaced": bf,
            "numberOfPitches": pitches,
            "strikeOuts": ks,
            "inningsPitched": ip,
        }
    }


class PitcherKWorkloadCandidateTests(unittest.TestCase):
    def test_builds_research_only_bundle_from_existing_prior_start_rows(self):
        rows = [
            _start(bf=22, pitches=86, ks=5, ip="5.2"),
            _start(bf=24, pitches=91, ks=7, ip="6.0"),
            _start(bf=26, pitches=99, ks=8, ip="6.1"),
            _start(bf=23, pitches=88, ks=6, ip="5.2"),
            _start(bf=25, pitches=96, ks=9, ip="6.0"),
        ]
        got = build_workload_bundle(rows)
        self.assertEqual(got["authority"], AUTHORITY)
        self.assertFalse(got["deployment"])
        self.assertFalse(got["model_p_eligible"])
        self.assertEqual(got["start_count"], 5)
        self.assertEqual(got["history"][0]["batters_faced"], 22)
        self.assertAlmostEqual(got["summary"]["recent_mean_batters_faced"], 24.0)
        self.assertAlmostEqual(
            got["summary"]["recent_mean_k_per_batter_faced"],
            sum([5/22, 7/24, 8/26, 6/23, 9/25]) / 5,
        )

    def test_missing_workload_field_fails_closed(self):
        rows = [_start() for _ in range(5)]
        del rows[2]["stat"]["battersFaced"]
        with self.assertRaisesRegex(PitcherKWorkloadCandidateError, "battersFaced"):
            build_workload_bundle(rows)

    def test_requires_frozen_five_to_ten_start_window(self):
        with self.assertRaisesRegex(PitcherKWorkloadCandidateError, "5..10"):
            build_workload_bundle([_start() for _ in range(4)])
        with self.assertRaisesRegex(PitcherKWorkloadCandidateError, "5..10"):
            build_workload_bundle([_start() for _ in range(11)])

    def test_rejects_non_start_or_impossible_values(self):
        rows = [_start() for _ in range(5)]
        rows[0]["stat"]["gamesStarted"] = 0
        with self.assertRaisesRegex(PitcherKWorkloadCandidateError, "not a start"):
            build_workload_bundle(rows)

        rows = [_start() for _ in range(5)]
        rows[0]["stat"]["strikeOuts"] = 30
        with self.assertRaisesRegex(PitcherKWorkloadCandidateError, "impossible"):
            build_workload_bundle(rows)


if __name__ == "__main__":
    unittest.main()
