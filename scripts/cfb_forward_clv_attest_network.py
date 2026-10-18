#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.cfb_forward_clv_network_attestation import build_attestation_record, build_observation, discover_event_ids

UTC=timezone.utc
ESPN_SUMMARY="https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"

def fetch(event_id:str):
    url=ESPN_SUMMARY+"?"+urllib.parse.urlencode({"event":event_id})
    req=urllib.request.Request(url,headers={"User-Agent":"sportsedge-cfb-attestation"})
    with urllib.request.urlopen(req,timeout=30) as r: raw=r.read()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def write_once(path:Path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): return False
    path.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return True

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out-dir",default="."); args=ap.parse_args()
    out=Path(args.out_dir); root=out/"cfb_forward_clv"/"captures"; now=datetime.now(UTC); report=[]
    for event_id in discover_event_ids(root):
        summary,raw_sha=fetch(event_id); obs=build_observation(espn_event_id=event_id,summary=summary,observed_at=now,raw_sha256=raw_sha)
        stamp=now.strftime("%Y%m%dT%H%M%S%fZ"); op=out/"cfb_forward_clv"/"attestation_observations"/event_id/f"{stamp}.json"; write_once(op,obs)
        rows=[]
        for p in sorted(op.parent.glob("*.json")):
            try: rows.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception: pass
        rec=build_attestation_record(rows)
        rp=out/"cfb_forward_clv"/"attestation_records"/event_id/f"{stamp}.json"; write_once(rp,rec)
        report.append({"event_id":event_id,"status":rec.get("status")})
    print(json.dumps({"status":"SUCCESS","events":report,"promotion_authority":False},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
