import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from sportsedge.draftkings_game_market_source import RawDraftKingsBoard
from scripts.capture_direct_dk_closing_lines import capture

UTC=timezone.utc
POLICY={
 'policy_id':'CLOSING_LINE_ARCHIVE_V1','promotion_authority':False,
 'windows':{'decision':{'min_minutes_before_start':45,'max_minutes_before_start':120},
            'close':{'min_minutes_before_start':2,'max_minutes_before_start':20}}
}

def payload(start='2026-09-14T03:00:00Z'):
 return {'events':[{'id':'e1','name':'Away Team @ Home Team','startEventDate':start}],
 'markets':[{'id':'m1','eventId':'e1','name':'Moneyline'}],
 'selections':[{'marketId':'m1','label':'Away Team','displayOdds':{'american':'+120'}},
               {'marketId':'m1','label':'Home Team','displayOdds':{'american':'-140'}}]}

class CaptureDirectDKTests(unittest.TestCase):
 def test_due_rows_preserve_exact_raw_and_zero_authority(self):
  received=datetime(2026,9,14,2,0,tzinfo=UTC)
  p=payload(); raw=b' {"exact":"provider bytes"} '
  def fake(sport): return RawDraftKingsBoard(sport,'https://example.test',raw,received,p)
  with tempfile.TemporaryDirectory() as td, patch('scripts.capture_direct_dk_closing_lines.fetch_board',side_effect=fake):
   root=Path(td); report=capture(out_dir=root,policy=POLICY)
   self.assertEqual(report['total_rows_written'],6)
   rows=[]
   for path in (root/'archive/direct-dk').glob('*/*.ndjson'):
    rows += [json.loads(x) for x in path.read_text().splitlines()]
   self.assertEqual(len(rows),6)
   for row in rows:
    self.assertEqual((root/row['raw_relative_path']).read_bytes(),raw)
    self.assertEqual(row['evidence_class'],'NOT_EVIDENCE')
    self.assertFalse(row['promotion_authority'])
    self.assertFalse(row['evidence_clock_authority'])
    self.assertFalse(row['historical_backfill'])
    self.assertEqual(row['timestamp_semantics'],'HTTP_RESPONSE_RECEIPT_UPPER_BOUND')

 def test_outside_window_writes_no_normalized_rows(self):
  received=datetime(2026,9,14,0,0,tzinfo=UTC); p=payload()
  def fake(sport): return RawDraftKingsBoard(sport,'https://example.test',b'{}',received,p)
  with tempfile.TemporaryDirectory() as td, patch('scripts.capture_direct_dk_closing_lines.fetch_board',side_effect=fake):
   report=capture(out_dir=Path(td),policy=POLICY)
   self.assertEqual(report['total_rows_written'],0)

if __name__=='__main__': unittest.main()
