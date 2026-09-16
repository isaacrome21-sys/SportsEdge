#!/usr/bin/env python3
"""Persist captured evidence to the remote and prove it landed."""
from __future__ import annotations
import argparse,json,subprocess,sys
from typing import Any,Callable,Sequence
NON_FAST_FORWARD_MARKERS=("non-fast-forward","fetch first","rejected","behind its remote counterpart","tip of your current branch is behind")
PERMISSION_MARKERS=("permission denied","protected branch","not authorized","403","refusing to allow","required status check","pre-receive hook declined")
NETWORK_MARKERS=("could not resolve host","connection timed out","connection reset","unable to access","operation timed out")
class PersistenceBlocked(RuntimeError):
    def __init__(self,reason,detail=None): super().__init__(reason); self.reason=reason; self.detail=detail
def classify_push_failure(stderr):
    text=(stderr or "").lower()
    for marker in PERMISSION_MARKERS:
        if marker in text:return "PERMISSION_DENIED"
    for marker in NON_FAST_FORWARD_MARKERS:
        if marker in text:return "NON_FAST_FORWARD"
    for marker in NETWORK_MARKERS:
        if marker in text:return "NETWORK"
    return "UNKNOWN"
def _run(args):
    proc=subprocess.run(args,capture_output=True,text=True); return proc.returncode,proc.stdout,proc.stderr
def local_head(runner=_run):
    _,out,_=runner(["git","rev-parse","HEAD"]); return out.strip()
def verify_remote(*,branch="main",runner=_run):
    head=local_head(runner); code,out,_=runner(["git","ls-remote","origin",f"refs/heads/{branch}"])
    if code!=0 or not out.strip(): return False
    return bool(head) and head==out.split()[0].strip()
def persist(*,paths:Sequence[str],branch="main",message="MLB direct paired capture: retained observations",max_attempts=4,runner=_run):
    code,out,_=runner(["git","status","--porcelain",*paths])
    if code!=0: raise PersistenceBlocked("BLOCKED_PERSISTENCE_STATUS",out)
    if not out.strip(): return {"status":"NOTHING_TO_PERSIST","attempts":0}
    attempts=[]; last=""
    for attempt in range(1,max_attempts+1):
        runner(["git","add",*paths]); code,_,err=runner(["git","commit","-m",message])
        if code!=0 and "nothing to commit" not in (err or "").lower(): raise PersistenceBlocked("BLOCKED_PERSISTENCE_COMMIT",err)
        code,_,err=runner(["git","push","origin",f"HEAD:{branch}"])
        if code==0:
            verified=verify_remote(branch=branch,runner=runner); attempts.append({"attempt":attempt,"result":"PUSHED"})
            if not verified: raise PersistenceBlocked("BLOCKED_PERSISTENCE_UNVERIFIED",{"attempts":attempts})
            return {"status":"PERSISTED","attempts":attempts,"commit":local_head(runner)}
        cls=classify_push_failure(err); last=err; attempts.append({"attempt":attempt,"result":cls})
        if cls=="PERMISSION_DENIED": raise PersistenceBlocked("BLOCKED_PERSISTENCE_PERMISSION",{"attempts":attempts,"stderr":err})
        rc,_,ferr=runner(["git","fetch","origin",branch])
        if rc!=0: raise PersistenceBlocked("BLOCKED_PERSISTENCE_FETCH",ferr)
        runner(["git","reset","--soft",f"origin/{branch}"])
    raise PersistenceBlocked("BLOCKED_PERSISTENCE_RETRIES_EXHAUSTED",{"attempts":attempts,"stderr":last})
def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--path",action="append",required=True); ap.add_argument("--branch",default="main"); ap.add_argument("--message",default="MLB direct paired capture: retained observations"); args=ap.parse_args(argv)
    try: result=persist(paths=args.path,branch=args.branch,message=args.message)
    except PersistenceBlocked as exc:
        print(json.dumps({"status":"BLOCKED","reason":exc.reason,"detail":exc.detail},indent=2)); return 2
    print(json.dumps(result,indent=2)); return 0
if __name__=="__main__": sys.exit(main())
