import unittest

from sportsedge.sports.nfl.player_stats_workload_source import build_prior_player_workload_inputs

URI = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv"
SHA = "b" * 64


def row(*, player_id="00-0030001", team="CHI", week=1, carries=3, targets=5, attempts=0,
        target_share=.25, air_yards_share=.30):
    return {
        "player_id": player_id,
        "player_name": "Example Player",
        "recent_team": team,
        "season": "2026",
        "week": str(week),
        "season_type": "REG",
        "attempts": str(attempts),
        "carries": str(carries),
        "targets": str(targets),
        "receptions": "4",
        "receiving_air_yards": "62",
        "target_share": str(target_share),
        "air_yards_share": str(air_yards_share),
    }


class NFLPlayerStatsWorkloadTests(unittest.TestCase):
    def test_target_week_is_excluded_fail_closed(self):
        out = build_prior_player_workload_inputs(
            rows=[row(week=1, targets=4), row(week=2, targets=8), row(week=3, targets=99)],
            season=2026, target_week=3, team_ids=("CHI", "GB"),
            source_uri=URI, source_sha256=SHA,
        )
        self.assertEqual(len(out), 1)
        payload = out[0]["source_payload"]
        self.assertEqual(payload["sample_weeks"], [1, 2])
        self.assertEqual(payload["targets"], [4.0, 8.0])
        self.assertEqual(out[0]["player_id"], "GSIS:00-0030001")
        self.assertEqual(payload["identity_namespace"], "GSIS")
        self.assertTrue(payload["strictly_prior_week_only"])

    def test_team_scope_and_regular_season_only(self):
        post = row(player_id="00-0030002", team="CHI", week=1)
        post["season_type"] = "POST"
        out = build_prior_player_workload_inputs(
            rows=[row(team="DAL"), post, row(player_id="00-0030003", team="GB")],
            season=2026, target_week=2, team_ids=("CHI", "GB"),
            source_uri=URI, source_sha256=SHA,
        )
        self.assertEqual([item["player_id"] for item in out], ["GSIS:00-0030003"])

    def test_never_invents_routes_or_snaps(self):
        out = build_prior_player_workload_inputs(
            rows=[row()], season=2026, target_week=2, team_ids=("CHI",),
            source_uri=URI, source_sha256=SHA,
        )
        payload = out[0]["source_payload"]
        self.assertEqual(payload["routes"], [])
        self.assertEqual(payload["snaps"], [])
        self.assertEqual(payload["snap_share"], [])
        self.assertEqual(payload["source_file_sha256"], SHA)


if __name__ == "__main__":
    unittest.main()
