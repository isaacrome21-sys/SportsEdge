#!/usr/bin/env python3
"""Durably persist MLB V8 decision/card evidence to the data branch."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import time

FORWARD_EPOCH = datetime(2026, 9, 3, tzinfo=timezone.utc)
DATA_BRANCH = "data"
WORKTREE = Path(".v8-data-branch")

class PersistError(RuntimeError):
    pass


def _run(args, *, cwd=None, check=True):
    p=subprocess.run(args, cwd=None if cwd is None else str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.stdout: print(p.stdout, end="")
    if check and p.returncode != 0: raise PersistError(f"command failed ({p.returncode}): {' '.join(args)}")
    return p


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False, default=str).encode()


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _utc(value):
    text=str(value or "").replace("Z","+00:00")
    dt=datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None: raise PersistError("generated_at timezone required")
    return dt.astimezone(timezone.utc)


def persist(card_path: Path, journal_root: Path) -> dict:
    if not card_path.is_file(): raise PersistError("live MLB card missing")
    card_raw=card_path.read_bytes(); card=json.loads(card_raw)
    generated=_utc(card.get("generated_at_utc"))
    if generated < FORWARD_EPOCH:
        return {"status":"SKIP_PRE_V8_EPOCH","generated_at_utc":generated.isoformat()}
    slate=str(card.get("slate_date_ct") or "").strip()
    if not slate: raise PersistError("slate_date_ct missing")
    card_sha=_sha(card_raw)
    stamp=generated.strftime("%Y%m%dT%H%M%S.%fZ")

    journal_ref=card.get("prediction_journal") if isinstance(card.get("prediction_journal"), dict) else {}
    journal_path=Path(str(journal_ref.get("path") or "")) if journal_ref else None
    if journal_path is not None and not journal_path.is_file():
        raise PersistError("prediction journal reference exists but file is missing")
    journal_sha=None
    journal_name=None
    if journal_path is not None:
        raw=journal_path.read_bytes(); journal_sha=_sha(raw); journal_name=journal_path.name
        expected=str(journal_ref.get("journal_sha256") or "")
        # Journal hash is over canonical record bytes without trailing newline in v2.
        try:
            record=json.loads(raw)
            canonical_sha=_sha(_canonical(record))
        except Exception as exc:
            raise PersistError("prediction journal invalid JSON") from exc
        if expected and canonical_sha != expected:
            raise PersistError("prediction journal hash mismatch")

    if WORKTREE.exists():
        _run(["git","worktree","remove","--force",str(WORKTREE)], check=False)
        if WORKTREE.exists(): shutil.rmtree(WORKTREE)
    _run(["git","fetch","origin",DATA_BRANCH])
    _run(["git","worktree","add","--detach",str(WORKTREE),"FETCH_HEAD"])
    try:
        card_dest=WORKTREE/"archive/v8_forward/cards"/slate/f"{stamp}_{card_sha}.json"
        card_dest.parent.mkdir(parents=True, exist_ok=True)
        if card_dest.exists() and card_dest.read_bytes()!=card_raw: raise PersistError("immutable card path collision")
        card_dest.write_bytes(card_raw)

        journal_dest=None
        if journal_path is not None:
            journal_dest=WORKTREE/"archive/v8_forward/decisions"/slate/journal_name
            journal_dest.parent.mkdir(parents=True, exist_ok=True)
            source=journal_path.read_bytes()
            if journal_dest.exists() and journal_dest.read_bytes()!=source: raise PersistError("immutable journal path collision")
            journal_dest.write_bytes(source)

        manifest={
            "schema_version":"mlb_v8_decision_persistence_v1",
            "forward_epoch_utc":FORWARD_EPOCH.isoformat(),
            "slate_date_ct":slate,
            "generated_at_utc":generated.isoformat(),
            "card_sha256":card_sha,
            "card_path":str(card_dest.relative_to(WORKTREE)),
            "journal_sha256":journal_sha,
            "journal_path":None if journal_dest is None else str(journal_dest.relative_to(WORKTREE)),
            "journal_present":journal_dest is not None,
            "run_status":card.get("run_status"),
            "card_status":card.get("card_status"),
            "truth_gate_semantics":"PERSISTENCE_IS_NOT_PROMOTION",
        }
        manifest["manifest_sha256"]=_sha(_canonical(manifest))
        manifest_path=WORKTREE/"archive/v8_forward/decision_manifests"/slate/f"{stamp}_{manifest['manifest_sha256']}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")

        _run(["git","config","user.name","sportsedge-v8-evidence-bot"],cwd=WORKTREE)
        _run(["git","config","user.email","sportsedge-v8-evidence-bot@users.noreply.github.com"],cwd=WORKTREE)
        _run(["git","add","archive/v8_forward"],cwd=WORKTREE)
        changed=_run(["git","diff","--cached","--quiet"],cwd=WORKTREE,check=False)
        if changed.returncode == 0:
            return {**manifest,"status":"ALREADY_PERSISTED"}
        if changed.returncode != 1: raise PersistError("unable to inspect staged evidence")
        _run(["git","commit","-m",f"evidence: persist MLB V8 decision {slate} {stamp}"],cwd=WORKTREE)
        for attempt in range(1,6):
            push=_run(["git","push","origin",f"HEAD:{DATA_BRANCH}"],cwd=WORKTREE,check=False)
            if push.returncode == 0: return {**manifest,"status":"PERSISTED"}
            _run(["git","fetch","origin",DATA_BRANCH],cwd=WORKTREE)
            rebase=_run(["git","rebase",f"origin/{DATA_BRANCH}"],cwd=WORKTREE,check=False)
            if rebase.returncode != 0:
                _run(["git","rebase","--abort"],cwd=WORKTREE,check=False)
                raise PersistError("data branch rebase conflict")
            time.sleep(attempt)
        raise PersistError("data branch push failed")
    finally:
        _run(["git","worktree","remove","--force",str(WORKTREE)],check=False)


def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--card",default="artifacts/live_mlb_card.json"); p.add_argument("--journal-root",default="artifacts/prediction_journal")
    args=p.parse_args(argv)
    result=persist(Path(args.card),Path(args.journal_root)); print(json.dumps(result,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
