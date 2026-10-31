"""2025-fit / 2026-test check of the props calibration shift (method record; scratch paths)."""
import sys,json,numpy as np
sys.argv=['x'];exec(open('price.py').read().split("if __name__")[0])
B=json.load(open('bias.json'))
for m,v in B.items():
    cfg=ev.MARKETS[m];a=np.array(v)
    def rows(season):
        out=[]
        for s,mu,y in a[a[:,0]==season]:
            for off in (-0.15,0,0.15):
                L=np.floor(mu*(1+off))+0.5
                p=pr.p_over_for(ev,mu,cvs[m],cfg['count'],L,grid); out.append((p,float(y>L)))
        return np.array(out)
    tr,te=rows(2025),rows(2026)
    k=lambda r:(r[:,0]>.35)&(r[:,0]<.65)
    shift=(tr[k(tr),1]-tr[k(tr),0]).mean()
    raw=(te[k(te),1]-te[k(te),0]).mean(); fix=(te[k(te),1]-(te[k(te),0]+shift)).mean()
    bs=lambda r,s:np.mean((np.clip(r[k(r),0]+s,0,1)-r[k(r),1])**2)
    print(f"{m:10} shift fit on 2025 {shift:+.3f} | 2026 miss raw {raw:+.3f} -> fixed {fix:+.3f} | Brier 2026 raw {bs(te,0):.4f} fixed {bs(te,shift):.4f} n={k(te).sum()}")
