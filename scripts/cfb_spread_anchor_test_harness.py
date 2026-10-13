# Copied pure anchor functions from PR #1954 blob 0d9df734b0043d56c863482c9c37bb7c8b4b9681.
# The evaluate(), slope CI and OOS fold math must not be tuned between feature attempts.
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path

FIRST_TEST_SEASON = 2021
T_CRITICAL = {3:3.182446, 4:2.776445, 5:2.570582, 6:2.446912,
              7:2.364624, 8:2.306004, 9:2.262157, 10:2.228139}

def assemble(predictions, cache):
    out, seen = [], set()
    for gid, p in predictions.items():
        year=int(p["season"])
        line=(cache.get(f"lines_{year}") or {}).get(str(gid))
        if not isinstance(line,dict) or line.get("spread") is None: continue
        if str(gid) in seen: raise ValueError("DUPLICATE_GAME")
        seen.add(str(gid))
        m=-float(line["spread"])  # CFBD home handicap reversed to expected margin
        model=float(p["model_margin"])
        actual=float(p["actual_margin"])
        if not all(map(math.isfinite,(m,model,actual))) or abs(m)>80: continue
        out.append({"game_id":str(gid),"season":year,"x":model-m,"y":actual-m,
                    "market_margin":m,"raw_margin":model,"actual_margin":actual})
    return sorted(out,key=lambda r:(r["season"],r["game_id"]))

def basic_ols(rows):
    n=len(rows)
    mx=sum(r["x"] for r in rows)/n
    my=sum(r["y"] for r in rows)/n
    sxx=sum((r["x"]-mx)**2 for r in rows)
    if sxx<1e-12: raise ValueError("NO_RAW_MARGIN_VARIANCE")
    w=sum((r["x"]-mx)*(r["y"]-my) for r in rows)/sxx
    return {"intercept":my-w*mx,"weight":w,"n":n}

def ols(rows):
    if len(rows)<300 or len({r["season"] for r in rows})<3:
        raise ValueError("TRAINING_INSUFFICIENT")
    return basic_ols(rows)

def errors(rows,b,w):
    e=[r["y"]-b-w*r["x"] for r in rows]
    return (sum(v*v for v in e),sum(abs(v) for v in e))

def clustered_slope_ci(rows):
    """CR1 cluster-robust t interval; each season is an independent cluster.

    The pooled heldout slope is a *diagnostic*, never a deployable fit.
    """
    years=sorted({r["season"] for r in rows})
    g=len(years)
    if g<4 or g-1 not in T_CRITICAL: raise ValueError("TOO_FEW_SEASON_CLUSTERS")
    fit=basic_ols(rows)
    n=len(rows)
    sx=sum(r["x"] for r in rows)
    sx2=sum(r["x"]**2 for r in rows)
    det=n*sx2-sx*sx
    v0,v1=-sx/det,n/det
    meat=0.
    for year in years:
        rec=[r for r in rows if r["season"]==year]
        e=[r["y"]-fit["intercept"]-fit["weight"]*r["x"] for r in rec]
        s0=sum(e)
        s1=sum(a*r["x"] for a,r in zip(e,rec))
        meat+=(v0*s0+v1*s1)**2
    se=math.sqrt(max(0.,g/(g-1)*(n-1)/(n-2)*meat))
    half=T_CRITICAL[g-1]*se
    return {**fit,"cluster_se":se,"ci95_low":fit["weight"]-half,
            "ci95_high":fit["weight"]+half,"clusters":g,
            "method":"CR1 season-cluster t(G-1) 95% CI; small G cautioned"}

def evaluate(paired,start=FIRST_TEST_SEASON):
    folds,held=[],[]
    totals={f"{kind}_{metric}":0. for kind in ("market","offset","anchor")
            for metric in ("sq","abs")}
    for year in sorted({r["season"] for r in paired}):
        if year<start: continue
        train=[r for r in paired if r["season"]<year]
        test=[r for r in paired if r["season"]==year]
        if not test: continue
        fit=ols(train)
        last=max(r["season"] for r in train)
        if last>=year: raise ValueError("LOOKAHEAD")
        mean_y=sum(r["y"] for r in train)/len(train)
        metrics={}
        for name,b,w in (("market",0.,0.),("offset",mean_y,0.),
                         ("anchor",fit["intercept"],fit["weight"])):
            sq,ab=errors(test,b,w)
            totals[name+"_sq"]+=sq
            totals[name+"_abs"]+=ab
            metrics[name+"_rmse"]=round(math.sqrt(sq/len(test)),4)
            metrics[name+"_mae"]=round(ab/len(test),4)
        folds.append({"season":year,"train_n":len(train),"test_n":len(test),
                      "max_train_season":last,"intercept":round(fit["intercept"],6),
                      "weight":round(fit["weight"],6),**metrics})
        held+=test
    if not folds: raise ValueError("NO_WALK_FORWARD_TESTS")
    n=len(held)
    pooled={}
    for name in ("market","offset","anchor"):
        pooled[name+"_rmse"]=round(math.sqrt(totals[name+"_sq"]/n),6)
        pooled[name+"_mae"]=round(totals[name+"_abs"]/n,6)
    pooled["n"]=n
    pooled["improvement_rmse_vs_market"]=round(pooled["market_rmse"]-pooled["anchor_rmse"],6)
    pooled["improvement_rmse_vs_intercept_only"]=round(pooled["offset_rmse"]-pooled["anchor_rmse"],6)
    diag=clustered_slope_ci(held)
    includes_zero=diag["ci95_low"]<=0.<=diag["ci95_high"]
    return {"schema":"CFB_SPREAD_ANCHOR_WALKFORWARD_RESEARCH_V1",
            "status":"NO_PROVEN_SPREAD_EDGE_LANE_OFF" if includes_zero else
                     "DIAGNOSTIC_SIGNAL_NOT_FORWARD_BETTING_PROOF",
            "training_method":"Score model trained on seasons < test season; "
                              "anchor fit on past-only prior-season model forecasts",
            "market_reference":"CFBD_RECONSTRUCTED_HISTORICAL_CLOSE_PROXY",
            "folds":folds,"pooled_oos":pooled,
            "heldout_residual_weight_diagnostic":{k:round(v,6) if isinstance(v,float) else v
                                                   for k,v in diag.items()},
            "ci_includes_zero":includes_zero,
            "authority":{"runtime_changed":False,"model_p":False,"pricing":False,
                         "bets":False,"official":False,"promotion":False,
                         "forward_validated":False,"no_backfill":True}}


def passes_feature_acceptance(report):
    """Separate decision rule; no changes to #1954's pure anchor-test math."""
    folds=[r["season"] for r in report["folds"]]
    ci=report["heldout_residual_weight_diagnostic"]
    rmse=report["pooled_oos"]
    return (folds==[2021,2022,2023,2024,2025] and
            ci["weight"]>0 and ci["ci95_low"]>0 and
            rmse["anchor_rmse"]<rmse["market_rmse"])
