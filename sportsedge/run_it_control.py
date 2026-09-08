"""Unified SportsEdge RUN IT control plane.

This module is orchestration only. It never changes Model_P, Truth Gate thresholds,
promotion evidence, or deployment eligibility. Missing autonomous lanes are emitted
as explicit blockers rather than silently skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping

CONTROL_SCHEMA = "RUN_IT_CONTROL_V1"
DEFAULT_SURFACE = Path("config/run_it_surface.json")


class RunItControlError(ValueError):
    pass


@dataclass(frozen=True)
class LaneResult:
    sport: str
    lane: str
    status: str
    automatic_completeness: str
    exit_code: int | None = None
    blocker: str | None = None
    command: tuple[str, ...] = ()
    stdout_tail: str = ""
    stderr_tail: str = ""


def _root(value: str | Path | None = None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[1]


def load_surface(path: str | Path | None = None, *, repo_root: str | Path | None = None) -> dict[str, Any]:
    root = _root(repo_root)
    target = Path(path) if path is not None else root / DEFAULT_SURFACE
    if not target.is_absolute():
        target = root / target
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RunItControlError("RUN_IT_SURFACE_UNREADABLE") from exc
    if payload.get("schema_version") != CONTROL_SCHEMA:
        raise RunItControlError("RUN_IT_SURFACE_SCHEMA_INVALID")
    sports = payload.get("sports")
    if not isinstance(sports, Mapping) or not sports:
        raise RunItControlError("RUN_IT_SURFACE_SPORTS_REQUIRED")
    return payload


def _path_from_command(command: Iterable[str]) -> str | None:
    parts = tuple(str(x) for x in command)
    if len(parts) >= 2 and parts[0].endswith("python"):
        return parts[1]
    return None


def audit_surface(*, repo_root: str | Path | None = None, surface_path: str | Path | None = None) -> dict[str, Any]:
    root = _root(repo_root)
    payload = load_surface(surface_path, repo_root=root)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for sport, spec_raw in payload["sports"].items():
        spec = dict(spec_raw)
        command = tuple(spec.get("automatic_command") or ())
        entrypoint = _path_from_command(command)
        entrypoint_exists = bool(entrypoint and (root / entrypoint).is_file())
        market_surface = spec.get("market_surface")
        market_surface_exists = bool(market_surface and (root / str(market_surface)).is_file())
        governance = spec.get("governance_source")
        governance_exists = None if not governance else (root / str(governance)).is_file()
        if command and not entrypoint_exists:
            failures.append(f"{sport}:AUTOMATIC_ENTRYPOINT_MISSING")
        if market_surface and not market_surface_exists:
            failures.append(f"{sport}:MARKET_SURFACE_MISSING")
        if governance and not governance_exists:
            failures.append(f"{sport}:GOVERNANCE_SOURCE_MISSING")
        rows.append({
            "sport": sport,
            "lane": spec.get("lane"),
            "automatic_completeness": spec.get("automatic_completeness"),
            "automatic_command": list(command),
            "automatic_entrypoint_exists": entrypoint_exists if command else False,
            "library_entrypoint": spec.get("library_entrypoint"),
            "market_surface": market_surface,
            "market_surface_exists": market_surface_exists if market_surface else None,
            "governance_source": governance,
            "governance_source_exists": governance_exists,
            "blocker": spec.get("blocker"),
        })
    return {
        "schema_version": CONTROL_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "sports": rows,
    }


def _tail(value: str, limit: int = 5000) -> str:
    text = str(value or "")
    return text[-limit:]


def execute_surface(
    *,
    scope: Iterable[str] | None = None,
    repo_root: str | Path | None = None,
    surface_path: str | Path | None = None,
    timeout_seconds: int = 900,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = _root(repo_root)
    surface = load_surface(surface_path, repo_root=root)
    selected = {str(x).strip().upper() for x in (scope or surface["sports"].keys()) if str(x).strip()}
    unknown = sorted(selected.difference(surface["sports"].keys()))
    if unknown:
        raise RunItControlError("RUN_IT_SCOPE_UNKNOWN:" + ",".join(unknown))
    run_env = dict(os.environ)
    if env:
        run_env.update({str(k): str(v) for k, v in env.items()})
    results: list[LaneResult] = []
    for sport, spec_raw in surface["sports"].items():
        if sport not in selected:
            continue
        spec = dict(spec_raw)
        command = tuple(str(x) for x in (spec.get("automatic_command") or ()))
        completeness = str(spec.get("automatic_completeness") or "UNKNOWN")
        lane = str(spec.get("lane") or "UNKNOWN")
        if not command:
            results.append(LaneResult(
                sport=sport,
                lane=lane,
                status="BLOCKED",
                automatic_completeness=completeness,
                blocker=str(spec.get("blocker") or "AUTOMATIC_ENTRYPOINT_NOT_IMPLEMENTED"),
            ))
            continue
        entrypoint = _path_from_command(command)
        if not entrypoint or not (root / entrypoint).is_file():
            results.append(LaneResult(
                sport=sport,
                lane=lane,
                status="BROKEN",
                automatic_completeness=completeness,
                blocker="AUTOMATIC_ENTRYPOINT_MISSING",
                command=command,
            ))
            continue
        try:
            proc = subprocess.run(
                (sys.executable, *command[1:]),
                cwd=root,
                env=run_env,
                text=True,
                capture_output=True,
                timeout=int(timeout_seconds),
                check=False,
            )
            status = "SUCCESS" if proc.returncode == 0 else "BROKEN"
            blocker = None if proc.returncode == 0 else "ENTRYPOINT_NONZERO"
            try:
                output = json.loads(proc.stdout)
            except (ValueError, TypeError):
                output = None
            if isinstance(output, dict) and str(output.get("run_status") or output.get("status") or "").startswith("BLOCKED"):
                status = "BLOCKED"
                blocker = str(output.get("reason") or output.get("error") or output.get("blocker") or output.get("run_status") or "ENTRYPOINT_REPORTED_BLOCKED")
            results.append(LaneResult(
                sport=sport,
                lane=lane,
                status=status,
                automatic_completeness=completeness,
                exit_code=int(proc.returncode),
                blocker=blocker,
                command=command,
                stdout_tail=_tail(proc.stdout),
                stderr_tail=_tail(proc.stderr),
            ))
        except subprocess.TimeoutExpired as exc:
            results.append(LaneResult(
                sport=sport,
                lane=lane,
                status="BLOCKED_OR_FAILED",
                automatic_completeness=completeness,
                blocker="ENTRYPOINT_TIMEOUT",
                command=command,
                stdout_tail=_tail(exc.stdout or ""),
                stderr_tail=_tail(exc.stderr or ""),
            ))
    rows = [asdict(row) for row in results]
    executable = [row for row in results if row.command]
    failed = [row for row in executable if row.status != "SUCCESS"]
    blocked = [row for row in results if not row.command]
    overall = "SUCCESS" if not failed and not blocked else "PARTIAL" if any(row.status == "SUCCESS" for row in results) else "BLOCKED"
    return {
        "schema_version": CONTROL_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": sorted(selected),
        "overall_status": overall,
        "governance": {
            "model_p_changed": False,
            "truth_gate_changed": False,
            "promotion_changed": False,
            "silent_skip_allowed": False,
        },
        "results": rows,
    }


def scope_from_request(payload: Mapping[str, Any] | None) -> tuple[str, ...] | None:
    if not payload:
        return None
    raw = payload.get("scope", "ALL")
    if isinstance(raw, str):
        if raw.strip().upper() == "ALL":
            return None
        return tuple(x.strip().upper() for x in raw.split(",") if x.strip())
    if isinstance(raw, (list, tuple)):
        values = tuple(str(x).strip().upper() for x in raw if str(x).strip())
        return None if "ALL" in values else values
    raise RunItControlError("RUN_IT_REQUEST_SCOPE_INVALID")
