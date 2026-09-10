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
    execution_status: str = "NOT_RUN"
    model_rows: int = 0
    official_bets: int = 0
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


def _output_path(command: tuple[str, ...], root: Path) -> Path | None:
    if "--output" not in command:
        return None
    index = command.index("--output") + 1
    if index >= len(command):
        return None
    path = Path(command[index])
    return path if path.is_absolute() else root / path


def _output_stamp(path: Path | None):
    if path is None or not path.is_file():
        return None
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


def _card_state(path: Path | None, previous_stamp) -> tuple[str, str | None, int, int]:
    if path is None or not path.is_file():
        return "BLOCKED", "RUN_OUTPUT_MISSING", 0, 0
    if _output_stamp(path) == previous_stamp:
        return "BLOCKED", "RUN_OUTPUT_NOT_REFRESHED", 0, 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = payload.get("report", payload)
        rows = report.get("results")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("results required")
    except (OSError, ValueError, AttributeError):
        return "BLOCKED", "RUN_OUTPUT_INVALID", 0, 0

    def has_model(row):
        value = row.get("model_p")
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1

    allowed_statuses = {"MODEL_CANDIDATE", "PASS", "OFFICIAL_BET", "BLOCKED"}
    models = sum(has_model(row) for row in rows)
    official = sum(row.get("bet_status") == "OFFICIAL_BET" for row in rows)
    if not rows:
        return "BLOCKED", "RUN_RESULTS_EMPTY", models, official
    if any(row.get("bet_status") not in allowed_statuses for row in rows):
        return "BLOCKED", "RUN_DECISION_STATUS_INVALID", models, official

    model_candidates = [
        row for row in rows
        if row.get("bet_status") in {"MODEL_CANDIDATE", "PASS", "OFFICIAL_BET"}
    ]
    true_blockers = [row for row in rows if row.get("bet_status") == "BLOCKED"]

    # A governance block on OFFICIAL promotion is not a failed model run. A row
    # explicitly surfaced as MODEL_CANDIDATE already carries that distinction.
    if not model_candidates:
        return "BLOCKED", "ALL_MARKETS_BLOCKED", models, official
    if payload.get("status") in {"FAILED", "ERROR"}:
        return "BLOCKED", "RUN_REPORTED_BLOCKED", models, official
    if str(report.get("run_status", "")).startswith("BLOCKED") and not model_candidates:
        return "BLOCKED", "RUN_REPORTED_BLOCKED", models, official
    if models == 0 or any(not has_model(row) for row in model_candidates):
        return "BLOCKED", "RUN_MODEL_PROBABILITIES_MISSING", models, official
    if true_blockers or report.get("run_status") == "DEGRADED":
        return "PARTIAL", "SOME_MARKETS_BLOCKED_OR_DEGRADED", models, official
    return "SUCCESS", None, models, official


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
        output_path = _output_path(command, root)
        previous_stamp = _output_stamp(output_path)
        runtime_command = (sys.executable, *command[1:])
        try:
            proc = subprocess.run(
                runtime_command,
                cwd=root,
                env=run_env,
                text=True,
                capture_output=True,
                timeout=int(timeout_seconds),
                check=False,
            )
            status, blocker, model_rows, official_bets = (
                _card_state(output_path, previous_stamp) if proc.returncode == 0
                else ("BLOCKED_OR_FAILED", "ENTRYPOINT_NONZERO", 0, 0)
            )
            results.append(LaneResult(
                sport=sport,
                lane=lane,
                status=status,
                automatic_completeness=completeness,
                execution_status="COMPLETED" if proc.returncode == 0 else "FAILED",
                model_rows=model_rows,
                official_bets=official_bets,
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
    overall = "SUCCESS" if not failed and not blocked else "PARTIAL" if any(row.status in {"SUCCESS", "PARTIAL"} for row in results) else "BLOCKED"
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
