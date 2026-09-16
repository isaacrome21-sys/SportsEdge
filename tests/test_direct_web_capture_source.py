import json
import unittest
from datetime import datetime, timezone
from sportsedge.draftkings_game_market_source import DraftKingsGameMarketError, RawDraftKingsBoard, board_url
from sportsedge import direct_web_capture_source as t
NOW=datetime(2026,9,16,18,0,0,tzinfo=timezone.utc); PAYLOAD={"events":[],"markets":[],"selections":[]}
def _fetch(sk): return RawDraftKingsBoard(sk,board_url(sk),json.dumps(PAYLOAD).encode(),NOW,PAYLOAD)
class SharedTransportTest(unittest.TestCase):
 def test_sport_neutral_across_leagues(self):
  for sk,host in (("americanfootball_nfl","sportsbook-nash.draftkings.com"),("baseball_mlb","sportsbook-nash.draftkings.com"),("americanfootball_ncaaf","sportsbook-nash.draftkings.com")):
   rec=t.acquire_board(sk,fetcher=_fetch); self.assertEqual(rec["sport_key"],sk); self.assertEqual(rec["transport_host"],host); self.assertEqual(rec["source_class"],"DRAFTKINGS_DIRECT_WEB_V1")
 def test_hashes_received_bytes_not_reserialization(self):
  import hashlib
  rec=t.acquire_board("baseball_mlb",fetcher=_fetch); self.assertEqual(rec["raw_sha256"],hashlib.sha256(json.dumps(PAYLOAD).encode()).hexdigest())
 def test_no_provider_timestamp(self):
  rec=t.acquire_board("baseball_mlb",fetcher=_fetch); self.assertIsNone(rec["book_last_update"]); self.assertFalse(rec["provider_quote_timestamp_available"])
 def test_failure_carries_attempts_and_no_record(self):
  def boom(_sk): raise DraftKingsGameMarketError("DK_HTTP_403")
  with self.assertRaises(t.DirectCaptureError) as ctx:t.acquire_board("baseball_mlb",fetcher=boom,clock=lambda:NOW)
  self.assertEqual(ctx.exception.attempts[0]["result_class"],"DK_HTTP_403")
if __name__=="__main__": unittest.main()
