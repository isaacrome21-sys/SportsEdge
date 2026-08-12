import json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from sportsedge.game_card_pipeline import run_game_card
from sportsedge.game_live_features import RUN_FEATURES, FI_FEATURES

class RunModel:
    def predict(self, X): return np.array([4.0, 4.5])
class ProbModel:
    def predict_proba(self, X):
        n=len(X); return np.column_stack([np.full(n,.45),np.full(n,.55)])
class Cal:
    def predict_proba(self, X):
        n=len(X); return np.column_stack([np.full(n,.45),np.full(n,.55)])

def artifacts():
    game={'version':'GAME_SCORE_V4_CUTOFF_CORRECT','run_features':RUN_FEATURES,'run_model':RunModel(),'away_scale':1.0,'home_scale':1.0,'alpha':0.1,'shared_sigma':0.1,'ml_calibrator':Cal()}
    nrfi={'version':'NRFI_V4_CUTOFF_CORRECT','features':FI_FEATURES,'model':ProbModel(),'calibrator':Cal()}
    return game,nrfi

def quote(market,side,line,retrieved_at=None):
    return {'game_id':'123','period':'1ST' if market in {'NRFI','YRFI'} else 'FG','market':market,'side':side,'line':line,'book_key':'draftkings','retrieved_at':retrieved_at or datetime(2026,8,12,12,0,tzinfo=timezone.utc),'is_alternate':False,'raw_market_name':'fixture','american_odds':-110,'ttl_seconds':600}

class Tests(unittest.TestCase):
    def test_all_five_game_markets_reach_model_path(self):
        game,nrfi=artifacts(); now=datetime(2026,8,12,12,1,tzinfo=timezone.utc)
        rows=[{'game_id':'123','run_rows':[[4.4,4.4,4.4,4.4,4.4,0,4,0,0,1],[4.4,4.4,4.4,4.4,4.4,1,4,0,0,1]],'fi_row':[.28]*13+[4,4,0,1]}]
        qs=[quote('MONEYLINE','HOME',None),quote('RUN_LINE','HOME',-1.5),quote('TOTALS','OVER',8.5),quote('NRFI','UNDER',.5),quote('YRFI','OVER',.5)]
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/'deployments.json'; reg.write_text(json.dumps({'schema_version':1,'markets':{m:{'eligible':True,'stage':'DEPLOYED','reason':'test'} for m in ['MONEYLINE','RUN_LINE','TOTALS','NRFI','YRFI']}}))
            out=run_game_card(feature_rows=rows,quotes=qs,game_score_artifact=game,nrfi_artifact=nrfi,ingestion_now=now,finalization_now=now,registry_path=str(reg))
        self.assertEqual([x.market for x in out],['MONEYLINE','RUN_LINE','TOTALS','NRFI','YRFI'])
        self.assertTrue(all(x.model_p is not None for x in out))
        self.assertTrue(all(x.bet_status in {'PASS','OFFICIAL_BET'} for x in out))

    def test_real_registry_deploys_game_market_but_stale_price_fails_closed_before_model(self):
        game,nrfi=artifacts(); now=datetime(2026,8,12,12,1,tzinfo=timezone.utc)
        rows=[{'game_id':'123','run_rows':[[4.4,4.4,4.4,4.4,4.4,0,4,0,0,1],[4.4,4.4,4.4,4.4,4.4,1,4,0,0,1]],'fi_row':[.28]*13+[4,4,0,1]}]
        fresh=run_game_card(feature_rows=rows,quotes=[quote('MONEYLINE','HOME',None)],game_score_artifact=game,nrfi_artifact=nrfi,ingestion_now=now,finalization_now=now)
        self.assertIn(fresh[0].bet_status,{'PASS','OFFICIAL_BET'}); self.assertIsNotNone(fresh[0].model_p); self.assertNotIn('DEPLOYMENT_BLOCKED',fresh[0].reason)
        stale_quote=quote('MONEYLINE','HOME',None,retrieved_at=now-timedelta(seconds=601))
        stale=run_game_card(feature_rows=rows,quotes=[stale_quote],game_score_artifact=game,nrfi_artifact=nrfi,ingestion_now=now,finalization_now=now)
        self.assertEqual(stale[0].bet_status,'BLOCKED'); self.assertIsNone(stale[0].model_p); self.assertIn('price is stale',stale[0].reason.lower())

if __name__=='__main__': unittest.main()
