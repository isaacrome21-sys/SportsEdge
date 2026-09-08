#!/usr/bin/env python3
"""Build a fail-closed, phone-readable SportsEdge daily operations digest."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.request import Request, urlopen
from urllib.parse import urlencode

UTC = timezone.utc
LANES = (
    ("MLB", "MLB raw odds archive", "archive-mlb-game-odds.yml", "archive-status"),
    ("MLB", "MLB additional PIT", "mlb-additional-pit-archive.yml", None),
    ("MLB", "MLB prop PIT", "mlb-prop-pit-archive.yml", None),
    ("NFL", "NFL forward CLV", "football-nfl-forward-clv-collection.yml", "nfl-forward"),
    ("CFB", "Football public splits", "football-public-splits.yml", None),
)
_TS_KEYS = ("run_at_utc","generated_at_utc","captured_at_utc","captured_at","decision_at","decision_ts","created_at","asof_ts","now")
_ERROR_RE = re.compile(r"(##\[error\].*|Traceback.*|(?:[A-Z][A-Z0-9_]{5,})(?::[^\r\n]*)?|FAILED\s+[^\r\n]+|(?:Error|Exception):[^\r\n]+)")
_NEEDS_ISAAC_RE = re.compile(r"(OUT_OF_USAGE_CREDITS|BLOCKED_NO_ODDS_KEY|NO_ODDS_KEY|HTTP\s*401|\b401\b.*(?:ODDS|KEY|TOKEN)|quota exhaustion|rate limit.*exhausted)", re.I)


def _dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
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
    req = Request(f"https://api.github.com/repos/{repo}/{path.lstrip('/')}", headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SportsEdge-daily-digest/1",
    })
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_bytes(path: str, *, token: str, repo: str) -> bytes:
    req = Request(f"https://api.github.com/repos/{repo}/{path.lstrip('/')}", headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SportsEdge-daily-digest/1",
    })
    with urlopen(req, timeout=30) as response:
        return response.read()


def _recent_runs(*, token: str, repo: str, cutoff: datetime) -> list[dict[str, Any]]:
    out = []
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


def _failed_error(run: dict[str, Any], *, token: str, repo: str) -> str:
    try:
        jobs = _api(f"actions/runs/{run['id']}/jobs?per_page=100", token=token, repo=repo).get("jobs") or []
    except Exception as exc:
        return f"ERROR LOG UNAVAILABLE: {type(exc).__name__}"
    failed = [j for j in jobs if j.get("conclusion") == "failure"]
    if not failed:
        return "ERROR STRING NO DATA"
    job = failed[0]
    failed_steps = [s.get("name") for s in (job.get("steps") or []) if s.get("conclusion") == "failure"]
    prefix = f"{job.get('name')}: " + (", ".join(str(x) for x in failed_steps if x) or "failed")
    try:
        raw = _api_bytes(f"actions/jobs/{job['id']}/logs", token=token, repo=repo).decode("utf-8", errors="replace")
    except Exception:
        return prefix + " — ERROR STRING NO DATA"
    matches = [m.group(0).strip() for m in _ERROR_RE.finditer(raw)]
    return prefix + (" — " + matches[-1][:350] if matches else " — ERROR STRING NO DATA")


def _failure_details(failures: list[dict[str, Any]], *, token: str, repo: str) -> dict[int, str]:
    def one(run: dict[str, Any]) -> tuple[int, str]:
        return int(run["id"]), _failed_error(run, token=token, repo=repo)
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, failures))


def _field_values(field: str, lo: int, hi: int) -> set[int]:
    vals = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            vals.update(range(lo, hi + 1))
        elif part.startswith("*/"):
            vals.update(range(lo, hi + 1, int(part[2:])))
        elif "-" in part:
            a, b = part.split("-", 1)
            vals.update(range(int(a), int(b) + 1))
        else:
            vals.add(int(part))
    return vals


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


def _expected_runs(path: Path, cutoff: datetime, now: datetime) -> int | None:
    crons = _workflow_crons(path)
    if not crons:
        return None
    cursor = cutoff.replace(second=0, microsecond=0)
    if cursor < cutoff:
        cursor += timedelta(minutes=1)
    count = 0
    while cursor <= now:
        if any(_cron_matches(expr, cursor) for expr in crons):
            count += 1
        cursor += timedelta(minutes=1)
    return count


def _rows_from_json_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def _row_time(row: dict[str, Any]) -> datetime | None:
    for key in _TS_KEYS:
        out = _dt(row.get(key))
        if out is not None:
            return out
    return None


def _recent_data_rows(data_root: Path, cutoff: datetime) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    if not data_root.exists():
        return out
    for path in data_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        for row in _rows_from_json_file(path):
            ts = _row_time(row)
            if ts is not None and ts >= cutoff:
                out.append((path, row))
    return out


def _capture_count(data_rows: list[tuple[Path, dict[str, Any]]], lane_key: str | None) -> str:
    if lane_key is None:
        return "NO DATA"
    matching = [(p, r) for p, r in data_rows if lane_key in str(p)]
    if not matching:
        return "NO DATA"
    if lane_key == "archive-status":
        captured = sum(str(r.get("status") or "").upper() == "CAPTURED" for _, r in matching)
        return f"{captured} durable CAPTURED records"
    if lane_key == "nfl-forward":
        decisions = sum(p.name == "decisions.jsonl" for p, _ in matching)
        closes = sum(p.name == "closes.jsonl" for p, _ in matching)
        return f"{decisions} decision rows / {closes} close rows"
    return "NO DATA"


def _blocked_rows(data_rows: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    out, seen = [], set()
    for path, row in data_rows:
        statuses = {str(row.get(k) or "").upper() for k in ("status","bet_status","engine_status","truth_gate_status")}
        if "BLOCKED" not in statuses and not any(x.startswith("BLOCKED_") for x in statuses):
            continue
        reason = str(row.get("reason") or row.get("blocked_reason") or row.get("error") or "STRUCTURED REASON NO DATA")
        market = str(row.get("market") or row.get("market_id") or "UNKNOWN_MARKET")
        game = str(row.get("game") or row.get("game_id") or row.get("event_id") or "UNKNOWN_EVENT")
        item = f"{market} | {game} | {reason} | {path}"
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:100]


def _nfl_windows(now: datetime) -> tuple[list[str], str | None]:
    url = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    try:
        with urlopen(Request(url, headers={"User-Agent":"SportsEdge-daily-digest/1"}), timeout=20) as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
    except Exception as exc:
        return [], f"NFL schedule unavailable: {type(exc).__name__}"
    from zoneinfo import ZoneInfo
    out = []
    for row in rows:
        if str(row.get("game_type") or "").upper() != "REG":
            continue
        day, clock = str(row.get("gameday") or "").strip(), str(row.get("gametime") or "").strip()
        if not day or not clock:
            continue
        try:
            local = datetime.combine(datetime.fromisoformat(day[:10]).date(), datetime.strptime(clock, "%H:%M").time(), tzinfo=ZoneInfo("America/New_York"))
            start = local.astimezone(UTC)
        except Exception:
            continue
        if not (now < start <= now + timedelta(hours=26)):
            continue
        gid = str(row.get("game_id") or "UNKNOWN_GAME")
        for label, before in (("decision-start",120),("decision-end",45),("close-start",20),("close-end",2)):
            point = start - timedelta(minutes=before)
            if now <= point <= now + timedelta(hours=24):
                out.append(f"NFL {gid} {label} {point.isoformat()}")
    return sorted(out), None


def _mlb_windows(now: datetime) -> tuple[list[str], str | None]:
    params = urlencode({"sportId":1,"startDate":now.date().isoformat(),"endDate":(now+timedelta(days=1)).date().isoformat()})
    try:
        with urlopen(Request(f"https://statsapi.mlb.com/api/v1/schedule?{params}", headers={"User-Agent":"SportsEdge-daily-digest/1"}), timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [], f"MLB schedule unavailable: {type(exc).__name__}"
    out = []
    for date_row in payload.get("dates") or []:
        for game in date_row.get("games") or []:
            start = _dt(game.get("gameDate"))
            if start is None:
                continue
            gid = str(game.get("gamePk") or "UNKNOWN_GAME")
            for before in (180,90,0):
                point = start - timedelta(minutes=before)
                if now <= point <= now + timedelta(hours=24):
                    out.append(f"MLB {gid} T-{before} capture {point.isoformat()}")
    return sorted(out), None


def _odds_usage(data_rows: list[tuple[Path, dict[str, Any]]]) -> tuple[str, list[str]]:
    relevant = [(p, r) for p, r in data_rows if "archive-status" in str(p)]
    if not relevant:
        return "NO DATA", []

    credits = 0
    latest_used: tuple[datetime, Any] | None = None
    latest_provider: tuple[datetime, dict[str, Any]] | None = None
    last_success: datetime | None = None
    needs: list[str] = []

    for _, row in relevant:
        try:
            consumed = row.get("credits_consumed_actual")
            if consumed is not None:
                credits += int(consumed)
        except Exception:
            pass

        ts = _row_time(row)
        used = row.get("provider_credits_used")
        if ts is not None and used is not None and (latest_used is None or ts > latest_used[0]):
            latest_used = (ts, used)

        provider_state = str(row.get("provider_state") or "").strip().upper()
        provider_code = str(row.get("provider_error_code") or "").strip().upper()
        provider_relevant = bool(provider_state or provider_code)
        if ts is not None and provider_relevant and (latest_provider is None or ts > latest_provider[0]):
            latest_provider = (ts, row)
        if ts is not None and provider_state == "AVAILABLE" and (last_success is None or ts > last_success):
            last_success = ts

        if _NEEDS_ISAAC_RE.search(json.dumps(row, sort_keys=True)):
            needs.append(str(row.get("reason") or row.get("status") or "Odds API credential/quota issue"))

    counter = f"provider cumulative used={latest_used[1]}" if latest_used else "provider cumulative counter NO DATA"
    if latest_provider is not None:
        _, latest = latest_provider
        state = str(latest.get("provider_state") or "").strip().upper()
        code = str(latest.get("provider_error_code") or "").strip().upper()
        if state == "ACCOUNT_TERMINAL" or code == "OUT_OF_USAGE_CREDITS":
            success_text = last_success.isoformat() if last_success is not None else "NO DATA"
            reason = str(latest.get("reason") or "ACCOUNT_LEVEL_USAGE_CREDITS_EXHAUSTED")
            needs.append(reason)
            return (
                "HARD OUTAGE — Odds API account terminal: "
                f"{code or state}; last provider success={success_text}; "
                f"observed durable archive credits last 24h={credits}; {counter}. "
                "Zero observed consumption does not imply provider availability.",
                list(dict.fromkeys(needs)),
            )

    return (
        f"observed durable archive credits last 24h={credits}; {counter}; projected total provider requests NO DATA",
        list(dict.fromkeys(needs)),
    )


def build_digest(*, repo_root: Path, data_root: Path, token: str, repo: str, now: datetime) -> str:
    cutoff = now - timedelta(hours=24)
    runs = _recent_runs(token=token, repo=repo, cutoff=cutoff)
    data_rows = _recent_data_rows(data_root, cutoff)
    lines = ["# SportsEdge Daily Digest","",f"Generated: {now.isoformat()}",f"Window: {cutoff.isoformat()} → {now.isoformat()}","","## Capture / execution lanes"]
    for sport, label, workflow, lane_key in LANES:
        wf_name = workflow.removesuffix(".yml")
        lane_runs = [r for r in runs if r.get("name") == wf_name and r.get("event") == "schedule"]
        expected = _expected_runs(repo_root/".github"/"workflows"/workflow, cutoff, now)
        passed = sum(r.get("conclusion") == "success" for r in lane_runs)
        failed = sum(r.get("conclusion") == "failure" for r in lane_runs)
        skipped = sum(r.get("conclusion") == "skipped" for r in lane_runs)
        ran = len(lane_runs)
        execution = f"expected={'NO DATA' if expected is None else expected}, scheduled-runs-seen={ran}, passed={passed}, failed={failed}, skipped={skipped}"
        if expected is not None and ran == 0:
            execution += " — NEVER RAN IN WINDOW"
        lines.append(f"- **{sport} — {label}:** {execution}; durable capture evidence: {_capture_count(data_rows,lane_key)}")

    lines += ["","## Workflow failures — last 24h"]
    failures = [r for r in runs if r.get("conclusion") == "failure"]
    failure_details = _failure_details(failures, token=token, repo=repo) if failures else {}
    if not failures:
        lines.append("- None observed among runs returned by GitHub.")
    else:
        for run in sorted(failures, key=lambda x: x.get("created_at") or ""):
            lines.append(f"- {run.get('name')} run {run.get('id')} — {failure_details.get(int(run['id']),'ERROR STRING NO DATA')}")

    lines += ["","## BLOCKED markets"]
    blocked = _blocked_rows(data_rows)
    lines.extend([f"- {x}" for x in blocked] if blocked else ["- NO DATA — no timestamped structured BLOCKED market rows were found in the durable data branch for this window."])

    lines += ["","## Upcoming decision / capture windows — next 24h"]
    nfl,nfl_err = _nfl_windows(now); mlb,mlb_err = _mlb_windows(now); windows = sorted(nfl+mlb)
    lines.extend([f"- {x}" for x in windows] if windows else ["- NO DATA — no upcoming window records were resolved."])
    if nfl_err: lines.append(f"- {nfl_err}")
    if mlb_err: lines.append(f"- {mlb_err}")

    usage, usage_needs = _odds_usage(data_rows)
    lines += ["","## Odds API usage",f"- {usage}"]

    needs = []
    for run in failures:
        err = failure_details.get(int(run["id"]), "ERROR STRING NO DATA")
        if _NEEDS_ISAAC_RE.search(err):
            needs.append(f"{run.get('name')} run {run.get('id')}: {err}")
    needs.extend(usage_needs)
    needs = list(dict.fromkeys(needs))
    lines += ["","## NEEDS ISAAC"]
    lines.extend([f"- {x}" for x in needs] if needs else ["- NONE OBSERVED IN AVAILABLE DATA. Promotion remains human-gated and is never auto-approved by this digest."])

    lines += ["","## Interpretation rules","- NO DATA means evidence was unavailable; it does not mean zero.","- A workflow counts as passed only when GitHub reports a completed successful run.","- Durable capture evidence is separate from workflow success.","- This digest never promotes a market and never changes Truth Gate state.",""]
    return "\n".join(lines)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-root",type=Path,default=Path(".")); ap.add_argument("--data-root",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); ap.add_argument("--now"); a=ap.parse_args()
    token=os.environ.get("GITHUB_TOKEN","").strip(); repo=os.environ.get("GITHUB_REPOSITORY","").strip()
    if not token: raise SystemExit("DAILY_DIGEST_GITHUB_TOKEN_REQUIRED")
    if not repo: raise SystemExit("DAILY_DIGEST_GITHUB_REPOSITORY_REQUIRED")
    now=_dt(a.now) if a.now else datetime.now(UTC)
    if now is None: raise SystemExit("DAILY_DIGEST_NOW_INVALID")
    result=build_digest(repo_root=a.repo_root,data_root=a.data_root,token=token,repo=repo,now=now)
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(result,encoding="utf-8"); print(result); return 0

if __name__=="__main__": raise SystemExit(main())