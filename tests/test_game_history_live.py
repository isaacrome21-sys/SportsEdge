import json,tempfile,unittest
from datetime import date
from pathlib import Path
from sportsedge.game_history_live import fetch_prior_finals

def payload(day='2026-03-20'):
    return {'dates':[{'date':day,'games':[{'gamePk':1,'gameType':'R','officialDate':day,'status':{'abstractGameState':'Final'},'teams':{'away':{'team':{'id':1}},'home':{'team':{'id':2}}},'linescore':{'teams':{'away':{'runs':3},'home':{'runs':4}},'innings':[{'num':1,'away':{'runs':0},'home':{'runs':1}}]}}]}]}

class Tests(unittest.TestCase):
    def test_cache_row_is_normalized_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'schedule_2026-03-01_2026-03-31.json'; p.write_text(json.dumps(payload()))
            games,excluded=fetch_prior_finals(through_date=date(2026,3,31),cache_dir=td,start_year=2026)
        self.assertEqual(len(games),1); self.assertEqual(games[0]['officialDate'],'2026-03-20'); self.assertEqual(games[0]['away_fi'],0); self.assertEqual(games[0]['home_fi'],1)

    def test_out_of_range_cached_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'schedule_2026-03-01_2026-03-31.json'; p.write_text(json.dumps(payload('2026-04-01')))
            games,excluded=fetch_prior_finals(through_date=date(2026,3,31),cache_dir=td,start_year=2026)
        self.assertEqual(games,[]); self.assertTrue(any(x.get('reason_code')=='SOURCE_RANGE_VIOLATION' for x in excluded))

if __name__=='__main__': unittest.main()
