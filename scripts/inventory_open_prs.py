#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess
from pathlib import Path

CRITICAL_TERMS = ("truth", "gate", "devig", "de-vig", "pit", "promotion", "model", "engine", "pricing", "calibration")

def sh(*args, check=True):
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} :: {p.stderr.strip()}")
    return p

def main():
    pulls = json.loads(sh("gh","api","repos/{}/pulls?state=open&per_page=100".format(os.environ["GITHUB_REPOSITORY"])).stdout)
    rows=[]
    for pr in pulls:
        n=pr["number"]
        ref=f"refs/remotes/pr/{n}"
        fetch=sh("git","fetch","origin",f"refs/pull/{n}/head:{ref}",check=False)
        files_api=sh("gh","api",f"repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{n}/files?per_page=100",check=False)
        if fetch.returncode or files_api.returncode:
            rows.append((n,pr["title"],pr["head"]["ref"],pr["created_at"][:10],pr["draft"],"?", "UNCLEAR","fetch/api failure"))
            continue
        files=[x["filename"] for x in json.loads(files_api.stdout)]
        merge_base=sh("git","merge-base","origin/main",ref).stdout.strip()
        cherry=sh("git","cherry","origin/main",ref,check=False).stdout.splitlines()
        unique=[x for x in cherry if x.startswith("+ ")]
        if not unique:
            status="SUPERSEDED"; detail="no patch-unique commits vs main"
        else:
            main_changed=set(sh("git","diff","--name-only",f"{merge_base}..origin/main").stdout.splitlines())
            pr_changed=set(sh("git","diff","--name-only",f"{merge_base}..{ref}").stdout.splitlines())
            overlap=sorted(main_changed & pr_changed)
            if overlap:
                status="CONFLICTS"; detail="overlap since merge-base: "+", ".join(overlap[:8])
            else:
                status="CONTAINS-UNIQUE"; detail=f"{len(unique)} patch-unique commit(s)"
        critical = status=="CONTAINS-UNIQUE" and any(any(term in f.lower() for term in CRITICAL_TERMS) for f in files)
        if critical: detail="CRITICAL-UNIQUE: "+detail
        rows.append((n,pr["title"],pr["head"]["ref"],pr["created_at"][:10],pr["draft"],len(files),status,detail+"; files="+", ".join(files[:12])))

    counts={}
    for r in rows: counts[r[6]]=counts.get(r[6],0)+1
    print("SUMMARY",json.dumps(counts,sort_keys=True))
    print("| PR | Title | Branch | Created | Draft | Files | Classification | Detail |")
    print("|---:|---|---|---|:---:|---:|---|---|")
    for r in sorted(rows, reverse=True):
        safe=[str(x).replace("|","/") for x in r]
        print("| "+" | ".join(safe)+" |")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
