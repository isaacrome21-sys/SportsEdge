#!/usr/bin/env python3
"""Build the fail-closed SportsEdge daily operations digest.

This v2 digest makes three states structurally distinct:
- NO DATA / genuinely nothing scheduled,
- NEVER RAN / scheduled execution absent,
- RAN / GitHub reported a real conclusion.

Zeros and nulls are never interpreted as successful evidence. Odds API usage is
compared with a committed schedule-derived upper-bound projection only when a
complete provider counter delta can be established; otherwise the judgment is
UNKNOWN and fails closed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

UTC = timezone.utc
CT = ZoneInfo("America/Chicago")
DEFAULT_PROJECTION = "config/odds_api_request_projection_v1.json"
LANES = (
    ("MLB", "MLB raw odds archive", "archive-mlb-game-odds.yml", "archive-status"),
    ("MLB", "MLB additional PIT", "mlb-additional-pit-archive.yml", None),
    ("MLB", "MLB prop PIT", "mlb-prop-pit-archive.yml", None),
    ("NFL", "NFL forward CLV", "football-nfl-forward-clv-collection.yml", "nfl-forward"),
    ("CFB", "Football public splits", "football-public-splits.yml", None),
)
_TS_KEYS = (
    "run_at_utc", "generated_at_utc", "captured_at_utc", "captured_at",
    "decision_at", "decision_ts", "created_at", "asof_ts", "now",
)
_ERROR_RE = re.compile(
    r"(##\[error\].*|Traceback.*|(?:[A-Z][A-Z0-9_]{5,})(?::[^\r\n]*)?|"
    r"FAILED\s+[^\r\n]+|(?:Error|Exception):[^\r\n]+)"
)
_NEEDS_ISAAC_RE = re.compile(
    r"(OUT_OF_USAGE_CREDITS|BLOCKED_NO_ODDS_KEY|NO_ODDS_KEY|HTTP\s*401|"
    r"\b401\b.*(?:ODDS|KEY|TOKEN)|quota exhaustion|rate limit.*exhausted)",
    re.I,
)


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    if out.tzinfo is None or out.utcoffset() is None:
        return None
    return out.astimezone(UTC)


def _api(path: str, *, token: str, repo: str) -> Any:
    req = Request(
        f"https://api.github.com/repos/{repo}/{path.lstrip('/')}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SportsEdge-daily-digest/2",
        },
    )
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_bytes(path: str, *, token: str, repo: str) -> bytes:
    req = Request(
        f"https://api.github.com/repos/{repo}/{path.lstrip('/')}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SportsEdge-daily-digest/2",
        },
    )
    with urlopen(req, timeout=30) as response:
        return response.read()


def _recent_runs(*, token: str, repo: str, cutoff: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, 11):
        payload = _api(f"actions/runs?per_page=100&page={page}", token=token, repo=repo)
        rows = payload.get("workflow_runs") or []
        if not rows:
            break
        saw_old = False
        for row in rows:
            created = _dt(row.get("created_at"))
            if created is None:
                continue
            if created < cutoff:
                saw_old = True
                continue
            out.append(dict(row))
        if saw_old:
            break
    return out


def _failed_error(run: Mapping[str, Any], *, token: str, repo: str) -> str:
    try:
        jobs = _api(f"actions/runs/{run['id']}/jobs?per_page=100", token=token, repo=repo).get("jobs") or []
    except Exception as exc:
        return f"ERROR LOG UNAVAILABLE: {type(exc).__name__}"
    failed = [job for job in jobs if job.get("conclusion") == "failure"]
    if not failed:
        return "ERROR STRING NO DATA"
    job = failed[0]
    steps = job.get("steps")
    runner_id = job.get("runner_id")
    runner_name = str(job.get("runner_name") or "").strip()
    if not steps and not runner_id and not runner_name:
        return f"{job.get('name')}: RUNNER NEVER ASSIGNED — steps=0 runner_id=0 runner_name=blank"
    failed_steps = [step.get("name") for step in (steps or []) if step.get("conclusion") == "failure"]
    prefix = f"{job.get('name')}: " + (", ".join(str(x) for x in failed_steps if x) or "failed")
    try:
        raw = _api_bytes(f"actions/jobs/{job['id']}/logs", token=token, repo=repo).decode("utf-8", errors="replace")
    except Exception:
        return prefix + " — ERROR STRING NO DATA"
    matches = [match.group(0).strip() for match in _ERROR_RE.finditer(raw)]
    return prefix + (" — " + matches[-1][:350] if matches else " — ERROR STRING NO DATA")


def _failure_details(
    failures: Sequence[Mapping[str, Any]], *, token: str, repo: str
) -> dict[int, str]:
    def one(run: Mapping[str, Any]) -> tuple[int, str]:
        return int(run["id"]), _failed_error(run, token=token, repo=repo)

    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, failures))


def _field_values(field: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(lo, hi + 1))
        elif part.startswith("*/"):
            values.update(range(lo, hi + 1, int(part[2:])))
        elif "-" in part:
            start, end = part.split("-", 1)
            values.update(range(int(start), int(end) + 1))
        else:
            values.add(int(part))
    return values


def _cron_matches(expr: str, when: datetime) -> bool:
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    cron_dow = (when.weekday() + 1) % 7
    return (
        when.minute in _field_values(minute, 0, 59)
        and when.hour in _field_values(hour, 0, 23)
        and when.day in _field_values(dom, 1, 31)
        and when.month in _field_values(month, 1, 12)
        and cron_dow in _field_values(dow, 0, 6)
    )


def _workflow_crons(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8"))


def _scheduled_points(crons: Sequence[str], cutoff: datetime, now: datetime) -> list[datetime]:
    cursor = cutoff.replace(second=0, microsecond=0)
    if cursor < cutoff:
        cursor += timedelta(minutes=1)
    out: list[datetime] = []
    while cursor <= now:
        if any(_cron_matches(expr, cursor) for expr in crons):
            out.append(cursor)
        cursor += timedelta(minutes=1)
    return out


def _expected_runs(path: Path, cutoff: datetime, now: datetime) -> int | None:
    crons = _workflow_crons(path)
    if not crons:
        return None
    return len(_scheduled_points(crons, cutoff, now))


def _rows_from_json_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _row_time(row: Mapping[str, Any]) -> datetime | None:
    for key in _TS_KEYS:
        value = _dt(row.get(key))
        if value is not None:
            return value
    return None


def _data_rows_since(data_root: Path, earliest: datetime) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    if not data_root.exists():
        return out
    for path in data_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        for row in _rows_from_json_file(path):
            stamp = _row_time(row)
            if stamp is not None and stamp >= earliest:
                out.append((path, row))
    return out


def _capture_count(data_rows: Sequence[tuple[Path, Mapping[str, Any]]], lane_key: str | None) -> str:
    if lane_key is None:
        return "NOT CONFIGURED"
    matching = [(path, row) for path, row in data_rows if lane_key in str(path)]
    if not matching:
        return "NO DATA"
    if lane_key == "archive-status":
        captured = sum(str(row.get("status") or "").upper() == "CAPTURED" for _, row in matching)
        return f"{captured} durable CAPTURED records"
    if lane_key == "nfl-forward":
        decisions = sum(path.name == "decisions.jsonl" for path, _ in matching)
        closes = sum(path.name == "closes.jsonl" for path, _ in matching)
        return f"{decisions} decision rows / {closes} close rows"
    return "NO DATA"


def _lane_health(
    *,
    expected: int | None,
    lane_runs: Sequence[Mapping[str, Any]],
    durable: str,
    durable_required: bool,
) -> dict[str, Any]:
    ran = len(lane_runs)
    passed = sum(row.get("conclusion") == "success" for row in lane_runs)
    failed = sum(row.get("conclusion") == "failure" for row in lane_runs)
    skipped = sum(row.get("conclusion") == "skipped" for row in lane_runs)

    if expected is None or expected == 0:
        state = "NO DATA — NOTHING SCHEDULED"
    elif ran == 0:
        state = "FAILURE — NEVER RAN"
    elif passed == 0:
        state = "FAILURE — 0% SUCCESS"
    elif durable_required and durable == "NO DATA":
        state = "FAILURE — RAN/PASSED BUT NO DURABLE EVIDENCE"
    elif failed > 0 or skipped > 0:
        state = "DEGRADED — PARTIAL SUCCESS"
    else:
        state = "PASS — RAN AND PASSED"

    return {
        "state": state,
        "expected": expected,
        "ran": ran,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "success_rate": (passed / ran) if ran else None,
    }


def _blocked_rows(data_rows: Sequence[tuple[Path, Mapping[str, Any]]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path, row in data_rows:
        statuses = {
            str(row.get(key) or "").upper()
            for key in ("status", "bet_status", "engine_status", "truth_gate_status")
        }
        if "BLOCKED" not in statuses and not any(value.startswith("BLOCKED_") for value in statuses):
            continue
        reason = str(row.get("reason") or row.get("blocked_reason") or row.get("error") or "STRUCTURED REASON NO DATA")
        market = str(row.get("market") or row.get("market_id") or "UNKNOWN_MARKET")
        game = str(row.get("game") or row.get("game_id") or row.get("event_id") or "UNKNOWN_EVENT")
        item = f"{market} | {game} | {reason} | {path}"
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:100]


def _mlb_schedule(now: datetime, *, days_back: int = 1, days_forward: int = 1) -> tuple[list[tuple[str, datetime]], str | None]:
    start = (now.astimezone(CT).date() - timedelta(days=days_back)).isoformat()
    end = (now.astimezone(CT).date() + timedelta(days=days_forward)).isoformat()
    params = urlencode({"sportId": 1, "startDate": start, "endDate": end})
    try:
        req = Request(
            f"https://statsapi.mlb.com/api/v1/schedule?{params}",
            headers={"User-Agent": "SportsEdge-daily-digest/2"},
        )
        with urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [], f"MLB schedule unavailable: {type(exc).__name__}"
    games: list[tuple[str, datetime]] = []
    for date_row in payload.get("dates") or []:
        for game in date_row.get("games") or []:
            start_at = _dt(game.get("gameDate"))
            if start_at is not None:
                games.append((str(game.get("gamePk") or "UNKNOWN_GAME"), start_at))
    return games, None


def _mlb_windows(now: datetime, games: Sequence[tuple[str, datetime]]) -> list[str]:
    out: list[str] = []
    for game_id, start in games:
        for before in (180, 90, 0):
            point = start - timedelta(minutes=before)
            if now <= point <= now + timedelta(hours=24):
                out.append(f"MLB {game_id} T-{before} capture {point.isoformat()}")
    return sorted(out)


def _nfl_windows(now: datetime) -> tuple[list[str], str | None]:
    url = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    try:
        with urlopen(Request(url, headers={"User-Agent": "SportsEdge-daily-digest/2"}), timeout=20) as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
    except Exception as exc:
        return [], f"NFL schedule unavailable: {type(exc).__name__}"
    eastern = ZoneInfo("America/New_York")
    out: list[str] = []
    for row in rows:
        if str(row.get("game_type") or "").upper() != "REG":
            continue
        day = str(row.get("gameday") or "").strip()
        clock = str(row.get("gametime") or "").strip()
        if not day or not clock:
            continue
        try:
            local = datetime.combine(
                datetime.fromisoformat(day[:10]).date(),
                datetime.strptime(clock, "%H:%M").time(),
                tzinfo=eastern,
            )
            start = local.astimezone(UTC)
        except Exception:
            continue
        if not (now < start <= now + timedelta(hours=26)):
            continue
        game_id = str(row.get("game_id") or "UNKNOWN_GAME")
        for label, before in (("decision-start", 120), ("decision-end", 45), ("close-start", 20), ("close-end", 2)):
            point = start - timedelta(minutes=before)
            if now <= point <= now + timedelta(hours=24):
                out.append(f"NFL {game_id} {label} {point.isoformat()}")
    return sorted(out), None


def _load_projection(repo_root: Path) -> dict[str, Any]:
    path = repo_root / DEFAULT_PROJECTION
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"ODDS_PROJECTION_UNAVAILABLE:{type(exc).__name__}") from exc
    if not isinstance(value, dict) or value.get("version") != "odds_api_request_projection_v1":
        raise ValueError("ODDS_PROJECTION_INVALID_VERSION")
    callers = value.get("scheduled_callers")
    if not isinstance(callers, list) or not callers:
        raise ValueError("ODDS_PROJECTION_NO_SCHEDULED_CALLERS")
    return value


def _archive_paid_point(point: datetime, games: Sequence[tuple[str, datetime]]) -> bool:
    for _, start in games:
        minutes_to = (start - point).total_seconds() / 60.0
        if any(abs(minutes_to - target) <= 8.0 for target in (180, 90, 0)):
            return True
    return False


def _projection_for_window(
    *,
    repo_root: Path,
    config: Mapping[str, Any],
    cutoff: datetime,
    now: datetime,
    games: Sequence[tuple[str, datetime]],
) -> tuple[dict[str, Any] | None, list[str]]:
    needs: list[str] = []
    rows: list[dict[str, Any]] = []
    total_http = 0
    total_credits = 0
    game_counts: dict[str, int] = {}
    for _, start in games:
        day = start.astimezone(CT).date().isoformat()
        game_counts[day] = game_counts.get(day, 0) + 1

    for caller in config.get("scheduled_callers") or []:
        workflow = str(caller.get("workflow") or "")
        configured_crons = [str(x) for x in (caller.get("cron") or [])]
        live_crons = _workflow_crons(repo_root / ".github" / "workflows" / workflow)
        if sorted(configured_crons) != sorted(live_crons):
            needs.append(f"ODDS PROJECTION UNKNOWN — cron drift for {workflow}: config={configured_crons}, live={live_crons}")
            return None, needs
        points = _scheduled_points(configured_crons, cutoff, now)
        http = 0
        credits = 0
        paid_runs = 0
        if workflow == "archive-mlb-game-odds.yml":
            paid_runs = sum(_archive_paid_point(point, games) for point in points)
            http = paid_runs
            credits = paid_runs * 3
        elif workflow == "auto-mlb.yml":
            paid_runs = len(points)
            for point in points:
                games_for_day = game_counts.get(point.astimezone(CT).date().isoformat(), 0)
                http += 4 + (3 * games_for_day)
                credits += 3 + (40 * games_for_day)
        else:
            needs.append(f"ODDS PROJECTION UNKNOWN — unsupported scheduled caller formula: {workflow}")
            return None, needs
        total_http += http
        total_credits += credits
        rows.append({
            "workflow": workflow,
            "scheduled_runs": len(points),
            "paid_run_upper_bound": paid_runs,
            "http_request_upper_bound": http,
            "provider_credit_upper_bound": credits,
        })
    return {
        "rows": rows,
        "http_request_upper_bound": total_http,
        "provider_credit_upper_bound": total_credits,
    }, needs


def _known_counter_delta(
    data_rows: Sequence[tuple[Path, Mapping[str, Any]]], *, cutoff: datetime, now: datetime
) -> tuple[int | None, str]:
    observations: dict[str, list[tuple[datetime, int]]] = {}
    for path, row in data_rows:
        if "archive-status" not in str(path) and "provider" not in str(path).lower():
            continue
        stamp = _row_time(row)
        if stamp is None or stamp > now:
            continue
        used = row.get("provider_credits_used")
        if used is None:
            continue
        try:
            value = int(used)
        except (TypeError, ValueError):
            return None, "UNKNOWN — invalid provider_credits_used counter"
        slot = str(row.get("key_slot") or "UNSPECIFIED")
        observations.setdefault(slot, []).append((stamp, value))

    if not observations:
        return None, "UNKNOWN — no provider cumulative counter observations"

    total = 0
    usable_slots = 0
    for slot, points in observations.items():
        points.sort(key=lambda item: item[0])
        before = [item for item in points if item[0] <= cutoff]
        after = [item for item in points if cutoff < item[0] <= now]
        if not before or not after:
            continue
        baseline = before[-1]
        latest = after[-1]
        if latest[1] < baseline[1]:
            return None, f"UNKNOWN — provider counter reset/non-monotonic for key slot {slot}"
        usable_slots += 1
        total += latest[1] - baseline[1]
    if usable_slots == 0:
        return None, "UNKNOWN — no key slot has both baseline and in-window cumulative counters"
    return total, f"KNOWN across {usable_slots} key slot(s) with baseline + in-window counters"


def _durable_credit_sum(
    data_rows: Sequence[tuple[Path, Mapping[str, Any]]], *, cutoff: datetime, now: datetime
) -> tuple[int | None, str]:
    relevant = []
    for path, row in data_rows:
        if "archive-status" not in str(path):
            continue
        stamp = _row_time(row)
        if stamp is not None and cutoff < stamp <= now:
            relevant.append(row)
    if not relevant:
        return None, "NO DATA"
    total = 0
    for row in relevant:
        value = row.get("credits_consumed_actual")
        if value is None:
            return None, "UNKNOWN — null credits_consumed_actual"
        try:
            total += int(value)
        except (TypeError, ValueError):
            return None, "UNKNOWN — invalid credits_consumed_actual"
    return total, "KNOWN FOR ARCHIVE STATUS ROWS ONLY"


def _odds_usage(
    *,
    repo_root: Path,
    data_rows: Sequence[tuple[Path, Mapping[str, Any]]],
    cutoff: datetime,
    now: datetime,
    games: Sequence[tuple[str, datetime]],
) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    needs: list[str] = []
    try:
        config = _load_projection(repo_root)
    except Exception as exc:
        return [f"- projection UNKNOWN — {exc}"], [str(exc)]

    projection, projection_needs = _projection_for_window(
        repo_root=repo_root, config=config, cutoff=cutoff, now=now, games=games
    )
    needs.extend(projection_needs)
    if projection is None:
        return ["- projected usage UNKNOWN — projection contract drift/unavailable"], needs

    for row in projection["rows"]:
        lines.append(
            "- projected "
            f"{row['workflow']}: scheduled-runs={row['scheduled_runs']}, "
            f"paid-run-upper-bound={row['paid_run_upper_bound']}, "
            f"http-request-upper-bound={row['http_request_upper_bound']}, "
            f"provider-credit-upper-bound={row['provider_credit_upper_bound']}"
        )
    lines.append(
        f"- projected TOTAL: http-request-upper-bound={projection['http_request_upper_bound']}; "
        f"provider-credit-upper-bound={projection['provider_credit_upper_bound']}"
    )

    archive_sum, archive_state = _durable_credit_sum(data_rows, cutoff=cutoff, now=now)
    lines.append(
        f"- durable archive reported credits: {'UNKNOWN' if archive_sum is None else archive_sum} ({archive_state})"
    )

    actual, actual_state = _known_counter_delta(data_rows, cutoff=cutoff, now=now)
    lines.append(f"- actual provider cumulative-counter delta: {'UNKNOWN' if actual is None else actual} ({actual_state})")
    if actual is None:
        lines.append("- actual-vs-projected judgment: UNKNOWN — blocked because actual usage is not fully known")
        needs.append("Odds API actual-vs-projected judgment is UNKNOWN; cumulative counter baseline/in-window evidence is incomplete")
        return lines, needs

    upper = int(projection["provider_credit_upper_bound"])
    excess = actual - upper
    material_cfg = config.get("material_excess") or {}
    absolute = int(material_cfg.get("absolute_credits", 5))
    fraction = float(material_cfg.get("fraction_of_projected_upper_bound", 0.1))
    threshold = max(absolute, int(round(upper * fraction)))
    if excess > threshold:
        lines.append(
            f"- actual-vs-projected judgment: ANOMALY — actual={actual} exceeds projected upper bound={upper} "
            f"by {excess} credits; material threshold={threshold}"
        )
        needs.append(
            f"UNACCOUNTED PAID-ENDPOINT USAGE SUSPECTED: actual provider delta {actual} > declared upper bound {upper} by {excess} credits"
        )
    else:
        lines.append(
            f"- actual-vs-projected judgment: WITHIN DECLARED UPPER BOUND — actual={actual}, upper={upper}, excess={excess}"
        )
    return lines, needs


def build_digest(*, repo_root: Path, data_root: Path, token: str, repo: str, now: datetime) -> str:
    cutoff = now - timedelta(hours=24)
    runs = _recent_runs(token=token, repo=repo, cutoff=cutoff)
    data_rows = _data_rows_since(data_root, cutoff - timedelta(days=2))
    recent_data_rows = [(path, row) for path, row in data_rows if (_row_time(row) or datetime.min.replace(tzinfo=UTC)) >= cutoff]
    failures = [run for run in runs if run.get("conclusion") == "failure"]
    failure_details = _failure_details(failures, token=token, repo=repo) if failures else {}

    lane_health: list[dict[str, Any]] = []
    for sport, label, workflow, lane_key in LANES:
        workflow_name = workflow.removesuffix(".yml")
        lane_runs = [run for run in runs if run.get("name") == workflow_name and run.get("event") == "schedule"]
        expected = _expected_runs(repo_root / ".github" / "workflows" / workflow, cutoff, now)
        durable = _capture_count(recent_data_rows, lane_key)
        health = _lane_health(
            expected=expected,
            lane_runs=lane_runs,
            durable=durable,
            durable_required=lane_key is not None,
        )
        health.update({
            "sport": sport,
            "label": label,
            "workflow": workflow,
            "runs": lane_runs,
            "durable": durable,
        })
        lane_health.append(health)

    zero_success = [
        row for row in lane_health
        if row["expected"] not in (None, 0) and row["passed"] == 0
    ]
    lines = [
        "# SportsEdge Daily Digest",
        "",
        f"Generated: {now.isoformat()}",
        f"Window: {cutoff.isoformat()} → {now.isoformat()}",
        "",
    ]
    if len(zero_success) >= 2:
        lines += [
            "# 🚨 SYSTEM OUTAGE",
            f"- {len(zero_success)} monitored lanes are at 0% success over an expected schedule window.",
            "",
        ]

    critical = [row for row in lane_health if str(row["state"]).startswith("FAILURE")]
    lines += ["## Critical capture failures"]
    if not critical:
        lines.append("- None.")
    else:
        for row in critical:
            lane_failures = sorted(
                [run for run in row["runs"] if run.get("conclusion") == "failure"],
                key=lambda run: run.get("created_at") or "",
            )
            detail = "ERROR STRING NO DATA"
            first = last = "NO DATA"
            first_id = last_id = "NO DATA"
            if lane_failures:
                first_run, last_run = lane_failures[0], lane_failures[-1]
                first = str(first_run.get("created_at") or "NO DATA")
                last = str(last_run.get("created_at") or "NO DATA")
                first_id = str(first_run.get("id") or "NO DATA")
                last_id = str(last_run.get("id") or "NO DATA")
                detail = failure_details.get(int(last_run["id"]), "ERROR STRING NO DATA")
            lines.append(
                f"- **{row['sport']} — {row['label']}: {row['state']}**; "
                f"passed={row['passed']}/{row['ran']}; expected={row['expected']}; "
                f"first_failure={first} run={first_id}; last_failure={last} run={last_id}; latest_error={detail}"
            )

    lines += ["", "## Capture / execution lanes"]
    for row in lane_health:
        expected_text = "NO DATA" if row["expected"] is None else str(row["expected"])
        lines.append(
            f"- **{row['sport']} — {row['label']}: {row['state']}**; "
            f"expected={expected_text}, scheduled-runs-seen={row['ran']}, passed={row['passed']}, "
            f"failed={row['failed']}, skipped={row['skipped']}; durable capture evidence: {row['durable']}"
        )

    lines += ["", "## Workflow failures — last 24h"]
    if not failures:
        lines.append("- None observed among runs returned by GitHub.")
    else:
        for run in sorted(failures, key=lambda item: item.get("created_at") or ""):
            lines.append(
                f"- {run.get('name')} run {run.get('id')} — "
                f"{failure_details.get(int(run['id']), 'ERROR STRING NO DATA')}"
            )

    lines += ["", "## BLOCKED markets"]
    blocked = _blocked_rows(recent_data_rows)
    lines.extend(
        [f"- {item}" for item in blocked]
        if blocked
        else ["- NO DATA — no timestamped structured BLOCKED market rows were found in the durable data branch for this window."]
    )

    games, mlb_error = _mlb_schedule(now)
    nfl, nfl_error = _nfl_windows(now)
    windows = sorted(nfl + _mlb_windows(now, games))
    lines += ["", "## Upcoming decision / capture windows — next 24h"]
    lines.extend([f"- {item}" for item in windows] if windows else ["- NO DATA — no upcoming window records were resolved."])
    if nfl_error:
        lines.append(f"- {nfl_error}")
    if mlb_error:
        lines.append(f"- {mlb_error}")

    odds_lines, odds_needs = _odds_usage(
        repo_root=repo_root,
        data_rows=data_rows,
        cutoff=cutoff,
        now=now,
        games=games,
    )
    lines += ["", "## Odds API usage", *odds_lines]

    needs: list[str] = []
    for row in lane_health:
        if row["expected"] in (None, 0):
            continue
        if row["state"] != "PASS — RAN AND PASSED":
            needs.append(
                f"{row['sport']} — {row['label']}: {row['state']} "
                f"(passed={row['passed']}/{row['ran']}, expected={row['expected']})"
            )
    for run in failures:
        error = failure_details.get(int(run["id"]), "ERROR STRING NO DATA")
        if _NEEDS_ISAAC_RE.search(error):
            needs.append(f"{run.get('name')} run {run.get('id')}: {error}")
    needs.extend(odds_needs)
    needs = list(dict.fromkeys(needs))

    lines += ["", "## NEEDS ISAAC"]
    if needs:
        lines.extend(f"- {item}" for item in needs)
    else:
        scheduled = [row for row in lane_health if row["expected"] not in (None, 0)]
        if scheduled and all(row["passed"] > 0 and row["state"] == "PASS — RAN AND PASSED" for row in scheduled):
            lines.append("- NONE OBSERVED — every scheduled monitored lane has a known non-zero successful execution state.")
        else:
            lines.append("- UNKNOWN — insufficient evidence to assert NONE.")

    lines += [
        "",
        "## Interpretation rules",
        "- NO DATA means evidence was unavailable or genuinely nothing was scheduled; it never means success.",
        "- NEVER RAN means a schedule expected execution but GitHub returned no scheduled run.",
        "- RAN AND PASSED requires at least one concrete GitHub success and no lane-level failure condition.",
        "- A null or invalid usage counter is UNKNOWN, never zero.",
        "- Actual-vs-projected Odds API judgment is blocked unless cumulative provider counter evidence is sufficient.",
        "- This digest never promotes a market and never changes Truth Gate state.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--now")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token:
        raise SystemExit("DAILY_DIGEST_GITHUB_TOKEN_REQUIRED")
    if not repo:
        raise SystemExit("DAILY_DIGEST_GITHUB_REPOSITORY_REQUIRED")
    now = _dt(args.now) if args.now else datetime.now(UTC)
    if now is None:
        raise SystemExit("DAILY_DIGEST_NOW_INVALID")
    result = build_digest(
        repo_root=args.repo_root,
        data_root=args.data_root,
        token=token,
        repo=repo,
        now=now,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result, encoding="utf-8")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
