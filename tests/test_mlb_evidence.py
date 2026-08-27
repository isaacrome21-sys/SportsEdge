from datetime import datetime, timezone
import unittest

from sportsedge.mlb_evidence import official_mlb_evidence
from sportsedge.mlb_source import GameSnapshot

NOW = datetime(2026, 8, 27, 15, 45, tzinfo=timezone.utc)


def snapshot():
    return GameSnapshot(
        game_pk=823014,
        game_date="2026-08-27T18:15:00+00:00",
        status="Preview",
        away_id=110,
        away_name="Baltimore Orioles",
        home_id=138,
        home_name="St. Louis Cardinals",
        away_probable_pitcher_id=669203,
        away_probable_pitcher_name="Trevor Rogers",
        home_probable_pitcher_id=680570,
        home_probable_pitcher_name="Gordon Graceffo",
        retrieved_at=NOW.isoformat(),
    )


def team_players(start=1, bench_id=99):
    players = {}
    for slot in range(1, 10):
        player_id = start * 1000 + slot
        players[f"ID{player_id}"] = {
            "person": {"id": player_id, "fullName": f"Player {player_id}"},
            "battingOrder": str(slot * 100),
        }
    players[f"ID{bench_id}"] = {
        "person": {"id": bench_id, "fullName": f"Bench {bench_id}"},
    }
    return players


class MLBOfficialEvidenceTests(unittest.TestCase):
    def test_schedule_probable_pitchers_are_primary_not_authoritative(self):
        packets = official_mlb_evidence(
            snapshot=snapshot(),
            boxscore=None,
            observed_at_utc=NOW,
            acquisition_mode="AUTOMATIC",
        )
        self.assertEqual(len(packets), 2)
        self.assertEqual({packet.fact_type for packet in packets}, {"STARTER_ID"})
        self.assertEqual({packet.authority for packet in packets}, {"PRIMARY"})
        self.assertEqual({packet.source_name for packet in packets}, {"MLB_STATSAPI_SCHEDULE"})

    def test_confirmed_nine_slot_lineup_records_team_set_and_positive_members_only(self):
        boxscore = {
            "teams": {
                "away": {"players": team_players(start=1, bench_id=1999)},
                "home": {"players": team_players(start=2, bench_id=2999)},
            }
        }
        packets = official_mlb_evidence(
            snapshot=snapshot(),
            boxscore=boxscore,
            observed_at_utc=NOW,
            acquisition_mode="AUTOMATIC",
        )
        lineup_packets = [
            packet for packet in packets if packet.fact_type == "STARTING_LINEUP_STATUS"
        ]
        lineup_sets = [
            packet for packet in packets if packet.fact_type == "STARTING_LINEUP_IDS"
        ]
        self.assertEqual(len(lineup_packets), 18)
        self.assertEqual(len(lineup_sets), 2)
        self.assertFalse(any(packet.entity_id in {"1999", "2999"} for packet in lineup_packets))
        self.assertTrue(all(packet.value is True for packet in lineup_packets))
        self.assertTrue(all(packet.gate_action == "NONE" for packet in lineup_packets))
        away = next(packet for packet in lineup_sets if packet.subject_id == "110")
        self.assertEqual(away.value, list(range(1001, 1010)))
        self.assertEqual(away.authority, "AUTHORITATIVE")

    def test_incomplete_lineup_never_manufactures_confirmed_lineup_facts(self):
        players = team_players(start=1, bench_id=1999)
        del players["ID1009"]["battingOrder"]
        boxscore = {
            "teams": {
                "away": {"players": players},
                "home": {"players": {}},
            }
        }
        packets = official_mlb_evidence(
            snapshot=snapshot(),
            boxscore=boxscore,
            observed_at_utc=NOW,
            acquisition_mode="AUTOMATIC",
        )
        self.assertFalse(any(
            packet.fact_type in {"STARTING_LINEUP_STATUS", "STARTING_LINEUP_IDS"}
            for packet in packets
        ))


if __name__ == "__main__":
    unittest.main()
