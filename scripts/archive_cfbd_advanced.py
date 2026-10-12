"""Archive CFBD raw advanced stats (free tier) to the data branch.

ACTIONS-SIDE ONLY. Reads the key from the SPORTSEDGE_CFBD_API_KEY
environment variable (GitHub repo secret). Never logs or prints the key.

Modes:
  weekly    Scheduled steady-state pull. Pulls ONLY what is missing:
            the current season's season/advanced (1 call) plus the latest
            completed week that is not yet archived (2 calls: game/advanced
            + ppa/games). 1 extra call for GET /info tier discovery.
            Typical cost: ~4 calls/run.
  backfill  One-time historical fill (workflow_dispatch). Pulls
            --year-start..--year-end for /stats/season/advanced (1 call per
            season) and /stats/game/advanced + /ppa/games per week
            (2 calls per week). Completed seasons are immutable: seasons
            already archived are skipped (0 calls). Hard-capped by
            --max-calls; refuses to exceed the tier's remaining budget as
            reported by GET /info.

Call-budget math (documented, not hardcoded — /info is authoritative):
  Free tier = 1,000 calls/month, calendar-month reset, pool shared with
  CFBD's basketball product (we only call football). Weekly steady state
  costs ~4 calls/run -> ~16-20 calls/month. A full backfill of 2022-2025
  costs 4 (season/advanced) + 4 seasons x ~15 weeks x 2 = ~124 calls,
  one-time, never repeated for completed seasons.

Writes (under --out-dir, the data-branch worktree):
  archive/cfb-advanced/seasons/{year}/season_advanced.json
  archive/cfb-advanced/weeks/{year}/week_{NN}.json      (game/advanced + ppa merged)
  archive/cfb-advanced/manifest.json                    (schema + pull provenance)
  runtime/cfbd-budget/ledger.json                       (per-run call accounting)

Exit codes: 0 = ran (archived or nothing due), 2 = failed closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.cfbd_client import (  # noqa: E402
    CFBDClient,
    CFBDBudgetExhausted,
    CFBDError,
    CFBDKeyMissing,
    CFBDNotWired,
    CFBDTierGated,
)

UTC = timezone.utc
SCHEMA_VERSION = "CFBD_ARCHIVE_V1"
LEDGER_REL = "runtime/cfbd-budget/ledger.json"
MANIFEST_REL = "archive/cfb-advanced/manifest.json"


class ArchiveError(RuntimeError):
    """Fail-closed error. Never downgraded to a warning."""


# ---------------------------------------------------------------------------
# Budget ledger (durable on the data branch; restored each run)
# ---------------------------------------------------------------------------

def load_ledger(out_dir: Path) -> dict:
    path = out_dir / LEDGER_REL
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("runs", [])
    return payload


def save_ledger(out_dir: Path, ledger: dict) -> None:
    path = out_dir / LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def month_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def ledger_calls_this_month(ledger: dict, now: datetime) -> int:
    return sum(
        r.get("calls_made", 0) for r in ledger.get("runs", [])
        if str(r.get("month", "")) == month_key(now)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256_of(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def week_file(out_dir: Path, year: int, week: int) -> Path:
    return out_dir / "archive" / "cfb-advanced" / "weeks" / str(year) / (
        "week_%02d.json" % week)


def season_file(out_dir: Path, year: int) -> Path:
    return out_dir / "archive" / "cfb-advanced" / "seasons" / str(year) / (
        "season_advanced.json")


def already_archived(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(payload, dict)
            and payload.get("schema_version") == SCHEMA_VERSION
            and payload.get("status") == "ARCHIVED")


def check_budget(info: dict, planned_calls: int, ledger: dict,
                 now: datetime, max_calls: int) -> None:
    """Refuse before spending when the plan cannot fit the budget."""
    if planned_calls > max_calls:
        raise CFBDBudgetExhausted(
            "CFBD_BUDGET_PLAN_EXCEEDS_CAP:planned=%d max_calls=%d"
            % (planned_calls, max_calls)
        )
    remaining = info.get("remaining")
    try:
        remaining_n = int(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining_n = None
    if remaining_n is not None and planned_calls > remaining_n:
        raise CFBDBudgetExhausted(
            "CFBD_BUDGET_PLAN_EXCEEDS_REMAINING:planned=%d remaining=%d"
            % (planned_calls, remaining_n)
        )
    # Ledger is our own independent accounting (the tier pool is shared
    # with basketball; the ledger only tracks what THIS workflow spent).
    spent = ledger_calls_this_month(ledger, now)
    limit = info.get("limit", 1000)
    try:
        limit_n = int(limit)
    except (TypeError, ValueError):
        limit_n = 1000
    if spent + planned_calls > limit_n:
        raise CFBDBudgetExhausted(
            "CFBD_BUDGET_LEDGER_EXCEEDS_LIMIT:spent=%d planned=%d limit=%d"
            % (spent, planned_calls, limit_n)
        )


def archive_season(client: CFBDClient, out_dir: Path, year: int) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ARCHIVED",
        "endpoint": "/stats/season/advanced",
        "year": year,
        "exclude_garbage_time": True,
        "archived_at_utc": datetime.now(UTC).isoformat(),
        "rows": client.season_advanced(year),
    }
    payload["row_count"] = len(payload["rows"])
    payload["sha256"] = sha256_of(payload["rows"])
    path = season_file(out_dir, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8")
    return {"year": year, "row_count": payload["row_count"]}


def archive_week(client: CFBDClient, out_dir: Path, year: int, week: int) -> dict:
    game_rows = client.game_advanced(year, week)
    ppa_rows = client.ppa_games(year, week)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ARCHIVED",
        "year": year,
        "week": week,
        "exclude_garbage_time": True,
        "archived_at_utc": datetime.now(UTC).isoformat(),
        "game_advanced": game_rows,
        "ppa_games": ppa_rows,
    }
    payload["game_row_count"] = len(game_rows)
    payload["ppa_row_count"] = len(ppa_rows)
    payload["sha256"] = sha256_of({"g": game_rows, "p": ppa_rows})
    path = week_file(out_dir, year, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8")
    return {"year": year, "week": week,
            "game_row_count": payload["game_row_count"],
            "ppa_row_count": payload["ppa_row_count"]}


def current_cfb_season(now: datetime) -> int:
    # The season label is the calendar year the season starts in.
    return now.year if now.month >= 7 else now.year - 1


def latest_completed_week(client: CFBDClient, year: int) -> int:
    """Find the latest week with archived-able data by probing backwards.

    Weeks are probed newest-first; each probe is one /stats/game/advanced
    call, so the probe itself is budget-counted. Cap the probe depth so a
    weird season cannot burn the month.
    """
    probe_depth = int(os.environ.get("SPORTSEDGE_CFBD_PROBE_DEPTH", "20"))
    # Start from a generous upper bound and walk down.
    for week in range(16, 0, -1):
        if 16 - week >= probe_depth:
            break
        rows = client.game_advanced(year, week)
        if rows:
            return week
    return 0


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_weekly(client: CFBDClient, out_dir: Path, info: dict,
               ledger: dict, now: datetime, max_calls: int) -> dict:
    year = current_cfb_season(now)
    plan: list[tuple[str, int, int]] = []
    if not already_archived(season_file(out_dir, year)):
        plan.append(("season", year, 0))
    # Probe for the latest completed week (1 call per probe, capped).
    calls_before_probe = client.calls_made
    week = latest_completed_week(client, year)
    probe_calls = client.calls_made - calls_before_probe
    if week and not already_archived(week_file(out_dir, year, week)):
        plan.append(("week", year, week))
    planned_new = len([p for p in plan if p[0] == "season"]) + 2 * len(
        [p for p in plan if p[0] == "week"])
    check_budget(info, planned_new, ledger, now, max_calls)
    results = []
    for kind, y, w in plan:
        if kind == "season":
            results.append(archive_season(client, out_dir, y))
        else:
            results.append(archive_week(client, out_dir, y, w))
    return {"mode": "weekly", "year": year, "latest_completed_week": week,
            "probe_calls": probe_calls, "archived": results}


def run_backfill(client: CFBDClient, out_dir: Path, info: dict,
                 ledger: dict, now: datetime, max_calls: int,
                 year_start: int, year_end: int) -> dict:
    if year_start > year_end:
        raise ArchiveError("CFBD_BACKFILL_YEAR_RANGE_INVALID")
    # Weeks per season for budget planning (regular season + bowls/playoff).
    weeks_per_season = int(os.environ.get("SPORTSEDGE_CFBD_WEEKS", "16"))
    plan_calls = 0
    plan: list[tuple[str, int, int]] = []
    for year in range(year_start, year_end + 1):
        if not already_archived(season_file(out_dir, year)):
            plan.append(("season", year, 0))
            plan_calls += 1
        for week in range(1, weeks_per_season + 1):
            if not already_archived(week_file(out_dir, year, week)):
                plan.append(("week", year, week))
                plan_calls += 2
    check_budget(info, plan_calls, ledger, now, max_calls)
    results = []
    for kind, y, w in plan:
        if kind == "season":
            results.append(archive_season(client, out_dir, y))
        else:
            results.append(archive_week(client, out_dir, y, w))
    return {"mode": "backfill", "year_start": year_start,
            "year_end": year_end, "archived": results}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("weekly", "backfill"),
                        default="weekly")
    parser.add_argument("--out-dir", default=".",
                        help="data-branch worktree (archive root)")
    parser.add_argument("--max-calls", type=int, default=60,
                        help="hard cap on API calls for this run")
    parser.add_argument("--year-start", type=int, default=2022)
    parser.add_argument("--year-end", type=int, default=2025)
    parser.add_argument("--status-out", default=None,
                        help="write the run result JSON here (artifacts)")
    parser.add_argument("--self-test", action="store_true",
                        help="no network: verify ledger math + key handling")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    out_dir = Path(args.out_dir)
    now = datetime.now(UTC)
    try:
        client = CFBDClient.from_env()
    except CFBDKeyMissing as exc:
        print("failed closed: %s" % exc, file=sys.stderr)
        return 2

    ledger = load_ledger(out_dir)
    try:
        info = client.get_info()          # 1 call; authoritative budget
        if args.mode == "weekly":
            result = run_weekly(client, out_dir, info, ledger, now,
                                args.max_calls)
        else:
            result = run_backfill(client, out_dir, info, ledger, now,
                                  args.max_calls, args.year_start,
                                  args.year_end)
        # Provenance manifest (never overwritten destructively: merge keys).
        manifest_path = out_dir / MANIFEST_REL
        manifest: dict = {}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        manifest.update({
            "schema_version": SCHEMA_VERSION,
            "tier": info.get("tier"),
            "limit": info.get("limit"),
            "last_run_at_utc": now.isoformat(),
            "last_mode": args.mode,
            "exclude_garbage_time": True,
            "paid_tier_gated_never_requested": sorted(
                ["/ratings/sp"]),
        })
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        run_row = {
            "run_at_utc": now.isoformat(),
            "month": month_key(now),
            "mode": args.mode,
            "calls_made": client.calls_made,
            "tier_reported_remaining": info.get("remaining"),
            "status": "ARCHIVED",
            "result": result,
        }
        ledger["runs"].append(run_row)
        ledger["runs"] = ledger["runs"][-200:]
        ledger["last_status"] = "ARCHIVED"
        ledger["last_run_at_utc"] = now.isoformat()
        save_ledger(out_dir, ledger)
        status_doc = {"status": "ARCHIVED",
                      "calls_made": client.calls_made,
                      "result": result}
        print(json.dumps(status_doc, indent=2, sort_keys=True))
        if args.status_out:
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(status_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        return 0
    except (CFBDBudgetExhausted, CFBDTierGated, CFBDNotWired, CFBDError,
            ArchiveError) as exc:
        run_row = {
            "run_at_utc": now.isoformat(),
            "month": month_key(now),
            "mode": args.mode,
            "calls_made": client.calls_made,
            "status": "FAILED_CLOSED",
            "reason": str(exc),
        }
        ledger["runs"].append(run_row)
        ledger["runs"] = ledger["runs"][-200:]
        ledger["last_status"] = "FAILED_CLOSED"
        ledger["last_run_at_utc"] = now.isoformat()
        save_ledger(out_dir, ledger)
        if args.status_out:
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(run_row, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        print("failed closed: %s" % exc, file=sys.stderr)
        return 2


def self_test() -> int:
    """No network. Verifies budget math + fail-closed key handling."""
    # 1. Missing key fails closed.
    try:
        CFBDClient.from_env(env={})
    except CFBDKeyMissing:
        pass
    else:
        print("SELF_TEST_FAIL: missing key did not fail closed",
              file=sys.stderr)
        return 2
    # 2. Paid-tier endpoint never fires.
    client = CFBDClient(api_key="fake-key-for-tests-only")
    try:
        client.sp_ratings(2025)
    except CFBDNotWired:
        pass
    else:
        print("SELF_TEST_FAIL: SP+ did not raise CFBDNotWired",
              file=sys.stderr)
        return 2
    # 3. Budget math: weekly plan must fit far under 1,000.
    now = datetime(2026, 10, 11, tzinfo=UTC)
    ledger = {"runs": [{"month": "2026-10", "calls_made": 40}]}
    weekly_plan_calls = 4  # /info + season/advanced + game/advanced + ppa/games
    try:
        check_budget({"limit": 1000, "remaining": 900}, weekly_plan_calls,
                     ledger, now, max_calls=60)
    except CFBDBudgetExhausted as exc:
        print("SELF_TEST_FAIL: sane weekly plan rejected: %s" % exc,
              file=sys.stderr)
        return 2
    # 4. A plan that exceeds remaining budget fails closed.
    try:
        check_budget({"limit": 1000, "remaining": 3}, 10, ledger, now,
                     max_calls=60)
    except CFBDBudgetExhausted:
        pass
    else:
        print("SELF_TEST_FAIL: over-budget plan not rejected",
              file=sys.stderr)
        return 2
    print("self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
