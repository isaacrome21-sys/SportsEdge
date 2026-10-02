#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame


def game_pks(payload):
    found = []
    games = payload.get("games") or (
        [{"resolved_game": payload.get("resolved_game")}]
        if payload.get("resolved_game")
        else []
    )
    for game in games:
        pk = (game.get("resolved_game") or {}).get("game_pk")
        if pk is not None and int(pk) not in found:
            found.append(int(pk))
    for row in payload.get("coverage_slots") or []:
        try:
            pk = int(row.get("game_id"))
        except (TypeError, ValueError):
            continue
        if pk > 0 and pk not in found:
            found.append(pk)
    for row in payload.get("results") or []:
        try:
            pk = int(row.get("game_id"))
        except (TypeError, ValueError):
            continue
        if pk > 0 and pk not in found:
            found.append(pk)
    return found


def _acquire_one(pk, acquire):
    now = datetime.now(timezone.utc)
    try:
        return pk, acquire(game_pk=pk, as_of=now), None
    except Exception as exc:
        return pk, None, f"Game {pk}: context NOT RETRIEVED ({type(exc).__name__}: {exc})"


def main(argv=None, *, acquire=acquire_mlb_run_it_pregame):
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-output", default="artifacts/manual_mlb_snapshot_card.json")
    ap.add_argument("--out-dir", default="artifacts/mlb_context")
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel game-context fetches. Default 1 preserves deterministic test/local behavior.",
    )
    args = ap.parse_args(argv)
    if args.workers < 1:
        ap.error("--workers must be >= 1")

    payload = json.loads(Path(args.engine_output).read_text())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pks = game_pks(payload)
    failures = []

    if args.workers == 1 or len(pks) <= 1:
        results = [_acquire_one(pk, acquire) for pk in pks]
    else:
        worker_count = min(args.workers, len(pks))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="mlb-context") as pool:
            futures = [pool.submit(_acquire_one, pk, acquire) for pk in pks]
            # Resolve in input order so artifacts/logs remain deterministic even
            # though the network-bound work runs concurrently.
            results = [future.result() for future in futures]

    for pk, bundle, failure in results:
        if failure:
            failures.append(failure)
            continue
        (out / f"{pk}.json").write_text(json.dumps(bundle, indent=2, default=str))
        print(f"{pk}: {bundle.get('status')} {str(bundle.get('payload_sha256'))[:12]}")

    (out / "failures.json").write_text(json.dumps(failures, indent=2))
    for failure in failures:
        print(failure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
