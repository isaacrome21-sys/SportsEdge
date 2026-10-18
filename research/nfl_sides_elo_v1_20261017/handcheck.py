"""Independent recomputation (no evaluator import): Elo replay + pooled moneyline log loss."""
import csv, math, sys
rows=[r for r in csv.DictReader(open(sys.argv[1])) if int(r["season"])>=2015 and r["home_score"]!=""]
rows.sort(key=lambda r:(r["gameday"],r["gametime"] or "00:00",r["game_id"]))
E={}; g=lambda t:E.get(t,1505.0); season=None; L=[]; prev=None; pend=[]
def flush():
    for h,a,s in pend: E[h]=g(h)+s; E[a]=g(a)-s
    pend.clear()
for r in rows:
    k=(r["gameday"],r["gametime"])
    if k!=prev: flush(); prev=k
    s=int(r["season"])
    if season is not None and s!=season:
        for t in list(E): E[t]+= (1505-E[t])/3
    season=s
    h,a=r["home_team"],r["away_team"]; d=g(h)+(0 if r["location"]=="Neutral" else 48)-g(a)
    p=1/(1+10**(-d/400)); m=float(r["home_score"])-float(r["away_score"])
    if 2018<=s<=2025 and m!=0 and r["home_moneyline"] and r["away_moneyline"]:
        imp=lambda x:100/(x+100) if x>0 else -x/(-x+100)
        ph,pa=imp(float(r["home_moneyline"])),imp(float(r["away_moneyline"])); pm=ph/(ph+pa); y=1 if m>0 else 0
        L.append((-math.log(p if y else 1-p), -math.log(pm if y else 1-pm)))
    res,mult=(0.5,1.0) if m==0 else ((1.0 if m>0 else 0.0), math.log(abs(m)+1)*2.2/(0.001*(d if m>0 else -d)+2.2))
    pend.append((h,a,20*mult*(res-p)))
print(len(L), sum(x for x,_ in L)/len(L), sum(y for _,y in L)/len(L))
