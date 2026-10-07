#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame
from sportsedge.mlb_context_forward_capture import capture_training_row
from sportsedge.statcast_daily_source import StatcastSourceError, fetch_daily_statcast


def shared_statcast_snapshot(*, fetch=fetch_daily_statcast, attempts=2, now=None):
    """Fetch the slate-wide 30-day Statcast window once for all games.

    Each game used to download the same large Savant CSV independently and in
    parallel, which timed out (#1457, Padres-Brewers). One shared fetch with a
    retry; on failure return (None, reason) and each game's Statcast lane
    degrades to SOURCE_FAILED without dropping its other lanes.
    """
    now = now or datetime.now(timezone.utc)
    last = None
    for _ in range(max(1, attempts)):
        try:
            return fetch(now=now), None
        except StatcastSourceError as exc:
            last = str(exc)
    return None, last


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
        "--capture-dir",
        default="artifacts/mlb_context_forward",
        help="Append-only forward PIT context evidence output",
    )
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
    capture_out = Path(args.capture_dir)
    capture_out.mkdir(parents=True, exist_ok=True)
    pks = game_pks(payload)
    failures = []
    capture_failures = []
    if acquire is acquire_mlb_run_it_pregame and pks:
        snapshot, statcast_error = shared_statcast_snapshot()
        if snapshot is not None:
            acquire = partial(acquire_mlb_run_it_pregame, statcast_snapshot=snapshot)
        else:
            print(f"shared Statcast fetch failed ({statcast_error}); per-game lanes will report SOURCE_FAILED")
            acquire = partial(acquire_mlb_run_it_pregame, statcast_unavailable_reason=statcast_error)

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
        first_pitch = bundle.get("first_pitch_utc")
        game_date = str(bundle.get("official_date") or (str(first_pitch)[:10] if first_pitch else ""))
        captured_at = str(bundle.get("as_of_utc") or "")
        if first_pitch and captured_at:
            try:
                evidence = capture_training_row(
                    bundle,
                    game_date=game_date,
                    first_pitch_utc=str(first_pitch),
                    captured_at_utc=captured_at,
                )
                capture_path = capture_out / f"{pk}_{evidence['capture_sha256']}.json"
                if not capture_path.exists():
                    capture_path.write_text(json.dumps(evidence, indent=2, default=str))
                print(f"{pk}: forward context evidence {evidence['capture_sha256'][:12]}")
            except ValueError as exc:
                capture_failures.append(
                    f"Game {pk}: context evidence NOT CAPTURED ({exc})"
                )
        else:
            capture_failures.append(
                f"Game {pk}: context evidence NOT CAPTURED (missing first-pitch/as-of timestamp)"
            )
        print(f"{pk}: {bundle.get('status')} {str(bundle.get('payload_sha256'))[:12]}")

    (out / "failures.json").write_text(json.dumps(failures, indent=2))
    (capture_out / "failures.json").write_text(
        json.dumps(capture_failures, indent=2)
    )
    for failure in failures:
        print(failure)
    for failure in capture_failures:
        print(failure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
