#!/usr/bin/env python3
"""Fail-closed NFL confirmation capture from the public DraftKings board only.

No Odds API. Both sides of each market must come from one HTTP pull.
A 403, empty board, parse error, or missing side writes a _missed marker.
Does not edit frozen source-bound modules.
NOT Model_P / NOT Truth Gate / NOT OFFICIAL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.draftkings_game_market_source import (  # noqa: E402
    board_url,
    normalize_board,
    RawDraftKingsBoard,
)

SPORT = "americanfootball_nfl"
CFG_PATH = ROOT / "config/nfl_2026_capture.json"
AUTHORITY = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"


class Blocked(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_cfg() -> dict[str, Any]:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def week_of(dt_utc: datetime, cfg: dict[str, Any]) -> int:
    local = dt_utc.astimezone(ZoneInfo(cfg["timezone"])).date()
    anchor = datetime.fromisoformat(cfg["week1_tuesday_local_date"]).date()
    return (local - anchor).days // 7 + 1


def fetch_once() -> tuple[RawDraftKingsBoard, str | None]:
    uri = board_url(SPORT)
    req = Request(
        uri,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 SportsEdge-DK-Market-Archive/1",
            "Referer": "https://sportsbook.draftkings.com/",
            "Origin": "https://sportsbook.draftkings.com",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
            date_header = resp.headers.get("Date")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        raise Blocked("HTTP_ERROR", f"status={exc.code}; reason={exc.reason}; url={exc.url}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise Blocked("FETCH_FAILED", type(exc).__name__) from exc
    if status == 403:
        raise Blocked("HTTP_403", "DraftKings blocked the runner")
    if not raw:
        raise Blocked("EMPTY_BOARD", "zero-byte response")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Blocked("RESPONSE_NOT_JSON", str(exc)) from exc
    if not isinstance(payload, dict):
        raise Blocked("RESPONSE_SHAPE_INVALID", type(payload).__name__)
    for key in ("events", "markets", "selections"):
        if not isinstance(payload.get(key), list):
            raise Blocked("DK_SCHEMA_MISSING", key)
    now = utc_now()
    board = RawDraftKingsBoard(SPORT, uri, raw, now, payload)
    return board, date_header


def pair_markets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        point = row.get("point")
        if point is None:
            line_key = None
        elif row["market"] == "totals":
            line_key = float(point)
        else:
            line_key = abs(float(point))
        key = (row["provider_event_id"], row["market"], line_key)
        groups.setdefault(key, []).append(row)
    paired: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for key, items in groups.items():
        outcomes = {i["outcome"]: i for i in items}
        if len(outcomes) != 2:
            blocked.append({"key": list(key), "reason": "MISSING_SIDE", "n": len(outcomes)})
            continue
        a, b = list(outcomes.values())
        paired.append(
            {
                "provider_event_id": a["provider_event_id"],
                "home_team": a["home_team"],
                "away_team": a["away_team"],
                "commence_time": a["commence_time"],
                "market": a["market"],
                "point": a.get("point"),
                "sides": [
                    {"outcome": a["outcome"], "price_american": a["price_american"], "point": a.get("point")},
                    {"outcome": b["outcome"], "price_american": b["price_american"], "point": b.get("point")},
                ],
                "sportsbook": "draftkings",
                "provider": "DRAFTKINGS_DIRECT_WEB",
            }
        )
    if not paired and blocked:
        raise Blocked("BLOCKED_MISSING_SIDE", json.dumps(blocked[:8], separators=(",", ":")))
    if not paired:
        raise Blocked("NO_PAIRED_MARKETS", "normalize_board returned no two-sided rows")
    return paired


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def write_json(path: Path, obj: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def persist_raw(out_dir: Path, raw: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    rel = Path("raw/draftkings-direct") / f"{digest}.json"
    atomic_write(out_dir / rel, raw)
    return rel.as_posix(), digest


def classify_windows(cfg: dict[str, Any], now: datetime, commence: datetime) -> list[str]:
    kinds: list[str] = []
    tz = ZoneInfo(cfg["timezone"])
    local = now.astimezone(tz)
    hh, mm = map(int, cfg["opener_local_time"].split(":"))
    opener = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if (
        local.strftime("%A") == cfg["opener_weekday"]
        and opener <= local < opener + timedelta(minutes=int(cfg["opener_window_minutes"]))
    ):
        kinds.append("OPENER")
    start = commence - timedelta(minutes=int(cfg["final_minutes_before_kickoff"]))
    end = start + timedelta(minutes=int(cfg["final_window_minutes"]))
    if start <= now < min(end, commence):
        kinds.append("FINAL")
    return kinds


def missed_path(out_dir: Path, week: int, kind: str, stamp: str, game_id: str = "") -> Path:
    safe = game_id.replace("/", "_") or stamp
    if kind == "OPENER":
        return out_dir / f"week{week:02d}" / "opener" / f"{safe}_missed.json"
    return out_dir / f"week{week:02d}" / "final" / f"{stamp}_{safe}_missed.json"


def success_path(out_dir: Path, week: int, kind: str, stamp: str, game_id: str = "") -> Path:
    safe = game_id.replace("/", "_") or stamp
    if kind == "OPENER":
        return out_dir / f"week{week:02d}" / "opener" / f"{safe}.json"
    return out_dir / f"week{week:02d}" / "final" / f"{stamp}_{safe}.json"


def write_missed(path: Path, reason: str, detail: str, kind: str, week: int, now: datetime) -> None:
    if path.exists():
        return
    write_json(
        path,
        {
            "authority_footer": AUTHORITY,
            "capture_kind": kind,
            "evidence_semantics": "ABSENCE_MARKER_ONLY_NOT_MARKET_DATA",
            "no_backfill": True,
            "observed_missing_at_utc": now.isoformat(),
            "reason": reason,
            "detail": detail,
            "status": "MISSED_OR_BLOCKED",
            "week": week,
            "source": "DRAFTKINGS_DIRECT_WEB_ONLY",
        },
    )


def run(*, force: bool, as_of: datetime | None = None) -> dict[str, Any]:
    cfg = load_cfg()
    now = as_of or utc_now()
    out_dir = ROOT / cfg["output_dir"]
    report: dict[str, Any] = {
        "authority_footer": AUTHORITY,
        "as_of_utc": iso_z(now),
        "promotion_authority": False,
        "model_p_created": False,
    }
    try:
        board, date_header = fetch_once()
    except Blocked as exc:
        report.update(status="FETCH_BLOCKED", reason=exc.reason, detail=exc.detail)
        return report

    raw_rel, raw_sha = persist_raw(out_dir, board.raw)
    try:
        paired = pair_markets(normalize_board(board))
    except Blocked as exc:
        week = week_of(now, cfg)
        write_missed(missed_path(out_dir, week, "FINAL", iso_z(now)), exc.reason, exc.detail, "PARSE", week, now)
        report.update(status="MISSED_OR_BLOCKED", reason=exc.reason, detail=exc.detail, raw_sha256=raw_sha)
        return report

    buckets: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    skipped_window = 0
    for row in paired:
        commence = datetime.fromisoformat(row["commence_time"].replace("Z", "+00:00")).astimezone(timezone.utc)
        week = week_of(commence, cfg)
        if week < int(cfg["first_week"]):
            continue
        kinds = classify_windows(cfg, now, commence)
        if force and not kinds:
            skipped_window += 1
            continue
        if not kinds:
            skipped_window += 1
            continue
        stamp = commence.strftime("%Y%m%dT%H%MZ")
        for kind in kinds:
            buckets.setdefault((stamp, week, kind, str(row["provider_event_id"])), []).append(row)

    written = []
    for (stamp, week, kind, game_id), games in buckets.items():
        path = success_path(out_dir, week, kind, stamp, game_id)
        record = {
            "authority_footer": AUTHORITY,
            "book": "draftkings",
            "capture_kind": kind,
            "date_header": date_header,
            "games": games,
            "no_backfill": True,
            "promotion_authority": False,
            "provider": "DRAFTKINGS_DIRECT_WEB",
            "raw_relative_path": raw_rel,
            "raw_sha256": raw_sha,
            "received_at_utc": iso_z(board.received_at),
            "server_date_header": date_header,
            "source_class": "DRAFTKINGS_DIRECT_WEB_V1",
            "source_uri": board.source_uri,
            "week": week,
        }
        write_json(path, record)
        written.append(str(path.relative_to(ROOT)))

    if not written:
        report.update(
            status="PROOF_OK" if force else "NO_WINDOW",
            skipped_outside_window=skipped_window,
            raw_sha256=raw_sha,
            paired=len(paired),
        )
        return report
    report.update(status="CAPTURED", files=written, raw_sha256=raw_sha, paired=len(paired), date_header=date_header)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="proof parsing/pairing outside frozen windows without writing governed evidence")
    parser.add_argument("--status-out", default="")
    args = parser.parse_args(argv)
    report = run(force=args.force)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.status_out:
        Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.status_out).write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("status") in {"CAPTURED", "NO_WINDOW", "PROOF_OK"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
