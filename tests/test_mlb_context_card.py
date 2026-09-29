import json
from pathlib import Path
import tempfile, unittest
from scripts.acquire_mlb_card_context import game_pks, main as acquire_main
from sportsedge.mlb_context_card import context_section, lane_sha256
BUNDLE={"game_pk":777,"as_of_utc":"2026-09-29T20:00:00+00:00","status":"PARTIAL","payload_sha256":"ab"*32,"source":"MLB_PUBLIC_PREGAME_BUNDLE","starters":{"status":"AVAILABLE","probable_pitchers":{"away":{"player_id":650633,"player_name":"Michael King"},"home":{"player_id":571510,"player_name":"Matthew Boyd"}},"model_p_eligible":False},"lineups":{"status":"UNAVAILABLE","complete_by_side":{"away":False,"home":False},"model_p_eligible":False},"umpire":{"status":"AVAILABLE","source":"MLB_STATSAPI","as_of_utc":"2026-09-29T20:00:00+00:00","assignment":{"umpire_name":"Pat Hoberg"},"tendencies":{"sample_gate":"PASS","home_plate_games":30},"model_p_eligible":False},"weather_roof":{"status":"UNAVAILABLE","source":"NWS","errors":["NWS_POINTS_HTTP_503"],"model_p_eligible":False},"statcast":{"status":"AVAILABLE","source":"BASEBALL_SAVANT","retrieved_at":"2026-09-29T20:00:01+00:00","bound_pitcher_count":2,"bound_hitter_count":0,"model_p_eligible":False}}
class ContextCardTests(unittest.TestCase):
 def test_reports_retrieved_not_model_use(self):
  t="\n".join(context_section([BUNDLE]));self.assertIn("NOT used by model_p",t);self.assertIn("Michael King vs Matthew Boyd",t);self.assertIn("umpire_name=Pat Hoberg",t);self.assertIn("NWS_POINTS_HTTP_503",t);self.assertIn("Park/venue: NOT RETRIEVED this run",t);self.assertIn(lane_sha256(BUNDLE["statcast"])[:12],t)
 def test_failures(self):
  self.assertIn("NOT RETRIEVED","\n".join(context_section([],failures=["Game 9: context NOT RETRIEVED (HTTPError: 500)"])))
 def test_acquire_records_failure(self):
  payload={"games":[{"resolved_game":{"game_pk":1}},{"resolved_game":{"game_pk":2}}],"results":[]};self.assertEqual(game_pks(payload),[1,2])
  def fake(*,game_pk,as_of):
   if game_pk==2:raise RuntimeError("savant down")
   return dict(BUNDLE,game_pk=game_pk)
  with tempfile.TemporaryDirectory() as tmp:
   eng=Path(tmp)/"engine.json";eng.write_text(json.dumps(payload));out=Path(tmp)/"ctx";acquire_main(["--engine-output",str(eng),"--out-dir",str(out)],acquire=fake);self.assertIn("savant down",json.loads((out/"failures.json").read_text())[0])
if __name__=="__main__":unittest.main()
