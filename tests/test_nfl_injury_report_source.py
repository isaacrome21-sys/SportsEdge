import unittest
from datetime import datetime, timezone

from sportsedge.sports.nfl.auto_slate import _bind_near_official_injuries
from sportsedge.sports.nfl.injury_report_source import build_pit_injury_inputs

PIT = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
SHA = "a" * 64
URI = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv"


def row(*, player="00-0030001", team="CHI", week=1, modified="2026-09-01T13:00:00Z",
        report_status="Questionable", practice_status="Limited Participation"):
    return {
        "season": "2026",
        "season_type": "REG",
        "team": team,
        "week": str(week),
        "gsis_id": player,
        "position": "WR",
        "full_name": "Example Player",
        "report_primary_injury": "Hamstring",
        "report_secondary_injury": "",
        "report_status": report_status,
        "practice_primary_injury": "Hamstring",
        "practice_secondary_injury": "",
        "practice_status": practice_status,
        "date_modified": modified,
    }


class NFLInjuryReportSourceTests(unittest.TestCase):
    def test_latest_pre_pit_row_wins_and_post_pit_update_is_excluded(self):
        rows = [
            row(modified="2026-09-01T10:00:00Z", report_status="Questionable"),
            row(modified="2026-09-01T13:00:00Z", report_status="Doubtful"),
            row(modified="2026-09-01T15:00:00Z", report_status="Out"),
        ]
        out = build_pit_injury_inputs(
            rows=rows, season=2026, target_week=1, team_ids=("CHI", "GB"),
            as_of=PIT, source_uri=URI, source_sha256=SHA,
        )
        self.assertEqual(len(out), 1)
        payload = out[0]["source_payload"]
        self.assertEqual(payload["status"], "DOUBTFUL")
        self.assertEqual(payload["practice_status"], "LP")
        self.assertEqual(payload["report_ts"], "2026-09-01T13:00:00+00:00")
        self.assertFalse(payload["official_host_confirmed"])
        self.assertEqual(payload["confirmation_level"], "NFLVERSE_NFLAPI_DERIVED")

    def test_wrong_team_week_and_missing_timestamp_are_surgically_excluded(self):
        rows = [
            row(team="DAL"),
            row(week=2),
            row(player="00-0030002", modified=""),
            row(player="00-0030003", team="GB", modified="2026-09-01T12:30:00Z"),
        ]
        out = build_pit_injury_inputs(
            rows=rows, season=2026, target_week=1, team_ids=("CHI", "GB"),
            as_of=PIT, source_uri=URI, source_sha256=SHA,
        )
        self.assertEqual([item["player_id"] for item in out], ["00-0030003"])

    def test_near_official_binding_never_claims_official_host(self):
        injury = build_pit_injury_inputs(
            rows=[row()], season=2026, target_week=1, team_ids=("CHI", "GB"),
            as_of=PIT, source_uri=URI, source_sha256=SHA,
        )
        bundle = {
            "collection_mode": "AUTO",
            "as_of_utc": PIT.isoformat(),
            "observations": {
                "injury_availability": {
                    "status": "MISSING",
                    "source_name": "NFL_OBJECTIVE_PROVIDER",
                }
            },
        }
        bound = _bind_near_official_injuries(bundle, game_id="2026_01_GB_CHI", as_of=PIT, rows=injury)
        obs = bound["observations"]["injury_availability"]
        self.assertEqual(obs["status"], "AVAILABLE")
        self.assertEqual(obs["source_name"], "NFLVERSE_NFLAPI_INJURY_REPORTS_NEAR_OFFICIAL")
        self.assertFalse(obs["payload"]["official_host_confirmed"])
        self.assertEqual(obs["source_uri"], URI)

    def test_existing_official_available_observation_has_precedence(self):
        bundle = {
            "collection_mode": "AUTO",
            "observations": {
                "injury_availability": {
                    "status": "AVAILABLE",
                    "source_name": "OFFICIAL_NFL_INJURY_REPORTS",
                    "payload": [{"status": "OUT"}],
                }
            },
        }
        injury = build_pit_injury_inputs(
            rows=[row()], season=2026, target_week=1, team_ids=("CHI", "GB"),
            as_of=PIT, source_uri=URI, source_sha256=SHA,
        )
        bound = _bind_near_official_injuries(bundle, game_id="g", as_of=PIT, rows=injury)
        self.assertEqual(bound, bundle)


if __name__ == "__main__":
    unittest.main()
