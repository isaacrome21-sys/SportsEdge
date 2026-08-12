#!/usr/bin/env python3
"""Fit/evaluate the predeclared BB-v5 narrow 1.5-walk calibration layer.

Governing documents:
- audit/BB_V5_PREDECLARED_PROTOCOL_2026-08-12.md
- audit/BB_V5_FUNCTIONAL_FORM_LOCK_2026-08-12.md

This script preserves the BB-v4 feature builder and frozen threshold models. Only
P(BB > 1.5) receives the predeclared band-aware monotone calibration layer.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

import scripts.rebuild_pitcher_bb_v4 as v4
import scripts.rebuild_pitcher_bb_v4_1 as v41

BANDS = [(-math.inf, .06, "lt_0.06"), (.06,.08,"0.06_0.08"), (.08,.10,"0.08_0.10"), (.10,.12,"0.10_0.12"), (.12,math.inf,"ge_0.12")]
V4_ARTIFACT = Path(os.getenv("SPORTSEDGE_BB_V4_ARTIFACT", "phase6_artifacts/sportsedge_pitcher_bb_v4.joblib"))
OUTDIR = Path(os.getenv("SPORTSEDGE_BB_V5_OUTDIR", "artifacts"))

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for c in iter(lambda:f.read(1<<20),b''): h.update(c)
    return h.hexdigest()

def logit(p):
    p=np.clip(np.asarray(p,float),1e-6,1-1e-6)
    return np.log(p/(1-p))

def metric(p,y):
    p=np.asarray(p,float); y=np.asarray(y,int); n=len(y)
    pred=float(p.mean()); actual=float(y.mean())
    se=math.sqrt(max(actual*(1-actual),1e-9)/max(n,1))
    z=abs(pred-actual)/se
    brier=float(np.mean((p-y)**2))
    ll=float(-np.mean(y*np.log(np.clip(p,1e-9,1))+(1-y)*np.log(np.clip(1-p,1e-9,1))))
    return {"n":int(n),"pred":pred,"actual":actual,"gap_pp":100*(pred-actual),"z":z,"brier":brier,"log_loss":ll}

def buckets(p,y):
    out=[]
    for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        m=(p>=lo)&(p<hi)
        if int(m.sum())>=30: out.append({"lo":lo,"hi":hi,**metric(p[m],y[m])})
    return out

def band_index(x: float) -> int:
    for i,(lo,hi,_) in enumerate(BANDS):
        if lo <= x < hi: return i
    raise AssertionError(x)

def band_report(p,y,pit):
    out=[]
    for i,(lo,hi,name) in enumerate(BANDS):
        m=np.array([band_index(float(x))==i for x in pit],bool)
        if m.any(): out.append({"band":name,"lo":None if not math.isfinite(lo) else lo,"hi":None if not math.isfinite(hi) else hi,**metric(p[m],y[m])})
    return out

def fit_one(x,y):
    if len(np.unique(y))<2: raise RuntimeError("BB_V5_BAND_SINGLE_CLASS")
    model=LogisticRegression(C=100.0,solver='lbfgs').fit(logit(x).reshape(-1,1),y)
    slope=float(model.coef_[0,0])
    if not math.isfinite(slope) or slope <= 0: raise RuntimeError("BB_V5_NON_MONOTONE_SLOPE")
    return model

def apply_models(base_p,pit,models):
    out=np.empty(len(base_p),float)
    for i,x in enumerate(pit):
        bi=band_index(float(x)); m=models[str(bi)]
        out[i]=m.predict_proba(logit([base_p[i]]).reshape(-1,1))[0,1]
    return np.clip(out,.001,.999)

def main():
    protocol=Path('audit/BB_V5_PREDECLARED_PROTOCOL_2026-08-12.md')
    form=Path('audit/BB_V5_FUNCTIONAL_FORM_LOCK_2026-08-12.md')
    if not protocol.exists() or not form.exists(): raise RuntimeError('BB_V5_PREDECLARATION_MISSING')
    if not V4_ARTIFACT.exists(): raise RuntimeError('BB_V4_FROZEN_ARTIFACT_MISSING')
    frozen=joblib.load(V4_ARTIFACT)
    if str((frozen.get('metadata') or {}).get('version','')).split('_')[0:3] != ['PITCHER','BB','V4']:
        raise RuntimeError('BB_V4_ARTIFACT_VERSION_INVALID')

    root=Path(os.getenv('SPORTSEDGE_BB_REBUILD_CACHE','.cache/sportsedge/bb-rebuild-v5'))
    games, excluded=v41.fetch_schedule_strict(root/'schedule')
    v4.old.ensure_boxes(games,root/'boxscores')
    X,walks,years,ids=v4.build_cutoff(games,root/'boxscores')
    by_date={int(g['game_pk']):g['officialDate'] for g in games}
    dates=np.array([by_date[int(identity[0])] for identity in ids])
    months=np.array([date.fromisoformat(d).month for d in dates],int)
    pit=X[:,0]
    y=(walks>1.5).astype(int)

    base_model=frozen['models']['1.5']['model']; base_cal=frozen['models']['1.5']['calibrator']
    raw=base_model.predict_proba(X)[:,1]
    base_p=base_cal.predict_proba(logit(raw).reshape(-1,1))[:,1]
    cal=years==2025; post=years==2026

    cf=np.full(len(X),np.nan); fold_meta=[]
    for month in sorted(set(months[cal])):
        tr=cal & (months!=month); te=cal & (months==month); models={}
        for bi in range(len(BANDS)):
            m=tr & np.array([band_index(float(x))==bi for x in pit],bool)
            models[str(bi)]=fit_one(base_p[m],y[m])
        cf[te]=apply_models(base_p[te],pit[te],models)
        fold_meta.append({"heldout_month":int(month),"n":int(te.sum())})
    if np.isnan(cf[cal]).any(): raise RuntimeError('BB_V5_CROSSFIT_INCOMPLETE')

    cf_metric=metric(cf[cal],y[cal]); base_cal_metric=metric(base_p[cal],y[cal])
    cf_buckets=buckets(cf[cal],y[cal]); cf_bands=band_report(cf[cal],y[cal],pit[cal])
    a_pass=(cf_metric['z']<=2.0 and max([b['z'] for b in cf_buckets] or [0])<=2.5 and
            max([b['z'] for b in cf_bands if b['n']>=75] or [0])<=2.5 and
            cf_metric['brier']<=base_cal_metric['brier']+.001 and cf_metric['log_loss']<=base_cal_metric['log_loss']+.002)

    final_models={}
    for bi in range(len(BANDS)):
        m=cal & np.array([band_index(float(x))==bi for x in pit],bool)
        final_models[str(bi)]=fit_one(base_p[m],y[m])
    post_p=apply_models(base_p[post],pit[post],final_models)
    post_metric=metric(post_p,y[post]); post_buckets=buckets(post_p,y[post]); post_bands=band_report(post_p,y[post],pit[post])
    base_post_bands=band_report(base_p[post],y[post],pit[post])
    pb={r['band']:r for r in post_bands}; bb={r['band']:r for r in base_post_bands}
    good='0.06_0.08'; bad='0.08_0.10'
    good_worsen=abs(pb[good]['gap_pp'])-abs(bb[good]['gap_pp'])
    bad_improve=abs(bb[bad]['gap_pp'])-abs(pb[bad]['gap_pp'])
    b_pass=(post_metric['z']<=2.0 and max([b['z'] for b in post_buckets] or [0])<=2.5 and
            max([b['z'] for b in post_bands if b['n']>=75] or [0])<=2.5 and good_worsen<=1.0 and bad_improve>=2.0)

    report={
        'schema_version':'pitcher_bb_v5_narrow_calibration_v1',
        'governing_protocol_sha256':sha256(protocol),
        'functional_form_lock_sha256':sha256(form),
        'frozen_bb_v4_sha256':sha256(V4_ARTIFACT),
        'source_range_policy':'EVERY_RESPONSE_AND_CACHE_ROW_MUST_MATCH_REQUESTED_INTERVAL',
        'excluded_games':excluded,
        'rows':int(len(X)), 'rows_2025':int(cal.sum()), 'rows_2026_through_aug10':int(post.sum()),
        'section_a_2025_crossfit':{'label':'MODEL_DEVELOPMENT_CROSSFIT_EVIDENCE','pass':bool(a_pass),'candidate':cf_metric,'bb_v4':base_cal_metric,'buckets':cf_buckets,'bands':cf_bands,'folds':fold_meta},
        'section_b_2026_confirmatory':{'label':'POST_HOC_CONFIRMATORY_NOT_PRISTINE_HOLDOUT','pass':bool(b_pass),'candidate':post_metric,'buckets':post_buckets,'bands':post_bands,'bb_v4_bands':base_post_bands,'good_band_abs_gap_worsen_pp':good_worsen,'bad_band_abs_gap_improvement_pp':bad_improve},
        'other_thresholds_path':'EXACT_FROZEN_BB_V4_OBJECTS_UNCHANGED',
        'development_pass':bool(a_pass and b_pass),
        'deployment_eligible':False,
        'deployment_block_reason':'FORWARD_SHADOW_GATE_PENDING' if a_pass and b_pass else 'BB_V5_DEVELOPMENT_GATE_FAIL',
    }
    OUTDIR.mkdir(parents=True,exist_ok=True)
    joblib.dump({'version':'PITCHER_BB_V5_NARROW_CALIBRATION','base_artifact_sha256':sha256(V4_ARTIFACT),'base_models':frozen['models'],'band_calibrators_1.5':final_models,'bands':BANDS,'feature_names':tuple(v4.FEATURES),'pit_bb_hist_index':0,'protocol_sha256':sha256(protocol),'functional_form_lock_sha256':sha256(form)},OUTDIR/'sportsedge_pitcher_bb_v5.joblib')
    (OUTDIR/'pitcher_bb_v5_validation.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'section_a_pass':a_pass,'section_b_pass':b_pass,'development_pass':a_pass and b_pass,'rows_2025':int(cal.sum()),'rows_2026':int(post.sum()),'bad_band_improve_pp':bad_improve},indent=2,sort_keys=True))
    return 0 if (a_pass and b_pass) else 2

if __name__=='__main__': raise SystemExit(main())
