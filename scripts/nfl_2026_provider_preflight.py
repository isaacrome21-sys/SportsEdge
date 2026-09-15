#!/usr/bin/env python3
"""Prospective provider-budget preflight for frozen NFL 2026 capture windows.

This is control-plane metadata only.  It cannot create evidence, Model_P,
promotion, Truth Gate, staking, OFFICIAL, or backfill authority.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.odds_api_quota_guard import configured_keys, probe_quota, zero_authority

CAPTURE_CONFIG = Path("config/nfl_2026_capture.json")
BUDGET_CONFIG = Path("config/nfl_2026_provider_budget_v1.json")


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include timezone")
    return parsed.astimezone(timezone.utc)


def _week_for_local_date(local_day: date, capture: dict) -> int:
    anchor = date.fromisoformat(capture["week1_tuesday_local_date"])
    return (local_day - anchor).days // 7 + 1


def next_opener_target(now: datetime, capture: dict) -> tuple[datetime, int]:
    tz = ZoneInfo(capture["timezone"])
    local = now.astimezone(tz)
    weekday = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
        "Friday": 4, "Saturday": 5, "Sunday": 6,
    }[capture["opener_weekday"]]
    hh, mm = map(int, capture["opener_local_time"].split(":"))
    delta = (weekday - local.weekday()) % 7
    candidate_day = local.date() + timedelta(days=delta)
    candidate = datetime(candidate_day.year, candidate_day.month, candidate_day.day, hh, mm, tzinfo=tz)
    if candidate <= local:
        candidate += timedelta(days=7)
    week = _week_for_local_date(candidate.date(), capture)
    while week < int(capture["first_week"]):
        candidate += timedelta(days=7)
        week = _week_for_local_date(candidate.date(), capture)
    return candidate.astimezone(timezone.utc), week


def _final_targets(schedule_csv: Path, now: datetime, capture: dict) -> list[tuple[datetime, int, str]]:
    out: list[tuple[datetime, int, str]] = []
    eastern = ZoneInfo("America/New_York")
    local_tz = ZoneInfo(capture["timezone"])
    lead = timedelta(minutes=int(capture["final_minutes_before_kickoff"]))
    with schedule_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != "2026":
                continue
            gameday = str(row.get("gameday") or "").strip()
            gametime = str(row.get("gametime") or "").strip()
            if not gameday or not gametime:
                continue
            try:
                kickoff = datetime.fromisoformat(f"{gameday}T{gametime}").replace(tzinfo=eastern).astimezone(timezone.utc)
            except ValueError:
                continue
            week = _week_for_local_date(kickoff.astimezone(local_tz).date(), capture)
            if week < int(capture["first_week"]):
                continue
            target = kickoff - lead
            if target <= now:
                continue
            event_key = str(row.get("game_id") or row.get("away_team") or "NFL_GAME")
            out.append((target, week, event_key))
    return out


def next_confirmation_target(schedule_csv: Path, now: datetime, capture: dict) -> dict:
    opener_at, opener_week = next_opener_target(now, capture)
    candidates: list[tuple[datetime, str, int, str | None]] = [
        (opener_at, "OPENER", opener_week, None)
    ]
    candidates.extend((dt, "FINAL", week, event_key) for dt, week, event_key in _final_targets(schedule_csv, now, capture))
    target_at, kind, week, event_key = min(candidates, key=lambda x: x[0])
    return {
        "kind": kind,
        "week": week,
        "event_key": event_key,
        "target_at_utc": target_at,
        "minutes_until_target": (target_at - now).total_seconds() / 60.0,
    }


def evaluate(
    schedule_csv: Path,
    now: datetime,
    capture: dict,
    budget: dict,
    *,
    quota_probe=probe_quota,
) -> dict:
    target = next_confirmation_target(schedule_csv, now, capture)
    lead = int(budget["preflight_lead_minutes"])
    reserve = int(budget["lower_priority_paid_work"]["minimum_confirmation_reserve_credits"])
    immediate_cost = int(budget["confirmation"]["expected_request_cost_credits"])
    base = {
        "schema_version": "SPORTSEDGE_NFL_2026_PROVIDER_PREFLIGHT_V1",
        "checked_at_utc": now.isoformat(),
        "target_kind": target["kind"],
        "target_week": target["week"],
        "target_event_key": target["event_key"],
        "target_at_utc": target["target_at_utc"].isoformat(),
        "minutes_until_target": round(target["minutes_until_target"], 3),
        "preflight_lead_minutes": lead,
        "required_confirmation_reserve_credits": reserve,
        "immediate_capture_cost_credits": immediate_cost,
        "authority": zero_authority(),
    }
    if target["minutes_until_target"] > lead:
        return {
            **base,
            "state": "NO_UPCOMING_PROVIDER_WINDOW",
            "provider_probe_run": False,
            "immediate_capture_possible": None,
            "forward_paid_allowed": None,
        }

    quota = quota_probe(configured_keys(), minimum_remaining=reserve)
    remaining = quota.get("max_remaining")
    immediate_possible = isinstance(remaining, int) and remaining >= immediate_cost
    forward_cost = int(budget["lower_priority_paid_work"]["max_single_forward_request_cost_credits"])
    forward_allowed = isinstance(remaining, int) and remaining - forward_cost >= reserve
    return {
        **base,
        "state": "PROVIDER_READY_PREFLIGHT" if quota.get("state") == "READY" else "PROVIDER_BLOCKED_PREFLIGHT",
        "provider_probe_run": True,
        "provider_quota": quota,
        "immediate_capture_possible": immediate_possible,
        "forward_paid_allowed": forward_allowed,
    }


def _write_github_outputs(report: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    values = {
        "state": report["state"],
        "provider_probe_run": str(bool(report.get("provider_probe_run"))).lower(),
        "target_kind": report.get("target_kind") or "",
        "target_week": report.get("target_week") or "",
        "immediate_capture_possible": "" if report.get("immediate_capture_possible") is None else str(bool(report["immediate_capture_possible"])).lower(),
        "forward_paid_allowed": "" if report.get("forward_paid_allowed") is None else str(bool(report["forward_paid_allowed"])).lower(),
    }
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    capture = json.loads(CAPTURE_CONFIG.read_text(encoding="utf-8"))
    budget = json.loads(BUDGET_CONFIG.read_text(encoding="utf-8"))
    report = evaluate(args.schedule_csv, _parse_now(args.now), capture, budget)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    _write_github_outputs(report)
    return 2 if report["state"] == "PROVIDER_BLOCKED_PREFLIGHT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
