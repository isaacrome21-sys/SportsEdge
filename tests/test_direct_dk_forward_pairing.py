import json
import unittest
from pathlib import Path

from sportsedge.validation.direct_dk_forward_pairing import _load_policy, pair_rows, DirectDKPairingError

POLICY=Path(__file__).resolve().parents[1]/"config/direct_dk_forward_pair_admission_v1.json"
SHA="a"*64

def row(*,sport="americanfootball_nfl",captured="2026-09-17T22:30:00Z",start="2026-09-18T00:15:00Z",market="spreads",outcome="A",point=-3.0):
    return {"schema_version":"DIRECT_DK_CLOSING_ROW_V1","provider":"DRAFTKINGS_DIRECT_WEB","sportsbook":"draftkings","sport_key":sport,"provider_event_id":"e1","home_team":"A","away_team":"B","commence_time":start,"market":market,"outcome":outcome,"point":point,"price_american":-110,"policy_id":"CLOSING_LINE_ARCHIVE_V1","evidence_class":"NOT_EVIDENCE","promotion_authority":False,"evidence_clock_authority":False,"window":"decision","captured_at":captured,"timestamp_semantics":"HTTP_RESPONSE_RECEIPT_UPPER_BOUND","raw_relative_path":"x","raw_sha256":SHA,"observation_id":"b"*64,"paired_two_sided":True,"historical_backfill":False}

class DirectDKForwardPairingTests(unittest.TestCase):
    def setUp(self): self.p=_load_policy(POLICY)
    def test_exact_nfl_decision_close_pair(self):
        rows=[row(outcome="A",point=-3),row(outcome="B",point=3),row(captured="2026-09-18T00:05:00Z",outcome="A",point=-3),row(captured="2026-09-18T00:05:00Z",outcome="B",point=3)]
        r=pair_rows(rows,self.p,"americanfootball_nfl")
        self.assertEqual(r["pair_count"],1); self.assertFalse(r["promotion_authority"]); self.assertFalse(r["model_p_created"])
    def test_threshold_drift_blocks_pair(self):
        rows=[row(outcome="A",point=-3),row(outcome="B",point=3),row(captured="2026-09-18T00:05:00Z",outcome="A",point=-3.5),row(captured="2026-09-18T00:05:00Z",outcome="B",point=3.5)]
        self.assertEqual(pair_rows(rows,self.p,"americanfootball_nfl")["pair_count"],0)
    def test_nfl_capture_before_frozen_checkpoint_is_excluded(self):
        rows=[row(captured="2026-09-15T13:59:59Z",start="2026-09-15T15:30:00Z",outcome="A",point=-3),row(captured="2026-09-15T13:59:59Z",start="2026-09-15T15:30:00Z",outcome="B",point=3)]
        self.assertEqual(pair_rows(rows,self.p,"americanfootball_nfl")["pair_count"],0)
    def test_cfb_before_sep19_game_is_excluded(self):
        rows=[row(sport="americanfootball_ncaaf",start="2026-09-18T23:00:00Z",outcome="A",point=-3),row(sport="americanfootball_ncaaf",start="2026-09-18T23:00:00Z",outcome="B",point=3)]
        self.assertEqual(pair_rows(rows,self.p,"americanfootball_ncaaf")["pair_count"],0)
    def test_backfill_and_authority_fail_closed(self):
        x=row(); x["historical_backfill"]=True
        with self.assertRaisesRegex(DirectDKPairingError,"BACKFILL_FORBIDDEN"): pair_rows([x],self.p,"americanfootball_nfl")
        bad=json.loads(POLICY.read_text()); bad["authority"]["promotion_authority"]=True
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            q=Path(td)/"p.json"; q.write_text(json.dumps(bad))
            with self.assertRaisesRegex(DirectDKPairingError,"AUTHORITY_FORBIDDEN"): _load_policy(q)

if __name__=="__main__": unittest.main()
