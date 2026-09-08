"""Read-only deterministic reproduction of ATTEMPT_001; no promotion writer."""
from pathlib import Path
import argparse, subprocess
import hashlib,json,sys
import numpy as np
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--frozen-repo', type=Path, required=True)
parser.add_argument('--attempt-bundle', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args=parser.parse_args()
repo=args.frozen_repo.resolve()
base=args.attempt_bundle.resolve()
old=json.loads((base/'nfl_production_validation.json').read_text())
actual_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
if actual_head != old['code_git_sha']:
    raise SystemExit('BLOCKED_FROZEN_CODE_SHA_MISMATCH')
if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo,text=True).strip():
    raise SystemExit('BLOCKED_FROZEN_CODE_DIRTY')
sys.path.insert(0,str(repo))
from scripts import run_nfl_production_validation as production
from sportsedge.sports.nfl.m2 import fit_nfl_m2_score_model
from sportsedge.core.walkforward.season import season_walk_forward
sources=base/'recovered_sources'
manifest=json.loads((base/'nfl_source_manifest.json').read_text())
paths={}
for source in manifest['sources']:
 name=source['name']
 path=base/'sources/games.csv' if name=='schedule' else repo/'config/nfl_historical_starter_overrides.json' if name=='starter_overrides' else sources/source['uri'].rsplit('/',1)[-1]
 if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
  raise SystemExit('BLOCKED_EXACT_SOURCE_UNAVAILABLE:'+name)
 paths[name]=path
print('All source hashes verified',flush=True)
schedule=production.normalize_nfl_rows(production.parse_schedule_csv(paths['schedule'].read_text(encoding='utf-8-sig')),range(2016,2026))
pbp=[]; participation=[]; depth=[]
for target,prefix,fields in [(pbp,'pbp_',production._PBP_FIELDS),(participation,'participation_',production._PARTICIPATION_FIELDS),(depth,'depth_',production._DEPTH_FIELDS)]:
 production._extend(target,[p for k,p in sorted(paths.items()) if k.startswith(prefix)],fields)
 print(prefix,len(target),flush=True)
stadiums,_=production.bridge_preopening_away_origins(schedule,production._read_projected(paths['stadiums'],production._STADIUM_FIELDS))
curves=production.fit_nfl_prior_decay_curves(schedule,pbp,min_train_seasons=2,weeks=range(1,7))
depth,_=production.apply_pinned_starting_qb_overrides(schedule,depth,json.loads(paths['starter_overrides'].read_text()))
exclusions={}
rows=production.build_nfl_m2_history_rows(schedule,pbp,participation,depth,stadiums,prior_decay_curves=curves,neutral_site_policy='exclude_from_evaluation',exclusion_report=exclusions)
old=json.loads((base/'nfl_production_validation.json').read_text())
assert len(rows)==old['point_in_time_history_row_count'], 'REPRODUCTION_ROW_COUNT_MISMATCH'
print('Historical rows reproduced',len(rows),flush=True)
records=[];summaries=[]
def metrics(actual,pred):
 residual=actual-pred
 return {'n':len(actual),'actual_mean':float(np.mean(actual)),'predicted_mean':float(np.mean(pred)),'mean_residual':float(np.mean(residual)),'residual_rmse':float(np.sqrt(np.mean(residual**2))),'actual_variance':float(np.var(actual)),'predicted_variance':float(np.var(pred))}
for fold in season_walk_forward(rows,season_key='season',min_train_seasons=2):
 model=fit_nfl_m2_score_model(fold.train_rows,ridge_alpha=10.0)
 actual=[];pred=[]
 for r in fold.test_rows:
  margin,total=model.predict(r); observed=float(r['home_score'])+float(r['away_score'])
  actual.append(observed);pred.append(total)
  records.append({'game_id':r['game_id'],'test_season':fold.test_season,'train_seasons':model.train_seasons,'actual_total':observed,'predicted_total':total,'actual_margin':float(r['home_score'])-float(r['away_score']),'predicted_margin':margin})
 actual=np.array(actual);pred=np.array(pred);cuts=np.quantile(actual,[1/3,2/3]);buckets=[]
 for label,mask in [('low',actual<=cuts[0]),('middle',(actual>cuts[0])&(actual<=cuts[1])),('high',actual>cuts[1])]:
  if mask.any():buckets.append({'bucket':label,**metrics(actual[mask],pred[mask])})
 summaries.append({'season':fold.test_season,'train_seasons':model.train_seasons,'train_residual_total_sigma':model.total_sigma,'realized_total_bucket_cutoffs':cuts.tolist(),'aggregate':metrics(actual,pred),'buckets':buckets})
 print('Diagnostic fold',fold.test_season,'complete',flush=True)
result={'status':'DIAGNOSTIC_ONLY','attempt':'ATTEMPT_001','frozen_code_git_sha':old['code_git_sha'],'source_manifest_sha256':manifest['manifest_sha256'],'original_attempt_changed':False,'promotion_eligible':False,'exclusions_by_season':exclusions,'folds':summaries,'heldout_predictions':records,'limitation':'Conditioning on realized outcomes creates residual patterns even for valid conditional-mean forecasts. These retrospective buckets alone do not prove shrinkage or noisy features and must not select a new model on this holdout.'}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2)+'\n')
