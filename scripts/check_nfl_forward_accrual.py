#!/usr/bin/env python3
"""Fail closed when a due NFL forward window lacks contract-valid durable state.

This checker deliberately ignores GitHub Actions conclusions.  GREEN is a runner
state; only a contract-valid row under the declared data-branch persistence root
can satisfy an evidence window.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MARKETS = {"moneyline", "spread", "total"}
QUALIFYING_GATES = {"SHADOW_QUALIFIED", "OFFICIAL"}
ALLOWED_GATES = QUALIFYING_GATES | {"REJECTED_NO_POSITIVE_EV"}
SELECTION_CONTRACT = "NFL_FORWARD_SHADOW_EV_V1"


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


def _now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    out = _dt(value)
    if out is None:
        raise SystemExit("NFL_FORWARD_LIVENESS_NOW_INVALID")
    return out


def _kickoff(row: Mapping[str, str]) -> datetime | None:
    explicit = str(row.get("game_start_ts") or row.get("start_time") or "").strip()
    if explicit:
        return _dt(explicit)
    day = str(row.get("gameday") or row.get("game_date") or "").strip()
    clock = str(row.get("gametime") or "").strip()
    if not day or not clock:
        return None
    try:
        return datetime.fromisoformat(f"{day[:10]}T{clock}").replace(tzinfo=EASTERN).astimezone(UTC)
    except ValueError:
        return None


def _schedule_games(path: Path) -> list[tuple[str, datetime]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise SystemExit("NFL_FORWARD_LIVENESS_SCHEDULE_UNREADABLE") from exc
    out: list[tuple[str, datetime]] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("season") or "").strip() != "2026":
            continue
        game_type = str(row.get("game_type") or "").strip().upper()
        if game_type and game_type != "REG":
            continue
        game_id = str(row.get("game_id") or "").strip()
        kickoff = _kickoff(row)
        if not game_id or kickoff is None:
            continue
        if game_id in seen:
            raise SystemExit(f"NFL_FORWARD_LIVENESS_DUPLICATE_SCHEDULE_GAME:{game_id}")
        seen.add(game_id)
        out.append((game_id, kickoff))
    return out


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _jsonl(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists():
        return [], True
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], False
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return [], False
        if not isinstance(row, dict):
            return [], False
        rows.append(row)
    return rows, True


def _same_time(value: Any, expected: datetime) -> bool:
    actual = _dt(value)
    return actual is not None and actual == expected


def _same_line(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _release_state(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    releases: list[dict[str, Any]] = []
    failures: list[str] = []
    if not root.is_dir():
        return releases, failures
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        sha = directory.name.lower()
        if not GIT_SHA_RE.fullmatch(sha):
            continue
        release = _json(directory / "release.json")
        if not isinstance(release, dict):
            failures.append(f"NFL_FORWARD_RELEASE_INVALID:{sha}")
            continue
        artifact = str(release.get("model_artifact_sha256") or "").strip().lower()
        if (
            release.get("schema_version") != 1
            or str(release.get("model_code_git_sha") or "").strip().lower() != sha
            or not SHA256_RE.fullmatch(artifact)
        ):
            failures.append(f"NFL_FORWARD_RELEASE_BINDING_INVALID:{sha}")
            continue
        decisions, decisions_ok = _jsonl(directory / "decisions.jsonl")
        closes, closes_ok = _jsonl(directory / "closes.jsonl")
        if not decisions_ok:
            failures.append(f"NFL_FORWARD_DECISIONS_JSONL_INVALID:{sha}")
            continue
        if not closes_ok:
            failures.append(f"NFL_FORWARD_CLOSES_JSONL_INVALID:{sha}")
            continue
        releases.append({
            "sha": sha,
            "artifact": artifact,
            "decisions": decisions,
            "closes": closes,
        })
    return releases, failures


def _valid_decision(row: Mapping[str, Any], *, game_id: str, kickoff: datetime,
                    release_sha: str, artifact_sha: str) -> bool:
    decision = _dt(row.get("decision_ts"))
    if decision is None or not (kickoff - timedelta(minutes=120) <= decision <= kickoff - timedelta(minutes=45)):
        return False
    source_sha = str(row.get("live_feature_source_manifest_sha256") or "").strip().lower()
    provider_sha = str(row.get("provider_event_snapshot_sha256") or "").strip().lower()
    return (
        str(row.get("game_id") or "").strip() == game_id
        and _same_time(row.get("game_start_ts"), kickoff)
        and str(row.get("sport") or "").lower() == "nfl"
        and str(row.get("book") or "").lower() == "draftkings"
        and str(row.get("market") or "").lower() in MARKETS
        and bool(str(row.get("side") or "").strip())
        and bool(str(row.get("provider_event_id") or "").strip())
        and str(row.get("selection_contract") or "") == SELECTION_CONTRACT
        and str(row.get("gate_result") or "") in ALLOWED_GATES
        and str(row.get("code_git_sha") or "").strip().lower() == release_sha
        and str(row.get("model_artifact_sha256") or "").strip().lower() == artifact_sha
        and SHA256_RE.fullmatch(source_sha) is not None
        and SHA256_RE.fullmatch(provider_sha) is not None
    )


def _complete_decision_set(release: Mapping[str, Any], game_id: str,
                           kickoff: datetime) -> list[dict[str, Any]] | None:
    candidates = [
        row for row in release["decisions"]
        if str(row.get("game_id") or "").strip() == game_id
    ]
    valid = [
        row for row in candidates
        if _valid_decision(
            row,
            game_id=game_id,
            kickoff=kickoff,
            release_sha=str(release["sha"]),
            artifact_sha=str(release["artifact"]),
        )
    ]
    markets = [str(row.get("market") or "").lower() for row in valid]
    if len(valid) != 3 or set(markets) != MARKETS or len(markets) != len(set(markets)):
        return None
    return valid


def _close_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("game_id") or "").strip(),
        str(row.get("market") or "").strip().lower(),
        str(row.get("side") or "").strip(),
        str(row.get("book") or "").strip().lower(),
    )


def _valid_close(close: Mapping[str, Any], decision: Mapping[str, Any], *,
                 kickoff: datetime, release_sha: str, artifact_sha: str) -> bool:
    close_ts = _dt(close.get("close_ts"))
    decision_ts = _dt(decision.get("decision_ts"))
    provider_sha = str(close.get("provider_event_snapshot_sha256") or "").strip().lower()
    source_sha = str(close.get("live_feature_source_manifest_sha256") or "").strip().lower()
    if close_ts is None or decision_ts is None:
        return False
    if not (kickoff - timedelta(minutes=20) <= close_ts <= kickoff - timedelta(minutes=2)):
        return False
    return (
        close_ts > decision_ts
        and _close_key(close) == _close_key(decision)
        and _same_time(close.get("game_start_ts"), kickoff)
        and str(close.get("sport") or "").lower() == "nfl"
        and str(close.get("book") or "").lower() == "draftkings"
        and str(close.get("provider_event_id") or "").strip() == str(decision.get("provider_event_id") or "").strip()
        and str(close.get("code_git_sha") or "").strip().lower() == release_sha
        and str(close.get("model_artifact_sha256") or "").strip().lower() == artifact_sha
        and SHA256_RE.fullmatch(provider_sha) is not None
        and SHA256_RE.fullmatch(source_sha) is not None
        and _same_line(close.get("probability_line"), decision.get("line_at_decision"))
    )


def forward_liveness(state_root: Path, schedule_csv: Path, now: datetime,
                     lookback_hours: float) -> dict[str, Any]:
    games = _schedule_games(schedule_csv)
    releases, failures = _release_state(state_root)
    lookback = timedelta(hours=float(lookback_hours))
    decision_expected = decision_accrued = 0
    close_expected = close_accrued = 0

    for game_id, kickoff in games:
        decision_end = kickoff - timedelta(minutes=45)
        decision_elapsed = now - decision_end
        decision_due = timedelta(0) <= decision_elapsed <= lookback

        completed: tuple[Mapping[str, Any], list[dict[str, Any]]] | None = None
        for release in releases:
            rows = _complete_decision_set(release, game_id, kickoff)
            if rows is not None:
                completed = (release, rows)
                break

        if decision_due:
            decision_expected += 1
            if completed is None:
                failures.append(f"NFL_FORWARD_ZERO_VALID_DECISIONS:game={game_id}")
            else:
                decision_accrued += 1

        close_end = kickoff - timedelta(minutes=2)
        close_elapsed = now - close_end
        close_due = timedelta(0) <= close_elapsed <= lookback
        if not close_due or completed is None:
            continue

        release, decisions = completed
        qualifying = [row for row in decisions if str(row.get("gate_result") or "") in QUALIFYING_GATES]
        if not qualifying:
            continue
        close_expected += len(qualifying)
        closes = list(release["closes"])
        for decision in qualifying:
            matches = [
                row for row in closes
                if _close_key(row) == _close_key(decision)
                and _valid_close(
                    row,
                    decision,
                    kickoff=kickoff,
                    release_sha=str(release["sha"]),
                    artifact_sha=str(release["artifact"]),
                )
            ]
            if len(matches) == 1:
                close_accrued += 1
            else:
                failures.append(
                    "NFL_FORWARD_ZERO_OR_INVALID_CLOSE:"
                    f"game={game_id}:market={decision.get('market')}:side={decision.get('side')}:valid={len(matches)}"
                )

    expected = decision_expected + close_expected
    accrued = decision_accrued + close_accrued
    if failures:
        evidence_state = "NO_ACCRUAL"
    elif expected == 0:
        evidence_state = "NOT_EXPECTED"
    else:
        evidence_state = "ACCRUED"
    return {
        "schema": "SPORTSEDGE_NFL_FORWARD_ACCRUAL_LIVENESS_V1",
        "status": "PASS" if not failures else "FAIL",
        "evidence_state": evidence_state,
        "decision_expected_games": decision_expected,
        "decision_accrued_games": decision_accrued,
        "close_expected_rows": close_expected,
        "close_accrued_rows": close_accrued,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--schedule-csv", type=Path, required=True)
    parser.add_argument("--now")
    parser.add_argument("--lookback-hours", type=float, default=4.0)
    args = parser.parse_args()
    report = forward_liveness(args.state_root, args.schedule_csv, _now(args.now), args.lookback_hours)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
