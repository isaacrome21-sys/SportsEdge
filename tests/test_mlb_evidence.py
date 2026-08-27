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

    def test_confirmed_nine_slot_lineup_marks_roster_bench_player_absent(self):
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
        self.assertEqual(len(lineup_packets), 20)
        away_bench = next(packet for packet in lineup_packets if packet.entity_id == "1999")
        home_bench = next(packet for packet in lineup_packets if packet.entity_id == "2999")
        self.assertFalse(away_bench.value)
        self.assertFalse(home_bench.value)
        self.assertEqual(away_bench.gate_action, "BLOCK_MATCHING")
        self.assertEqual(away_bench.authority, "AUTHORITATIVE")
        starter = next(packet for packet in lineup_packets if packet.entity_id == "1001")
        self.assertTrue(starter.value)
        self.assertEqual(starter.gate_action, "NONE")

    def test_incomplete_lineup_never_manufactures_absent_player_facts(self):
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
            packet.fact_type == "STARTING_LINEUP_STATUS" for packet in packets
        ))


if __name__ == "__main__":
    unittest.main()
