import json, unittest
from datetime import datetime, timezone
from sportsedge.mlb_context import fetch_slate_context, parse_context
from sportsedge.mlb_source import GameSnapshot


def snap(pk=123):
    return GameSnapshot(
        game_pk=pk, game_date="2026-08-12T18:10:00+00:00", status="Preview",
        away_id=1, away_name="Away", home_id=2, home_name="Home",
        away_probable_pitcher_id=11, away_probable_pitcher_name="Away SP",
        home_probable_pitcher_id=22, home_probable_pitcher_name="Home SP",
        retrieved_at=datetime(2026,8,12,12,0,tzinfo=timezone.utc).isoformat(),
        venue_id=15, official_date="2026-08-12",
    )


class Response:
    def __init__(self, payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return json.dumps(self.payload).encode()


class MLBContextTests(unittest.TestCase):
    def test_missing_weather_and_umpire_are_explicit_not_posted(self):
        row=parse_context(snap(), {"gameData":{"venue":{"name":"Park","fieldInfo":{"roofType":"Open"}},"weather":{},"probablePitchers":{}},"liveData":{"boxscore":{"officials":[]}}})
        self.assertEqual(row.weather_status,"NOT_POSTED"); self.assertIsNone(row.weather)
        self.assertEqual(row.plate_umpire_status,"NOT_POSTED"); self.assertIsNone(row.plate_umpire)
        self.assertEqual(row.roof_type,"Open")
        self.assertEqual(row.away_probable_pitcher,"Away SP")

    def test_posted_context_is_preserved_without_reinterpretation(self):
        row=parse_context(snap(), {"gameData":{"venue":{"name":"Chase Field","fieldInfo":{"roofType":"Retractable"}},"weather":{"condition":"Partly Cloudy","temp":101,"wind":"6 mph, Out To RF"},"probablePitchers":{"away":{"fullName":"Feed Away"},"home":{"fullName":"Feed Home"}}},"liveData":{"boxscore":{"officials":[{"officialType":"Home Plate","official":{"id":7,"fullName":"Ump Name"}}]}}})
        self.assertEqual(row.weather_status,"POSTED"); self.assertEqual(row.weather["temp"],101)
        self.assertEqual(row.plate_umpire_status,"POSTED"); self.assertEqual(row.plate_umpire,{"name":"Ump Name","id":7})
        self.assertEqual(row.roof_type,"Retractable")
        self.assertEqual(row.away_probable_pitcher,"Feed Away")

    def test_fetch_failure_keeps_game_visible(self):
        def opener(req, timeout=15): raise OSError("network down")
        rows=fetch_slate_context([snap()],opener=opener)
        self.assertEqual(len(rows),1); self.assertEqual(rows[0].game_id,"123")
        self.assertEqual(rows[0].weather_status,"FETCH_FAILED")
        self.assertEqual(rows[0].plate_umpire_status,"FETCH_FAILED")
        self.assertIn("network down",rows[0].error)

    def test_duplicate_game_is_explicit_failure_not_dropped(self):
        payload={"gameData":{"venue":{},"weather":{}},"liveData":{"boxscore":{"officials":[]}}}
        def opener(req, timeout=15): return Response(payload)
        rows=fetch_slate_context([snap(),snap()],opener=opener)
        self.assertEqual(len(rows),2); self.assertEqual(rows[1].error,"DUPLICATE_GAME_PK")

if __name__=='__main__': unittest.main()
