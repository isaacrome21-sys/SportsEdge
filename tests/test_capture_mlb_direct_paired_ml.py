import importlib.util,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sportsedge.draftkings_game_market_source import RawDraftKingsBoard
_spec=importlib.util.spec_from_file_location("capture_mlb_direct_paired_ml",Path(__file__).resolve().parents[1]/"scripts"/"capture_mlb_direct_paired_ml.py"); cap=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cap)
NOW=datetime(2026,9,16,18,0,0,tzinfo=timezone.utc)
def payload(minutes_before=32,one_sided=False):
 start=NOW+timedelta(minutes=minutes_before); sels=[{"marketId":"m1","label":"New York Yankees","displayOdds":{"american":"-145"}},{"marketId":"m1","label":"Boston Red Sox","displayOdds":{"american":"+122"}}]
 if one_sided:sels=sels[:1]
 return {"events":[{"id":"MLB1","name":"Boston Red Sox @ New York Yankees","startEventDate":start.isoformat().replace("+00:00","Z"),"participants":[{"name":"Boston Red Sox","venueRole":"Away"},{"name":"New York Yankees","venueRole":"Home"}]}],"markets":[{"id":"m1","eventId":"MLB1","name":"Moneyline"}],"selections":sels}
def fetcher(p):
 def _f(sk):
  from sportsedge.draftkings_game_market_source import board_url
  raw=json.dumps(p).encode(); return RawDraftKingsBoard(sk,board_url(sk),raw,NOW,p)
 return _f
class MLBDirectCaptureTest(unittest.TestCase):
 def test_retains_and_binds(self):
  with tempfile.TemporaryDirectory() as d:
   r=cap.capture(output_dir=d,clock=lambda:NOW,fetch=fetcher(payload()),artifact_binder=lambda:"a"*64); row=json.loads(Path(r["paths"][0]).read_text())
  self.assertEqual(r["status"],"RETAINED"); self.assertEqual(row["capture_window"],"T30"); self.assertFalse(row["promotion_authority"]); self.assertEqual(row["model_artifact_sha256"],"a"*64); self.assertEqual(r["events_on_board"],1); self.assertEqual(r["events_in_window"],1)
 def test_no_capture_due_requires_nonempty_board(self):
  with tempfile.TemporaryDirectory() as d:r=cap.capture(output_dir=d,fetch=fetcher(payload(200)),artifact_binder=lambda:"a"*64)
  self.assertEqual(r["status"],"NO_CAPTURE_DUE"); self.assertEqual(r["events_on_board"],1); self.assertEqual(r["events_in_window"],0)
 def test_empty_board_blocks(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(cap.CaptureBlocked) as c:cap.capture(output_dir=d,fetch=fetcher({"events":[],"markets":[],"selections":[]}),artifact_binder=lambda:"a"*64)
  self.assertEqual(c.exception.reason,"BLOCKED_EMPTY_BOARD"); self.assertEqual(c.exception.detail["events_on_board"],0); self.assertIn("raw_sha256",c.exception.detail); self.assertIn("source_uri",c.exception.detail)
 def test_one_sided_blocks(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(cap.CaptureBlocked) as c:cap.capture(output_dir=d,fetch=fetcher(payload(one_sided=True)),artifact_binder=lambda:"a"*64)
  self.assertEqual(c.exception.reason,"BLOCKED_ONE_SIDED")
 def test_dedup(self):
  with tempfile.TemporaryDirectory() as d:
   cap.capture(output_dir=d,fetch=fetcher(payload()),artifact_binder=lambda:"a"*64); r=cap.capture(output_dir=d,fetch=fetcher(payload()),artifact_binder=lambda:"a"*64)
  self.assertEqual(r["status"],"ALREADY_CAPTURED")
if __name__=="__main__": unittest.main()
