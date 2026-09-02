#!/usr/bin/env python3
"""Persist canonical V8 market snapshots to the SportsEdge data branch."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time

DATA_BRANCH="data"; WORKTREE=Path(".v8-market-data-branch")

class PersistError(RuntimeError): pass

def _run(args,*,cwd=None,check=True):
    p=subprocess.run(args,cwd=None if cwd is None else str(cwd),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if p.stdout: print(p.stdout,end="")
    if check and p.returncode!=0: raise PersistError(f"command failed ({p.returncode}): {' '.join(args)}")
    return p

def persist(source: Path) -> dict:
    manifest_path=source/"manifest.json"
    if not manifest_path.is_file(): raise PersistError("V8 market manifest missing")
    manifest=json.loads(manifest_path.read_text())
    if int(manifest.get("rows_written") or 0)<=0:
        return {"status":"NO_V8_ROWS_TO_PERSIST","rows_written":0,"skipped_pre_epoch":manifest.get("skipped_pre_epoch")}
    if WORKTREE.exists():
        _run(["git","worktree","remove","--force",str(WORKTREE)],check=False)
        if WORKTREE.exists(): shutil.rmtree(WORKTREE)
    _run(["git","fetch","origin",DATA_BRANCH]); _run(["git","worktree","add","--detach",str(WORKTREE),"FETCH_HEAD"])
    try:
        dest=WORKTREE/"archive/v8_forward/market_snapshots"
        dest.mkdir(parents=True,exist_ok=True)
        for day in source.glob("20??-??-??"):
            if not day.is_dir(): continue
            day_dest=dest/day.name; day_dest.mkdir(parents=True,exist_ok=True)
            for file in day.iterdir():
                if not file.is_file(): continue
                target=day_dest/file.name
                if target.exists() and target.read_bytes()!=file.read_bytes():
                    # JSONL is append-only at source. Merge by unique exact line rather than overwrite.
                    if file.suffix==".jsonl":
                        existing=set(target.read_text().splitlines()); incoming=file.read_text().splitlines()
                        merged=list(target.read_text().splitlines())
                        for line in incoming:
                            if line and line not in existing: merged.append(line); existing.add(line)
                        target.write_text("\n".join(merged)+("\n" if merged else ""))
                    else: raise PersistError(f"immutable V8 market collision:{target}")
                elif not target.exists(): shutil.copy2(file,target)
        manifest_dir=WORKTREE/"archive/v8_forward/market_manifests"; manifest_dir.mkdir(parents=True,exist_ok=True)
        digest=str(manifest.get("manifest_sha256") or "missing"); mtarget=manifest_dir/f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}_{digest}.json"
        shutil.copy2(manifest_path,mtarget)
        _run(["git","config","user.name","sportsedge-v8-evidence-bot"],cwd=WORKTREE); _run(["git","config","user.email","sportsedge-v8-evidence-bot@users.noreply.github.com"],cwd=WORKTREE)
        _run(["git","add","archive/v8_forward"],cwd=WORKTREE)
        diff=_run(["git","diff","--cached","--quiet"],cwd=WORKTREE,check=False)
        if diff.returncode==0: return {"status":"ALREADY_PERSISTED","rows_written":manifest["rows_written"]}
        if diff.returncode!=1: raise PersistError("unable to inspect staged evidence")
        _run(["git","commit","-m",f"evidence: persist MLB V8 market snapshots {manifest.get('manifest_sha256','')[:12]}"],cwd=WORKTREE)
        for attempt in range(1,6):
            push=_run(["git","push","origin",f"HEAD:{DATA_BRANCH}"],cwd=WORKTREE,check=False)
            if push.returncode==0: return {"status":"PERSISTED","rows_written":manifest["rows_written"],"manifest_sha256":manifest.get("manifest_sha256")}
            _run(["git","fetch","origin",DATA_BRANCH],cwd=WORKTREE)
            reb=_run(["git","rebase",f"origin/{DATA_BRANCH}"],cwd=WORKTREE,check=False)
            if reb.returncode!=0:
                _run(["git","rebase","--abort"],cwd=WORKTREE,check=False); raise PersistError("data branch rebase conflict")
            time.sleep(attempt)
        raise PersistError("data branch push failed")
    finally:
        _run(["git","worktree","remove","--force",str(WORKTREE)],check=False)

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--source",default="artifacts/v8_forward"); args=p.parse_args(argv); result=persist(Path(args.source)); print(json.dumps(result,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
