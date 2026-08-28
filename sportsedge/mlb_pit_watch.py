"""Local MLB PIT evidence execution independent of GitHub Actions.

The watcher orchestrates existing immutable archive lanes and can publish their
artifacts to the repository ``data`` branch. It does not price, settle, or promote.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Mapping

CAPTURE_MINUTES = (7, 22, 37, 52)


class MLBPITWatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class PITIteration:
    captured_at: str
    prop_status: str
    prop_count: int
    additional_status: str
    additional_count: int
    published: bool
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "prop_status": self.prop_status,
            "prop_count": self.prop_count,
            "additional_status": self.additional_status,
            "additional_count": self.additional_count,
            "published": self.published,
            "failures": list(self.failures),
        }


def aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MLBPITWatchError("PIT_WATCH_TIMEZONE_REQUIRED")
    return current.astimezone(timezone.utc)


def next_capture_time(now: datetime) -> datetime:
    current = aware_utc(now)
    floor = current.replace(second=0, microsecond=0)
    for minute in CAPTURE_MINUTES:
        candidate = floor.replace(minute=minute)
        if candidate > current:
            return candidate
    return (floor + timedelta(hours=1)).replace(minute=CAPTURE_MINUTES[0])


def _count(payload: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


def _status(payload: Mapping[str, Any], *, count: int, state_key: str | None = None) -> str:
    if state_key and str(payload.get(state_key) or "").strip():
        return str(payload[state_key]).strip()
    return "CAPTURED" if count > 0 else "BLOCKED_NO_TARGET_QUOTES"


def run_pit_iteration(
    *,
    now: datetime,
    capture_props: Callable[[datetime], Mapping[str, Any]],
    capture_additional: Callable[[datetime], Mapping[str, Any]],
    publisher: Callable[[], bool] | None = None,
) -> PITIteration:
    current = aware_utc(now)
    failures: list[str] = []
    prop_payload: Mapping[str, Any] = {}
    additional_payload: Mapping[str, Any] = {}
    try:
        prop_payload = capture_props(current)
    except Exception as exc:
        failures.append(f"PROP:{type(exc).__name__}:{exc}")
    try:
        additional_payload = capture_additional(current)
    except Exception as exc:
        failures.append(f"ADDITIONAL:{type(exc).__name__}:{exc}")

    prop_count = _count(prop_payload, "pit_target_quote_count", "pit_quote_count")
    additional_count = _count(additional_payload, "pit_quote_count", "pit_target_quote_count")
    prop_status = (
        "ERROR"
        if not prop_payload and any(item.startswith("PROP:") for item in failures)
        else _status(prop_payload, count=prop_count)
    )
    additional_status = (
        "ERROR"
        if not additional_payload and any(item.startswith("ADDITIONAL:") for item in failures)
        else _status(additional_payload, count=additional_count, state_key="capture_status")
    )

    published = False
    if publisher is not None and (prop_payload or additional_payload):
        try:
            published = bool(publisher())
        except Exception as exc:
            failures.append(f"PUBLISH:{type(exc).__name__}:{exc}")

    return PITIteration(
        captured_at=current.isoformat(),
        prop_status=prop_status,
        prop_count=prop_count,
        additional_status=additional_status,
        additional_count=additional_count,
        published=published,
        failures=tuple(failures),
    )


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def publish_data_branch(repo_root: str | Path) -> bool:
    """Copy immutable local PIT artifacts into ``data`` and push them.

    Existing destination files are not proactively deleted. A no-change publish
    returns ``False``. Push/commit errors propagate and are recorded by the watcher.
    """
    root = Path(repo_root).resolve()
    gitmeta = root / ".git"
    if not gitmeta.exists():
        raise MLBPITWatchError("PIT_REPO_GIT_METADATA_MISSING")

    _git(root, "fetch", "origin", "data")
    worktree = root / ".pit-data-worktree"
    if worktree.exists():
        _git(root, "worktree", "remove", "--force", str(worktree), check=False)
        if worktree.exists():
            shutil.rmtree(worktree)
    _git(root, "worktree", "add", "--force", str(worktree), "origin/data")
    try:
        mappings = (
            (root / "artifacts" / "prop_odds", worktree / "runtime" / "mlb-prop-pit"),
            (root / "artifacts" / "additional_odds", worktree / "runtime" / "mlb-additional-pit"),
        )
        added_paths: list[str] = []
        for source, destination in mappings:
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, dirs_exist_ok=True)
                added_paths.append(str(destination.relative_to(worktree)))
        if not added_paths:
            return False
        _git(worktree, "add", *added_paths)
        diff = _git(worktree, "diff", "--cached", "--quiet", check=False)
        if diff.returncode == 0:
            return False
        if diff.returncode != 1:
            raise MLBPITWatchError("PIT_DATA_BRANCH_DIFF_FAILED")
        _git(worktree, "config", "user.name", "sportsedge-local-pit")
        _git(worktree, "config", "user.email", "sportsedge-local-pit@users.noreply.github.com")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _git(worktree, "commit", "-m", f"archive: local MLB PIT {stamp}")
        _git(worktree, "push", "origin", "HEAD:data")
        return True
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree), check=False)
