#!/usr/bin/env python3
"""t272 reproducibility: fit CFB_MARGIN_MODEL coefficients on the 2024 season
(actual results only; closing lines printed for reference, never fitted).
Run after build_eval_rows.py in the same directory."""
import json,numpy as np
rows=json.load(open("eval_rows.json"))
tr=[r for r in rows if r["season"]==2024]
X=np.array([[0 if r["neutral"] else 1, r["h_mm"]-r["a_mm"]] for r in tr]); y=np.array([r["margin"] for r in tr])
c,*_=np.linalg.lstsq(X,y,rcond=None); res=y-X@c
print("margin hfa,k",c,"sd",res.std(ddof=2))
Xt=np.array([[1,(r["h_mt"]+r["a_mt"])/2] for r in tr]); yt=np.array([r["points"] for r in tr])
ct,*_=np.linalg.lstsq(Xt,yt,rcond=None); rt=yt-Xt@ct
print("total a,b",ct,"sd",rt.std(ddof=2))
# market reference
print("close spread sd of resid", np.std([r["margin"]+r["spread_home"] for r in tr]), "close total resid sd",np.std([r["points"]-r["total"] for r in tr]))
print("mean points",yt.mean(),"mean close total",np.mean([r["total"] for r in tr]))
