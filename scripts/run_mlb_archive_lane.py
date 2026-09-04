#!/usr/bin/env python3
"""Run and durably persist the standalone MLB raw-odds archive lane.

This wrapper is intentionally standard-library only. It runs inside an existing
SportsEdge scheduler so the archive does not need its own dense GitHub Actions
schedule. Every execution persists a unique lane heartbeat and the budget ledger
to the ``data`` branch; raw snapshots are staged only when they exist.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

DATA_BRANCH = "data"
WORKTREE = Path(".data-branch")
LEDGER_ENV = "SPORTSEDGE_ODDS_BUDGET_LEDGER"
DEFAULT_LEDGER = Path(".cache/sportsedge/odds-budget/ledger.json")
RAW_ROOT = Path("artifacts/raw_odds")
DEDUPE_SECONDS = 5 * 60
DEFAULT_CAP = 12
NO_STATUS_EXIT = 97


class ArchiveLaneError(RuntimeError):
    pass


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=None if cwd is None else str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout, end="")
    if check and result.returncode != 0:
        raise ArchiveLaneError(
            f"command failed ({result.returncode}): {' '.join(args)}"
        )
    return result


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ledger_path() -> Path:
    raw = os.environ.get(LEDGER_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_LEDGER


def _daily_cap() -> int:
    raw = os.environ.get(
        "SPORTSEDGE_ODDS_DAILY_BUDGET_CREDITS", str(DEFAULT_CAP)
    )
    try:
        cap = int(raw)
    except Exception as exc:
        raise ArchiveLaneError(f"invalid daily budget cap: {raw!r}") from exc
    if cap < 0:
        raise ArchiveLaneError(f"invalid negative daily budget cap: {cap}")
    return cap


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _parse_run_at(row: dict) -> datetime | None:
    try:
        stamp = str(row["run_at_utc"]).replace("Z", "+00:00")
        return datetime.fromisoformat(stamp).astimezone(timezone.utc)
    except Exception:
        return None


def _normalized_ledger(*, ledger_path: Path, now: datetime) -> dict:
    day = now.date().isoformat()
    ledger = _load_json(ledger_path)
    if ledger.get("utc_date") != day:
        return {
            "utc_date": day,
            "cap_credits": _daily_cap(),
            "credits_consumed_actual": 0,
            "runs": [],
        }
    ledger["utc_date"] = day
    ledger["cap_credits"] = _daily_cap()
    ledger.setdefault("credits_consumed_actual", 0)
    ledger.setdefault("runs", [])
    return ledger


def _prepare_data_worktree() -> None:
    if WORKTREE.exists():
        _run(
            ["git", "worktree", "remove", "--force", str(WORKTREE)],
            check=False,
        )
        if WORKTREE.exists():
            shutil.rmtree(WORKTREE)
    _run(["git", "fetch", "--depth=1", "origin", DATA_BRANCH])
    _run(["git", "worktree", "add", "--detach", str(WORKTREE), "FETCH_HEAD"])


def _restore_ledger() -> Path:
    ledger = _ledger_path()
    source = WORKTREE / "runtime/odds-budget/ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, ledger)
    return ledger


def _latest_fresh_capture_status(
    *,
    ledger: dict,
    now: datetime,
) -> tuple[str | None, str | None]:
    """Return the most recent non-heartbeat status written by this execution."""
    for row in reversed(list(ledger.get("runs") or [])):
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if not status or status == "ARCHIVE_LANE_HEARTBEAT":
            continue
        run_at = _parse_run_at(row)
        if run_at is None:
            continue
        age = (now - run_at).total_seconds()
        if not (0 <= age <= DEDUPE_SECONDS):
            return None, None
        return status, row.get("run_at_utc")
    return None, None


def _append_lane_heartbeat(
    *,
    ledger_path: Path,
    now: datetime,
    source: str,
    run_id: str,
    capture_exit_code: int,
    status_root: Path = RAW_ROOT,
) -> dict:
    """Persist execution health without erasing the real capture result."""
    ledger = _normalized_ledger(ledger_path=ledger_path, now=now)
    fresh_status, fresh_run_at = _latest_fresh_capture_status(
        ledger=ledger,
        now=now,
    )

    effective_code = int(capture_exit_code)
    if fresh_status == "EXECUTED_STARTED":
        capture_status = "CAPTURE_HELPER_STARTED_NO_FINAL_STATUS"
        if effective_code == 0:
            effective_code = NO_STATUS_EXIT
    elif fresh_status:
        capture_status = fresh_status
    elif effective_code == 0:
        capture_status = "CAPTURE_HELPER_NO_STATUS"
        effective_code = NO_STATUS_EXIT
    else:
        capture_status = "CAPTURE_HELPER_PRESTATUS_FAILURE"

    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    row = {
        "run_at_utc": now.isoformat(),
        "status": "ARCHIVE_LANE_HEARTBEAT",
        "archive_source": source,
        "github_run_id": run_id,
        "capture_exit_code": effective_code,
        "capture_succeeded": effective_code == 0,
        "capture_status": capture_status,
        "capture_status_run_at_utc": fresh_run_at,
    }
    _write_json(
        status_root
        / "status"
        / now.date().isoformat()
        / f"lane_{stamp}.json",
        row,
    )

    runs = ledger.setdefault("runs", [])
    runs.append(row)
    if len(runs) > 500:
        del runs[:-500]

    # Preserve capture semantics for existing readers. The wrapper heartbeat gets
    # its own fields instead of replacing last_status with a generic heartbeat.
    ledger["last_status"] = capture_status
    ledger["last_run_at_utc"] = fresh_run_at or row["run_at_utc"]
    ledger["last_lane_heartbeat_at_utc"] = row["run_at_utc"]
    ledger["last_lane_capture_status"] = capture_status
    ledger["last_lane_capture_exit_code"] = effective_code
    _write_json(ledger_path, ledger)
    print(json.dumps(row, sort_keys=True))
    return row


def _dedupe_recent_capture(*, ledger_path: Path, now: datetime) -> bool:
    ledger = _normalized_ledger(ledger_path=ledger_path, now=now)
    source = None
    for row in reversed(list(ledger.get("runs") or [])):
        if not isinstance(row, dict) or row.get("status") != "CAPTURED":
            continue
        captured_at = _parse_run_at(row)
        if captured_at is None:
            continue
        age = (now - captured_at).total_seconds()
        if 0 <= age <= DEDUPE_SECONDS:
            source = row
        break
    if source is None:
        return False

    day = now.date().isoformat()
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    row = {
        "run_at_utc": now.isoformat(),
        "status": "SKIP_RECENT_CAPTURE_DEDUP",
        "credits_consumed_actual": 0,
        "source_run_at_utc": source.get("run_at_utc"),
        "source_capture_window": source.get("capture_window"),
        "source_raw_file": source.get("raw_file"),
        "dedupe_horizon_seconds": DEDUPE_SECONDS,
    }
    _write_json(RAW_ROOT / "status" / day / f"run_{stamp}.json", row)
    runs = ledger.setdefault("runs", [])
    runs.append(row)
    if len(runs) > 500:
        del runs[:-500]
    ledger["last_status"] = row["status"]
    ledger["last_run_at_utc"] = row["run_at_utc"]
    _write_json(ledger_path, ledger)
    print(json.dumps(row, sort_keys=True))
    return True


def _run_capture() -> int:
    self_test = _run(
        [
            sys.executable,
            "-I",
            "scripts/archive_raw_game_odds.py",
            "--self-test",
        ],
        check=False,
    )
    if self_test.returncode != 0:
        return self_test.returncode
    return _run(
        [sys.executable, "-I", "scripts/archive_raw_game_odds.py"],
        check=False,
    ).returncode


def _copy_tree_contents(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def _stage_persistence_paths(repo: Path) -> None:
    """Stage required heartbeat paths and optional raw snapshots fail-closed."""
    ledger = repo / "runtime/odds-budget/ledger.json"
    status_root = repo / "runtime/archive-status"
    if not ledger.is_file():
        raise ArchiveLaneError("required durable archive ledger is missing")
    if not status_root.is_dir() or not any(status_root.rglob("*.json")):
        raise ArchiveLaneError(
            "required durable archive status heartbeat is missing"
        )
    _run(
        [
            "git",
            "add",
            "runtime/odds-budget/ledger.json",
            "runtime/archive-status",
        ],
        cwd=repo,
    )
    if (repo / "archive/raw_odds").is_dir():
        _run(["git", "add", "archive/raw_odds"], cwd=repo)


def _persist(
    *,
    ledger_path: Path,
    day: str,
    run_id: str,
    source: str,
) -> None:
    ledger_destination = WORKTREE / "runtime/odds-budget/ledger.json"
    ledger_destination.parent.mkdir(parents=True, exist_ok=True)
    if not ledger_path.is_file():
        raise ArchiveLaneError("archive budget ledger missing after execution")
    shutil.copy2(ledger_path, ledger_destination)

    status_source = RAW_ROOT / "status" / day
    status_destination = WORKTREE / "runtime/archive-status" / day
    status_destination.mkdir(parents=True, exist_ok=True)
    if status_source.is_dir():
        _copy_tree_contents(status_source, status_destination)
    if not any(status_destination.glob("*.json")):
        raise ArchiveLaneError("archive execution produced no status heartbeat")

    raw_source = RAW_ROOT / day
    if raw_source.is_dir():
        _copy_tree_contents(
            raw_source,
            WORKTREE / "archive/raw_odds" / day,
        )

    _run(
        ["git", "config", "user.name", "sportsedge-archive-bot"],
        cwd=WORKTREE,
    )
    _run(
        [
            "git",
            "config",
            "user.email",
            "sportsedge-archive-bot@users.noreply.github.com",
        ],
        cwd=WORKTREE,
    )
    _stage_persistence_paths(WORKTREE)

    staged = _run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=WORKTREE,
        check=False,
    )
    if staged.returncode == 0:
        raise ArchiveLaneError(
            "archive execution produced no durable data-branch change"
        )
    if staged.returncode != 1:
        raise ArchiveLaneError(
            "unable to inspect staged archive persistence diff"
        )

    _run(
        [
            "git",
            "commit",
            "-m",
            f"archive: persist MLB odds {source} run {run_id}",
        ],
        cwd=WORKTREE,
    )

    # Shared workflow concurrency serializes normal writers. This retry protects
    # against an unexpected external data-branch update without hiding conflicts.
    for attempt in range(1, 6):
        pushed = _run(
            ["git", "push", "origin", f"HEAD:{DATA_BRANCH}"],
            cwd=WORKTREE,
            check=False,
        )
        if pushed.returncode == 0:
            return
        _run(["git", "fetch", "origin", DATA_BRANCH], cwd=WORKTREE)
        rebased = _run(
            ["git", "rebase", f"origin/{DATA_BRANCH}"],
            cwd=WORKTREE,
            check=False,
        )
        if rebased.returncode != 0:
            _run(
                ["git", "rebase", "--abort"],
                cwd=WORKTREE,
                check=False,
            )
            raise ArchiveLaneError(
                "data-branch archive persistence rebase conflict"
            )
        time.sleep(attempt * 2)

    raise ArchiveLaneError(
        "data-branch archive persistence push failed after retries"
    )


def _self_test() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        _run(["git", "init", "-q"], cwd=root)
        _run(["git", "config", "user.name", "test"], cwd=root)
        _run(["git", "config", "user.email", "test@example.test"], cwd=root)

        (root / "runtime/odds-budget").mkdir(parents=True)
        (root / "runtime/archive-status/2026-09-01").mkdir(parents=True)
        (root / "runtime/odds-budget/ledger.json").write_text("{}\n")
        (root / "runtime/archive-status/2026-09-01/run.json").write_text(
            "{}\n"
        )

        # Missing optional raw directory must not prevent required persistence.
        _stage_persistence_paths(root)
        names = set(
            _run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=root,
            ).stdout.splitlines()
        )
        assert "runtime/odds-budget/ledger.json" in names
        assert "runtime/archive-status/2026-09-01/run.json" in names
        assert not any(
            name.startswith("archive/raw_odds/") for name in names
        )

        _run(["git", "reset"], cwd=root)
        (root / "archive/raw_odds/2026-09-01/T0").mkdir(parents=True)
        (root / "archive/raw_odds/2026-09-01/T0/raw.json").write_text(
            "[]\n"
        )
        _stage_persistence_paths(root)
        names = set(
            _run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=root,
            ).stdout.splitlines()
        )
        assert "archive/raw_odds/2026-09-01/T0/raw.json" in names

        heartbeat_root = root / "heartbeat"
        heartbeat_ledger = heartbeat_root / "ledger.json"
        heartbeat_now = datetime(
            2026,
            9,
            1,
            14,
            0,
            tzinfo=timezone.utc,
        )

        # Capture startup failure still creates a current execution heartbeat.
        failed = _append_lane_heartbeat(
            ledger_path=heartbeat_ledger,
            now=heartbeat_now,
            source="self-test",
            run_id="123",
            capture_exit_code=17,
            status_root=heartbeat_root / "artifacts/raw_odds",
        )
        persisted = _load_json(heartbeat_ledger)
        assert persisted["last_status"] == "CAPTURE_HELPER_PRESTATUS_FAILURE"
        assert persisted["last_lane_capture_exit_code"] == 17
        assert failed["capture_exit_code"] == 17

        # A successful helper without a final status must fail closed.
        no_status_root = root / "no-status"
        no_status_ledger = no_status_root / "ledger.json"
        no_status = _append_lane_heartbeat(
            ledger_path=no_status_ledger,
            now=heartbeat_now,
            source="self-test",
            run_id="124",
            capture_exit_code=0,
            status_root=no_status_root / "artifacts/raw_odds",
        )
        assert no_status["capture_status"] == "CAPTURE_HELPER_NO_STATUS"
        assert no_status["capture_exit_code"] == NO_STATUS_EXIT

        # A real final capture status remains authoritative after heartbeat.
        preserved_root = root / "preserved"
        preserved_ledger = preserved_root / "ledger.json"
        final_at = heartbeat_now.isoformat()
        _write_json(
            preserved_ledger,
            {
                "utc_date": "2026-09-01",
                "cap_credits": 12,
                "credits_consumed_actual": 0,
                "runs": [
                    {
                        "run_at_utc": final_at,
                        "status": "SKIP_OUTSIDE_CAPTURE_WINDOW",
                    }
                ],
                "last_status": "SKIP_OUTSIDE_CAPTURE_WINDOW",
                "last_run_at_utc": final_at,
            },
        )
        preserved = _append_lane_heartbeat(
            ledger_path=preserved_ledger,
            now=heartbeat_now,
            source="self-test",
            run_id="125",
            capture_exit_code=0,
            status_root=preserved_root / "artifacts/raw_odds",
        )
        preserved_state = _load_json(preserved_ledger)
        assert preserved["capture_status"] == "SKIP_OUTSIDE_CAPTURE_WINDOW"
        assert preserved_state["last_status"] == "SKIP_OUTSIDE_CAPTURE_WINDOW"

    print(
        json.dumps(
            {
                "status": "SELF_TEST_OK",
                "required_persistence_without_raw": "PASS",
                "optional_raw_persistence": "PASS",
                "capture_failure_heartbeat": "PASS",
                "capture_status_preserved": "PASS",
                "success_without_status_fails_closed": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    source = (
        os.environ.get(
            "SPORTSEDGE_ARCHIVE_SOURCE",
            "archive-lane",
        ).strip()
        or "archive-lane"
    )
    started_at = _utcnow()

    try:
        _prepare_data_worktree()
        ledger = _restore_ledger()

        if _dedupe_recent_capture(
            ledger_path=ledger,
            now=started_at,
        ):
            capture_code = 0
        else:
            capture_code = _run_capture()

        # This wrapper-level heartbeat is independent of the capture helper's
        # status writer, so startup/self-test failures are still observable.
        heartbeat_at = _utcnow()
        heartbeat = _append_lane_heartbeat(
            ledger_path=ledger,
            now=heartbeat_at,
            source=source,
            run_id=run_id,
            capture_exit_code=capture_code,
        )
        capture_code = int(heartbeat["capture_exit_code"])

        _persist(
            ledger_path=ledger,
            day=heartbeat_at.date().isoformat(),
            run_id=run_id,
            source=source,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "ARCHIVE_PERSISTENCE_FAILED",
                    "error": f"{type(exc).__name__}:{exc}",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 98

    return capture_code


if __name__ == "__main__":
    raise SystemExit(main())
