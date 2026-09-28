#!/usr/bin/env python3
"""Collect prospective MLB prop evidence receipts from the official MLB Stats API."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sportsedge.mlb_prop_forward_evidence import (
    MlbPropForwardEvidenceError,
    build_pregame_receipt,
    build_settlement_receipt,
    canonical_json_bytes,
    missed_receipt,
    source_url,
)

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
USER_AGENT = "SportsEdge-Prospective-Evidence/1.0"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mlb_date_now() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _fetch_json(url: str, timeout: int = 20) -> Mapping[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"SOURCE_FETCH_FAILED:{url}:{type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"SOURCE_PAYLOAD_NOT_OBJECT:{url}")
    return payload


def _schedule_game_pks(payload: Mapping[str, Any]) -> list[int]:
    dates = payload.get("dates")
    if not isinstance(dates, list):
        raise RuntimeError("SCHEDULE_MISSING_DATES")
    pks: list[int] = []
    for date_row in dates:
        games = date_row.get("games") if isinstance(date_row, Mapping) else None
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, Mapping):
                continue
            try:
                pks.append(int(game.get("gamePk")))
            except (TypeError, ValueError):
                continue
    return sorted(set(pks))


def _abstract_state(feed: Mapping[str, Any]) -> str:
    game_data = feed.get("gameData")
    status = game_data.get("status") if isinstance(game_data, Mapping) else None
    return str(status.get("abstractGameState") or "").strip().upper() if isinstance(status, Mapping) else ""


def _write_create_only(path: Path, payload: Mapping[str, Any]) -> str:
    data = canonical_json_bytes(payload) + b"\n"
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"CREATE_ONLY_COLLISION:{path}")
        return "EXISTS_IDENTICAL"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "CREATED"


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"EXISTING_RECEIPT_NOT_OBJECT:{path}")
    return payload


def run(*, mlb_date: str, output_root: Path, now_utc: str | None = None) -> dict[str, Any]:
    observed_at = now_utc or _now_utc()
    day_root = output_root / mlb_date
    schedule_url = SCHEDULE_URL + "?" + urlencode({"sportId": 1, "date": mlb_date})
    schedule = _fetch_json(schedule_url)
    game_pks = _schedule_game_pks(schedule)
    summary: dict[str, Any] = {
        "status": "OK",
        "authority": "EVIDENCE_ONLY_NOT_MODEL_P_NOT_TRUTH_GATE_NOT_OFFICIAL",
        "mlb_date": mlb_date,
        "observed_at_utc": observed_at,
        "schedule_url": schedule_url,
        "games": len(game_pks),
        "captured": 0,
        "settled": 0,
        "missed_or_blocked": 0,
        "existing": 0,
        "source_failures": [],
    }

    for game_pk in game_pks:
        pregame_path = day_root / "pregame" / f"{game_pk}.json"
        settlement_path = day_root / "settlement" / f"{game_pk}.json"
        missed_path = day_root / "missed" / f"{game_pk}.json"
        if settlement_path.exists():
            summary["existing"] += 1
            continue
        try:
            feed = _fetch_json(source_url(game_pk))
        except RuntimeError as exc:
            summary["source_failures"].append({"game_pk": game_pk, "error": str(exc)})
            continue

        state = _abstract_state(feed)
        if state == "PREVIEW":
            if pregame_path.exists():
                summary["existing"] += 1
                continue
            try:
                receipt = build_pregame_receipt(feed=feed, captured_at_utc=observed_at)
            except MlbPropForwardEvidenceError:
                if not missed_path.exists():
                    blocked = missed_receipt(
                        feed=feed,
                        observed_at_utc=observed_at,
                        reason="PREGAME_STATE_BUT_CAPTURE_WINDOW_NOT_PROVABLE",
                    )
                    _write_create_only(missed_path, blocked)
                    summary["missed_or_blocked"] += 1
                else:
                    summary["existing"] += 1
                continue
            _write_create_only(pregame_path, receipt)
            summary["captured"] += 1
            continue

        if state == "FINAL":
            if not pregame_path.exists():
                if not missed_path.exists():
                    blocked = missed_receipt(
                        feed=feed,
                        observed_at_utc=observed_at,
                        reason="NO_PREGAME_CAPTURE_BEFORE_FINAL",
                    )
                    _write_create_only(missed_path, blocked)
                    summary["missed_or_blocked"] += 1
                else:
                    summary["existing"] += 1
                continue
            pregame = _load_json(pregame_path)
            settlement = build_settlement_receipt(
                feed=feed,
                pregame_receipt=pregame,
                settled_at_utc=observed_at,
            )
            _write_create_only(settlement_path, settlement)
            summary["settled"] += 1
            continue

        if state == "LIVE" and not pregame_path.exists():
            if not missed_path.exists():
                blocked = missed_receipt(
                    feed=feed,
                    observed_at_utc=observed_at,
                    reason="NO_PREGAME_CAPTURE_BEFORE_LIVE_STATE",
                )
                _write_create_only(missed_path, blocked)
                summary["missed_or_blocked"] += 1
            else:
                summary["existing"] += 1

    if summary["source_failures"]:
        summary["status"] = "BLOCKED_SOURCE_FAILURE"
    elif summary["missed_or_blocked"]:
        summary["status"] = "MISSED_OR_BLOCKED"
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=_mlb_date_now())
    parser.add_argument("--output-root", default="data/mlb_prop_forward")
    args = parser.parse_args(argv)
    try:
        result = run(mlb_date=args.date, output_root=Path(args.output_root))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
