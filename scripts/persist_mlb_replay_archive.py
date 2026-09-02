#!/usr/bin/env python3
"""Persist a completed MLB replay archive to the immutable data branch."""
from __future__ import annotations
import argparse, json, shutil, subprocess, time
from pathlib import Path

DATA_BRANCH="data"; WORKTREE=Path(".replay-data-branch")
class PersistError(RuntimeError): pass

def _run(args,*,cwd=None,check=True):
    p=subprocess.run(args,cwd=None if cwd is None else str(cwd),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if p.stdout: print(p.stdout,end="")
    if check and p.returncode!=0: raise PersistError(f"command failed ({p.returncode}): {' '.join(args)}")
    return p

def persist(source: Path) -> dict:
    manifest_path=source/"manifest.json"
    if not manifest_path.is_file(): raise PersistError("replay manifest missing")
    manifest=json.loads(manifest_path.read_text()); digest=str(manifest.get("manifest_sha256") or "")
    if len(digest)!=64: raise PersistError("replay manifest hash missing")
    if WORKTREE.exists():
        _run(["git","worktree","remove","--force",str(WORKTREE)],check=False)
        if WORKTREE.exists(): shutil.rmtree(WORKTREE)
    _run(["git","fetch","origin",DATA_BRANCH]); _run(["git","worktree","add","--detach",str(WORKTREE),"FETCH_HEAD"])
    try:
        dest=WORKTREE/"archive/mlb_replay/2026_mar_aug"/digest
        if dest.exists(): return {"status":"ALREADY_PERSISTED","manifest_sha256":digest,"path":str(dest.relative_to(WORKTREE))}
        dest.parent.mkdir(parents=True,exist_ok=True); shutil.copytree(source,dest)
        _run(["git","config","user.name","sportsedge-replay-bot"],cwd=WORKTREE); _run(["git","config","user.email","sportsedge-replay-bot@users.noreply.github.com"],cwd=WORKTREE)
        _run(["git","add",str(dest.relative_to(WORKTREE))],cwd=WORKTREE); _run(["git","commit","-m",f"evidence: persist MLB March-August replay {digest[:12]}"],cwd=WORKTREE)
        for attempt in range(1,6):
            push=_run(["git","push","origin",f"HEAD:{DATA_BRANCH}"],cwd=WORKTREE,check=False)
            if push.returncode==0: return {"status":"PERSISTED","manifest_sha256":digest,"path":str(dest.relative_to(WORKTREE))}
            _run(["git","fetch","origin",DATA_BRANCH],cwd=WORKTREE); reb=_run(["git","rebase",f"origin/{DATA_BRANCH}"],cwd=WORKTREE,check=False)
            if reb.returncode!=0:
                _run(["git","rebase","--abort"],cwd=WORKTREE,check=False); raise PersistError("data branch rebase conflict")
            time.sleep(attempt)
        raise PersistError("data branch push failed")
    finally: _run(["git","worktree","remove","--force",str(WORKTREE)],check=False)

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--source",default="artifacts/mlb_replay_2026_mar_aug"); args=p.parse_args(argv); print(json.dumps(persist(Path(args.source)),sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
