#!/usr/bin/env python3
"""Fail-closed automatic CFB entrypoint for the canonical SportsEdge run machine.

The script never trains a model. It requires a registry-bound frozen CFB joint-model
artifact, CFBD football-data credentials, and a caller-supplied sportsbook board
transcribed from the user's screenshots. It never fetches sportsbook prices from an
odds API. Objective context is a sidecar and never substitutes for Model_P or evidence.

CFBD rate-limit (HTTP 429) handling
------------------------------------
CFBD live fetches inside _run_manual_model are wrapped with _cfbd_fetch_with_retry().
Up to 3 attempts with exponential backoff (2s, 4s). If all attempts are exhausted a
CFBSourceThrottleError is raised. main() catches this separately from hard governance
errors and writes a BLOCKED payload with cfbd_source_status=STALE_CFBD_429 so ops can
distinguish a transient throttle from a real model/governance failure. The run still
blocks — no fabricated features are ever substituted — but with a structured error code
rather than an unhandled exception traceback.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from time import perf_counter
from typing import Callable, Sequence, TypeVar

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.cfb.auto_slate import discover_cfb_auto_games
from sportsedge.sports.cfb.full_auto import build_cfb_full_auto_slate
from sportsedge.sports.cfb.game_freeze import (
    CFBGameFreezeError,
    load_cfb_game_freeze,
    verify_frozen_cfb_game_artifact,
)
from sportsedge.sports.cfb.model_artifact import (
    CFB_MODEL_ARTIFACT_SCHEMA,
    CFBModelArtifactError,
    cfb_model_code_surface_sha256,
    load_cfb_model_artifact,
)
from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH
from sportsedge.sports.cfb.run_machine import run_it_cfb
from sportsedge.sports.cfb.candidate_live_source import fetch_cfbd_candidate_metric_snapshots
from sportsedge.sports.cfb.selected_candidate_artifact import (
    CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA,
    CFBSelectedCandidateArtifactError,
    cfb_selected_candidate_code_surface_sha256,
    load_cfb_selected_candidate_artifact,
)
from sportsedge.sports.cfb.selected_candidate_runtime import run_selected_candidate_cfb_machine
from sportsedge.sports.cfb.source import (
    CFBGame,
    attach_weather,
    build_team_alias_index,
    fetch_cfbd_games,
    fetch_cfbd_team_metrics,
    fetch_cfbd_teams,
    fetch_cfbd_weather,
    parse_the_odds_api_quotes,
)

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class CFBAutoError(ValueError):
    pass


class CFBSourceThrottleError(CFBAutoError):
    """CFBD returned HTTP 429 (rate-limit) and all retry attempts were exhausted."""


# ---------------------------------------------------------------------------
# CFBD fetch retry wrapper
# ---------------------------------------------------------------------------

_T = TypeVar("_T")

_CFBD_MAX_ATTEMPTS = 3
_CFBD_BACKOFF_BASE = 2.0   # seconds; attempt n sleeps base * 2^(n-1): 2s, 4s
_CFBD_BACKOFF_MAX = 10.0   # hard ceiling on any single sleep


def _cfbd_fetch_with_retry(fn: Callable[[], _T], *, label: str) -> _T:
    """Call fn() up to _CFBD_MAX_ATTEMPTS times, retrying on 429 or network errors.

    Parameters
    ----------
    fn:
        Zero-argument callable wrapping the CFBD fetch (use functools.partial or
        a lambda to bind arguments before passing).
    label:
        Short string identifying which fetch is being retried (for error messages).

    Raises
    ------
    CFBSourceThrottleError
        When all attempts are exhausted due to HTTP 429 responses.
    CFBAutoError
        Re-raised immediately for any non-throttle exception on the first attempt;
        subsequent attempts only retry on 429 / connection-level errors.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _CFBD_MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            exc_str = str(exc)
            is_throttle = (
                "429" in exc_str
                or "Too Many Requests" in exc_str
                or "rate limit" in exc_str.lower()
            )
            is_network = (
                "ConnectionError" in type(exc).__name__
                or "Timeout" in type(exc).__name__
                or "ConnectTimeout" in type(exc).__name__
                or "ReadTimeout" in type(exc).__name__
            )
            if not (is_throttle or is_network):
                # Hard failure — not a transient HTTP issue; raise immediately.
                raise
            last_exc = exc
            if attempt < _CFBD_MAX_ATTEMPTS:
                sleep_s = min(_CFBD_BACKOFF_BASE * (2 ** (attempt - 1)), _CFBD_BACKOFF_MAX)
                time.sleep(sleep_s)
    raise CFBSourceThrottleError(
        f"CFB_AUTO_CFBD_THROTTLE:{label}:exhausted {_CFBD_MAX_ATTEMPTS} attempts — {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBAutoError("CFB_AUTO_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBAutoError("CFB_AUTO_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _dt(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBAutoError("CFB_AUTO_GAME_START_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBAutoError("CFB_AUTO_GAME_START_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def discover_cfb_week(
    *,
    season: int,
    now: datetime,
    cfbd_api_key: str,
    game_fetcher: Callable[..., Sequence[CFBGame]] | None = None,
    season_discoverer: Callable[..., dict] = discover_cfb_auto_games,
    max_week: int = 16,
) -> int:
    """Return the earliest regular-season FBS week with a future kickoff.

    Production uses one season-schedule fetch instead of probing every week
    individually. game_fetcher remains an injectable compatibility path for
    deterministic tests and callers that already own week-scoped snapshots.
    """
    if max_week < 0:
        raise CFBAutoError("CFB_AUTO_MAX_WEEK_INVALID")
    candidates: list[tuple[datetime, int]] = []

    if game_fetcher is not None:
        for week in range(0, int(max_week) + 1):
            games = game_fetcher(season=int(season), week=week, cfbd_api_key=cfbd_api_key)
            for game in games:
                start = _dt(game.start_ts)
                if start > now:
                    candidates.append((start, int(game.week)))
    else:
        plan = season_discoverer(
            as_of=now,
            cfbd_api_key=cfbd_api_key,
            season=int(season),
            min_lead_minutes=0,
            horizon_minutes=(int(max_week) + 1) * 7 * 24 * 60,
        )
        for game in plan.get("games") or []:
            week = int(game.get("week"))
            if week < 0 or week > int(max_week):
                continue
            start = _dt(str(game.get("kickoff_ts") or ""))
            if start > now:
                candidates.append((start, week))

    if not candidates:
        raise CFBAutoError("CFB_AUTO_NO_FUTURE_FBS_WEEK")
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][1]


def _credentials() -> str:
    cfbd = str(os.environ.get("SPORTSEDGE_CFBD_API_KEY") or os.environ.get("CFBD_API_KEY") or "").strip()
    if not cfbd:
        raise CFBAutoError("CFB_AUTO_CFBD_API_KEY_REQUIRED")
    return cfbd


def _manual_board(raw: str | None) -> list[dict]:
    text = str(raw or "").strip()
    if not text:
        raise CFBAutoError("CFB_AUTO_MANUAL_BOARD_REQUIRED")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CFBAutoError("CFB_AUTO_MANUAL_BOARD_JSON_INVALID") from exc
    if not isinstance(payload, list) or not payload:
        raise CFBAutoError("CFB_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
    if not all(isinstance(row, dict) for row in payload):
        raise CFBAutoError("CFB_AUTO_MANUAL_BOARD_EVENT_INVALID")
    return payload


def _model(path: Path, *, repo_root: Path):
    """Load only an artifact authorized by the committed freeze registry."""
    if not path.is_file():
        raise CFBAutoError("CFB_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
    try:
        registry = load_cfb_game_freeze(repo_root / "config/cfb_game_model_freeze.json")
    except CFBGameFreezeError as exc:
        raise CFBAutoError(str(exc)) from exc
    expected_path = repo_root / str(registry["artifact_path"])
    if path.resolve() != expected_path.resolve():
        raise CFBAutoError("CFB_AUTO_MODEL_ARTIFACT_PATH_NOT_FROZEN")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBAutoError("CFB_AUTO_MODEL_ARTIFACT_UNREADABLE") from exc

    schema = str(payload.get("schema_version") or "")
    try:
        verify_frozen_cfb_game_artifact(payload, artifact_bytes=raw, registry=registry)
        if schema == CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA:
            code_sha = cfb_selected_candidate_code_surface_sha256(repo_root)
            if code_sha != registry["model_code_sha256"]:
                raise CFBAutoError("CFB_AUTO_MODEL_CODE_SHA256_REGISTRY_MISMATCH")
            model = load_cfb_selected_candidate_artifact(
                payload,
                expected_model_code_sha256=registry["model_code_sha256"],
                expected_training_source_sha256=registry["training_source_sha256"],
            )
            return model, payload, registry, "SELECTED_CANDIDATE"
        if schema == CFB_MODEL_ARTIFACT_SCHEMA:
            code_sha = cfb_model_code_surface_sha256(repo_root)
            if code_sha != registry["model_code_sha256"]:
                raise CFBAutoError("CFB_AUTO_MODEL_CODE_SHA256_REGISTRY_MISMATCH")
            model = load_cfb_model_artifact(
                payload,
                expected_model_code_sha256=registry["model_code_sha256"],
                expected_training_source_sha256=registry["training_source_sha256"],
            )
            return model, payload, registry, "LEGACY_JOINT"
        raise CFBAutoError("CFB_AUTO_MODEL_ARTIFACT_SCHEMA_UNSUPPORTED")
    except (
        CFBModelArtifactError,
        CFBSelectedCandidateArtifactError,
        CFBGameFreezeError,
    ) as exc:
        raise CFBAutoError(str(exc)) from exc


def _objective_context(*, current: datetime, season: int, cfbd_key: str) -> tuple[str, dict | None, str | None]:
    """Acquire optional objective context without turning a sidecar failure into a slate-wide model failure."""
    try:
        payload = build_cfb_full_auto_slate(
            as_of=current,
            cfbd_api_key=cfbd_key,
            season=season,
            mode="AUTO",
            min_lead_minutes=0,
            horizon_minutes=7 * 24 * 60,
        )
        return "AVAILABLE", payload, None
    except Exception as exc:
        return "SOURCE_FAILED", None, f"{type(exc).__name__}:{exc}"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Core model runner — CFBD fetches wrapped with retry
# ---------------------------------------------------------------------------

def _run_manual_model(
    *,
    current: datetime,
    season: int,
    week: int,
    model,
    model_runtime: str,
    frozen_artifact_sha256: str,
    cfbd_key: str,
    manual_events: list[dict],
    bookmakers: tuple[str, ...],
    root_seed: int,
    n_paths: int,
):
    """Run the CFB model against the manual board.

    All CFBD network fetches are wrapped with _cfbd_fetch_with_retry() so a
    transient HTTP 429 triggers exponential backoff rather than immediately
    killing the run. A CFBSourceThrottleError is raised if all retries are
    exhausted; the caller (main) catches it separately from hard governance
    errors and emits a structured BLOCKED payload.
    """
    import functools

    team_rows = _cfbd_fetch_with_retry(
        functools.partial(fetch_cfbd_teams, season=season, cfbd_api_key=cfbd_key),
        label="fetch_cfbd_teams",
    )
    games = _cfbd_fetch_with_retry(
        functools.partial(fetch_cfbd_games, season=season, week=week, cfbd_api_key=cfbd_key),
        label="fetch_cfbd_games",
    )
    weather = _cfbd_fetch_with_retry(
        functools.partial(fetch_cfbd_weather, season=season, week=week, cfbd_api_key=cfbd_key),
        label="fetch_cfbd_weather",
    )
    games = attach_weather(games, weather)
    quotes = parse_the_odds_api_quotes(
        manual_events,
        games=games,
        alias_index=build_team_alias_index(team_rows),
        bookmakers=bookmakers,
    )
    if not quotes:
        raise CFBAutoError("CFB_AUTO_MANUAL_BOARD_NO_MATCHING_QUOTES")
    if model_runtime == "SELECTED_CANDIDATE":
        snapshots = _cfbd_fetch_with_retry(
            functools.partial(
                fetch_cfbd_candidate_metric_snapshots,
                season=season,
                week=week,
                cfbd_api_key=cfbd_key,
                now=current,
            ),
            label="fetch_cfbd_candidate_metric_snapshots",
        )
        return run_selected_candidate_cfb_machine(
            mode="MANUAL",
            season=season,
            week=week,
            model=model,
            now=current,
            games=games,
            candidate_snapshots=snapshots,
            quotes=quotes,
            fbs_team_rows=team_rows,
            root_seed=root_seed,
            n_paths=n_paths,
            frozen_artifact_sha256=frozen_artifact_sha256,
        )
    if model_runtime != "LEGACY_JOINT":
        raise CFBAutoError("CFB_AUTO_MODEL_RUNTIME_UNSUPPORTED")
    metrics = _cfbd_fetch_with_retry(
        functools.partial(
            fetch_cfbd_team_metrics,
            season=season,
            week=week,
            cfbd_api_key=cfbd_key,
            now=current,
        ),
        label="fetch_cfbd_team_metrics",
    )
    return run_it_cfb(
        mode="MANUAL",
        season=season,
        week=week,
        model=model,
        now=current,
        games=games,
        metrics=metrics,
        quotes=quotes,
        fbs_team_rows=team_rows,
        root_seed=root_seed,
        n_paths=n_paths,
    )


def _run_model_and_context(
    *,
    current: datetime,
    season: int,
    week: int,
    model,
    model_runtime: str,
    frozen_artifact_sha256: str,
    cfbd_key: str,
    manual_events: list[dict],
    bookmakers: tuple[str, ...],
    root_seed: int,
    n_paths: int,
):
    """Run the model from screenshot-supplied prices and objective context in parallel."""
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cfb-fast") as pool:
        context_future = pool.submit(
            _objective_context,
            current=current,
            season=season,
            cfbd_key=cfbd_key,
        )
        report_future = pool.submit(
            _run_manual_model,
            current=current,
            season=season,
            week=week,
            model=model,
            model_runtime=model_runtime,
            frozen_artifact_sha256=frozen_artifact_sha256,
            cfbd_key=cfbd_key,
            manual_events=manual_events,
            bookmakers=bookmakers,
            root_seed=root_seed,
            n_paths=n_paths,
        )
        report = report_future.result()  # raises CFBSourceThrottleError here if exhausted
        context_status, objective_context, context_error = context_future.result()
    return report, context_status, objective_context, context_error


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--asof")
    parser.add_argument(
        "--board-json",
        help="Manual sportsbook board JSON transcribed from screenshots; same event/bookmaker shape accepted by the quote parser.",
    )
    parser.add_argument("--model-artifact", type=Path, default=DEFAULT_CFB_MODEL_ARTIFACT_PATH)
    parser.add_argument("--bookmaker", action="append", dest="bookmakers")
    parser.add_argument("--n-paths", type=int, default=20000)
    parser.add_argument("--root-seed", type=int, default=20260826)
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_card.json"))
    args = parser.parse_args()

    root = _REPO_ROOT
    current = _utc(args.asof)
    try:
        cfbd_key = _credentials()
        model, artifact, registry, model_runtime = _model(args.model_artifact, repo_root=root)
        manual_events = _manual_board(args.board_json or os.environ.get("CFB_MANUAL_BOARD_JSON"))
        season = int(args.season if args.season is not None else current.year)
        week = int(args.week) if args.week is not None else discover_cfb_week(
            season=season,
            now=current,
            cfbd_api_key=cfbd_key,
        )
        started = perf_counter()
        report, context_status, objective_context, context_error = _run_model_and_context(
            current=current,
            season=season,
            week=week,
            model=model,
            model_runtime=model_runtime,
            frozen_artifact_sha256=artifact["artifact_sha256"],
            cfbd_key=cfbd_key,
            manual_events=manual_events,
            bookmakers=tuple(args.bookmakers or ["draftkings"]),
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
        )
        elapsed_seconds = round(perf_counter() - started, 3)
        report_payload = report.to_dict()
        board = (report_payload.get("summary") or {}).get("full_board") or {}
        board_summary = board.get("summary") or {}
        from sportsedge.football_full_board import catalog_complete
        payload = {
            "schema_version": "CFB_AUTO_RUN_V1",
            "status": "SUCCESS",
            "run_status": report.run_status,
            "full_board": board,
            "summary": {
                "both_sides": board_summary.get("both_sides"),
                "side_rows": board_summary.get("side_rows"),
                "total_rows": board_summary.get("total_rows"),
                "prop_rows": board_summary.get("prop_rows"),
                "catalog_complete": catalog_complete(board_summary),
            },
            "market_input_source": "MANUAL_SCREENSHOT_BOARD",
            "season": season,
            "week": week,
            "model_artifact_sha256": artifact["artifact_sha256"],
            "model_code_sha256": artifact["model_code_sha256"],
            "training_source_sha256": artifact["training_source_sha256"],
            "game_freeze_registry_sha256": registry["registry_sha256"],
            "model_runtime": model_runtime,
            "objective_context_status": context_status,
            "objective_context_error": context_error,
            "objective_context": objective_context,
            "report": report_payload,
            "runtime": {
                "model_and_context_parallel": True,
                "elapsed_seconds": elapsed_seconds,
            },
            "governance": {
                "model_fit_performed": False,
                "objective_context_is_model_p": False,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True,
                "context_failure_is_scoped": True,
                "training_source_env_override_allowed": False,
                "sportsbook_api_used": False,
                "manual_market_board_required": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps({
            "status": "SUCCESS",
            "season": season,
            "week": week,
            "run_status": report.run_status,
            "objective_context_status": context_status,
            "both_sides": payload["summary"]["both_sides"],
            "side_rows": payload["summary"]["side_rows"],
            "total_rows": payload["summary"]["total_rows"],
            "prop_rows": payload["summary"]["prop_rows"],
            "catalog_complete": payload["summary"]["catalog_complete"],
            "elapsed_seconds": elapsed_seconds,
            "output": str(args.output),
        }, sort_keys=True))
        return 0

    except CFBSourceThrottleError as exc:
        # CFBD returned 429 and all retries were exhausted. This is a data-source
        # infrastructure failure, not a governance or model failure. Emit a structured
        # BLOCKED payload with a distinct blocker code so ops can distinguish a transient
        # throttle from a hard governance error.
        from sportsedge.football_full_board import board_from_machine_results, catalog_complete
        board = board_from_machine_results("CFB", [])
        payload = {
            "schema_version": "CFB_AUTO_RUN_V1",
            "status": "BLOCKED",
            "blocker": "CFB_AUTO_CFBD_THROTTLE",
            "cfbd_source_status": "STALE_CFBD_429",
            "cfbd_source_error": str(exc),
            "generated_at_utc": current.isoformat(),
            "full_board": board,
            "summary": {
                "both_sides": board["summary"]["both_sides"],
                "side_rows": board["summary"]["side_rows"],
                "total_rows": board["summary"]["total_rows"],
                "prop_rows": board["summary"]["prop_rows"],
                "catalog_complete": catalog_complete(board["summary"]),
            },
            "report": board,
            "governance": {
                "model_fit_performed": False,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True,
                "context_failure_is_scoped": True,
                "sportsbook_api_used": False,
                "manual_market_board_required": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    except (CFBAutoError, ValueError) as exc:
        from sportsedge.football_full_board import board_from_machine_results, catalog_complete
        board = board_from_machine_results("CFB", [])
        payload = {
            "schema_version": "CFB_AUTO_RUN_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "full_board": board,
            "summary": {
                "both_sides": board["summary"]["both_sides"],
                "side_rows": board["summary"]["side_rows"],
                "total_rows": board["summary"]["total_rows"],
                "prop_rows": board["summary"]["prop_rows"],
                "catalog_complete": catalog_complete(board["summary"]),
            },
            "report": board,
            "governance": {
                "model_fit_performed": False,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True,
                "sportsbook_api_used": False,
                "manual_market_board_required": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
