#!/usr/bin/env python3
"""Persist immutable captures and a run-scoped snapshot of the append-only log."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.persist_forward_evidence_data_branch import PersistenceBlocked, persist


def archive_paths(root: Path, run_id: str, attempt: str) -> list[str]:
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise PersistenceBlocked('NFL_ARCHIVE_RUN_IDENTITY_REQUIRED')
    captures = root / 'data/nfl_2026_confirmation/captures'
    paths = [str(p.relative_to(root)) for p in sorted(captures.rglob('*'))
             if p.is_file() and p.name != 'attempts.jsonl']
    log = captures / 'attempts.jsonl'
    if log.is_file():
        snapshot = root / 'data/nfl_2026_confirmation/attempt_logs' / f'{run_id}_{attempt}.jsonl'
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        raw = log.read_bytes()
        if snapshot.exists() and snapshot.read_bytes() != raw:
            raise PersistenceBlocked('NFL_ATTEMPT_LOG_IDENTITY_COLLISION')
        if not snapshot.exists():
            with snapshot.open('xb') as handle:
                handle.write(raw)
        paths.append(str(snapshot.relative_to(root)))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', required=True)
    args = parser.parse_args()
    try:
        paths = archive_paths(Path.cwd(), os.getenv('GITHUB_RUN_ID', ''), os.getenv('GITHUB_RUN_ATTEMPT', ''))
        result = persist(paths=paths, branch='data', worktree=args.worktree,
                         message='NFL confirmation archive ' + os.environ['GITHUB_RUN_ID'])
    except PersistenceBlocked as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': exc.reason, 'detail': exc.detail}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
