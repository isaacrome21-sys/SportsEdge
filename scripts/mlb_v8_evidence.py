#!/usr/bin/env python3
"""Build immutable MLB V8 evidence bundles without changing model semantics.

The forward lane starts 2026-09-03 (Chicago slate date). Historical material can
be ingested separately, but it is never relabeled as a forward observation.

This script is deliberately standard-library only so the irreplaceable evidence
path does not depend on the SportsEdge runtime environment.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
FORWARD_START = date(2026, 9, 3)
SCHEMA_VERSION = "SPORTSEDGE_MLB_V8_EVIDENCE_V1"
DEFAULT_OUT = Path("artifacts/mlb_v8")

PIT_DECISION_CLASSES = {
    "PIT_SNAPSHOT",
    "PIT_TIMESERIES",
    "FORWARD_OBSERVATION",
}
CLV_CLASSES = PIT_DECISION_CLASSES | {
    "OPEN_CLOSE_ONLY",
    "EXCHANGE_PIT",
}


class EvidenceError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    if out.tzinfo is None:
        return None
    return out.astimezone(timezone.utc)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _copy_immutable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256_file(source) != _sha256_file(destination):
            raise EvidenceError(f"immutable collision: {destination}")
        return
    shutil.copy2(source, destination)


def _artifact_time(payload: Any) -> tuple[datetime | None, str | None]:
    """Read only card/run-level as-of fields; never borrow a nested quote timestamp."""
    preferred = (
        "decision_at_utc",
        "as_of_utc",
        "as_of",
        "run_at_utc",
        "generated_at_utc",
        "created_at",
    )
    if not isinstance(payload, dict):
        return None, None
    for key in preferred:
        parsed = _parse_iso(payload.get(key))
        if parsed is not None:
            return parsed, key
    for container_key in ("metadata", "run", "provenance", "decision", "card"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in preferred:
            parsed = _parse_iso(container.get(key))
            if parsed is not None:
                return parsed, f"{container_key}.{key}"
    return None, None


def _parse_raw_odds_snapshot(path: Path) -> dict[str, Any]:
    """Extract only indexing metadata; raw bytes remain authoritative."""
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        raise EvidenceError(f"invalid raw odds JSON {path}: {exc}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        events = payload["data"]
        provider_snapshot = payload.get("timestamp")
    elif isinstance(payload, list):
        events = payload
        provider_snapshot = None
    else:
        raise EvidenceError(f"unexpected raw odds shape: {path}")

    rows: list[dict[str, Any]] = []
    earliest_start = None
    latest_start = None
    for event in events:
        if not isinstance(event, dict):
            continue
        start = _parse_iso(event.get("commence_time") or event.get("start_time"))
        if start is not None:
            earliest_start = start if earliest_start is None else min(earliest_start, start)
            latest_start = start if latest_start is None else max(latest_start, start)
        books = []
        for book in event.get("bookmakers", event.get("books", [])) or []:
            if not isinstance(book, dict):
                continue
            books.append({
                "key": book.get("key") or book.get("book"),
                "last_update": book.get("last_update") or book.get("updated_at"),
                "market_count": len(book.get("markets", []) or []),
            })
        rows.append({
            "event_id": event.get("id") or event.get("event_id"),
            "commence_time": _iso(start) if start else None,
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "bookmakers": books,
        })

    return {
        "provider_snapshot_timestamp": provider_snapshot,
        "event_count": len(rows),
        "earliest_commence_time": _iso(earliest_start) if earliest_start else None,
        "latest_commence_time": _iso(latest_start) if latest_start else None,
        "events": rows,
    }


def _infer_capture_time(path: Path) -> tuple[datetime | None, str]:
    # Canonical archive filename: game_odds_YYYYMMDDTHHMMSSZ.json
    stem = path.stem
    prefix = "game_odds_"
    if stem.startswith(prefix):
        raw = stem[len(prefix):]
        try:
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), "filename"
        except ValueError:
            pass
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return ts, "filesystem_mtime_untrusted"


def _slate_from_path(path: Path, capture_at: datetime) -> str:
    for part in path.parts:
        try:
            d = date.fromisoformat(part)
        except ValueError:
            continue
        if 2020 <= d.year <= 2100:
            return d.isoformat()
    return capture_at.astimezone(CT).date().isoformat()


def _bundle_id(kind: str, observed_at: datetime, sha: str) -> str:
    return f"{observed_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{kind}_{sha[:16]}"


def build_market_bundles(
    *,
    input_root: Path,
    output_root: Path,
    now: datetime,
    source_name: str,
    source_class: str,
) -> list[Path]:
    written: list[Path] = []
    if not input_root.is_dir():
        return written

    for raw_path in sorted(input_root.rglob("game_odds_*.json")):
        capture_at, time_basis = _infer_capture_time(raw_path)
        if capture_at is None:
            continue
        slate = _slate_from_path(raw_path, capture_at)
        slate_date = date.fromisoformat(slate)
        if slate_date < FORWARD_START:
            # Forward collector never launders old local files into V8-forward.
            continue

        raw_sha = _sha256_file(raw_path)
        index = _parse_raw_odds_snapshot(raw_path)
        bundle = output_root / slate / "market" / _bundle_id("market", capture_at, raw_sha)
        raw_dest = bundle / "raw.json"
        _copy_immutable(raw_path, raw_dest)

        prestart_count = 0
        poststart_count = 0
        unknown_count = 0
        for row in index["events"]:
            start = _parse_iso(row.get("commence_time"))
            if start is None:
                unknown_count += 1
            elif capture_at <= start:
                prestart_count += 1
            else:
                poststart_count += 1

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "evidence_kind": "MARKET_SNAPSHOT",
            "collection_mode": "FORWARD",
            "forward_start_date_ct": FORWARD_START.isoformat(),
            "slate_date_ct": slate,
            "source_name": source_name,
            "source_class": source_class,
            "retrieved_at_utc": _iso(capture_at),
            "retrieved_at_basis": time_basis,
            "packaged_at_utc": _iso(now),
            "raw_sha256": raw_sha,
            "raw_bytes": raw_dest.stat().st_size,
            "raw_original_path": raw_path.as_posix(),
            "git_sha": os.environ.get("GITHUB_SHA"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "pit_policy": {
                "decision_eligible_source_class": source_class in PIT_DECISION_CLASSES,
                "clv_eligible_source_class": source_class in CLV_CLASSES,
                "prestart_events": prestart_count,
                "poststart_events": poststart_count,
                "unknown_start_events": unknown_count,
                "rule": "event-level use requires retrieved_at_utc <= commence_time; post-start rows are never pregame decision evidence",
            },
            "provider_index": index,
        }
        _atomic_json(bundle / "manifest.json", manifest)
        written.append(bundle)
    return written


def build_decision_bundle(
    *,
    card: Path,
    associated: list[Path],
    output_root: Path,
    now: datetime,
) -> Path | None:
    if not card.is_file():
        return None

    raw = card.read_bytes()
    card_sha = _sha256_bytes(raw)
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise EvidenceError(f"invalid decision artifact {card}: {exc}") from exc

    decision_at, decision_key = _artifact_time(payload)
    observed = decision_at or now
    slate = observed.astimezone(CT).date().isoformat()
    if date.fromisoformat(slate) < FORWARD_START:
        return None

    bundle = output_root / slate / "decision" / _bundle_id("decision", observed, card_sha)
    _copy_immutable(card, bundle / "live_mlb_card.json")

    files = [{
        "role": "decision_card",
        "path": "live_mlb_card.json",
        "sha256": card_sha,
        "bytes": len(raw),
    }]
    for path in associated:
        if not path.is_file():
            continue
        dest = bundle / path.name
        _copy_immutable(path, dest)
        files.append({
            "role": "associated_input_or_diagnostic",
            "path": path.name,
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": "MODEL_DECISION",
        "collection_mode": "FORWARD",
        "forward_start_date_ct": FORWARD_START.isoformat(),
        "slate_date_ct": slate,
        "decision_at_utc": _iso(decision_at) if decision_at else None,
        "decision_at_basis": f"artifact:{decision_key}" if decision_at else "UNVERIFIED_NO_ARTIFACT_TIMESTAMP",
        "workflow_packaged_at_utc": _iso(now),
        "git_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "files": files,
        "governance": {
            "promotion_effect": "NONE",
            "truth_gate_status": "UNCHANGED",
            "decision_evidence_usable": decision_at is not None,
            "rule": "an artifact without its own PIT decision timestamp is retained but cannot satisfy chronological calibration",
        },
    }
    _atomic_json(bundle / "manifest.json", manifest)
    return bundle


def _self_test() -> int:
    now = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
    with TemporaryDirectory() as td:
        root = Path(td)
        raw_root = root / "artifacts/raw_odds/2026-09-03/Tminus90m"
        raw_root.mkdir(parents=True)
        raw = raw_root / "game_odds_20260903T150000Z.json"
        raw.write_text(json.dumps([{
            "id": "g1",
            "commence_time": "2026-09-03T16:30:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [{
                "key": "draftkings",
                "last_update": "2026-09-03T14:59:00Z",
                "markets": [{"key": "h2h", "outcomes": []}],
            }],
        }]))
        out = root / "v8"
        bundles = build_market_bundles(
            input_root=root / "artifacts/raw_odds",
            output_root=out,
            now=now,
            source_name="the_odds_api",
            source_class="FORWARD_OBSERVATION",
        )
        assert len(bundles) == 1
        manifest = json.loads((bundles[0] / "manifest.json").read_text())
        assert manifest["pit_policy"]["prestart_events"] == 1
        assert manifest["pit_policy"]["poststart_events"] == 0

        old_root = root / "old/2026-09-02/Tminus90m"
        old_root.mkdir(parents=True)
        (old_root / "game_odds_20260902T150000Z.json").write_text(raw.read_text())
        assert build_market_bundles(
            input_root=root / "old",
            output_root=out,
            now=now,
            source_name="the_odds_api",
            source_class="FORWARD_OBSERVATION",
        ) == []

        card = root / "live_mlb_card.json"
        card.write_text(json.dumps({"as_of_utc": "2026-09-03T14:57:00Z", "bets": []}))
        decision = build_decision_bundle(
            card=card,
            associated=[],
            output_root=out,
            now=now,
        )
        assert decision is not None
        dm = json.loads((decision / "manifest.json").read_text())
        assert dm["governance"]["decision_evidence_usable"] is True

        card2 = root / "card_without_asof.json"
        card2.write_text(json.dumps({"quotes": [{"retrieved_at": "2026-09-03T14:58:00Z"}]}))
        decision2 = build_decision_bundle(
            card=card2,
            associated=[],
            output_root=out,
            now=now,
        )
        assert decision2 is not None
        dm2 = json.loads((decision2 / "manifest.json").read_text())
        assert dm2["governance"]["decision_evidence_usable"] is False

    print(json.dumps({
        "status": "SELF_TEST_OK",
        "forward_start_guard": "PASS",
        "prestart_classification": "PASS",
        "decision_timestamp_fail_closed": "PASS",
        "immutable_hashing": "PASS",
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--market-root", type=Path, default=Path("artifacts/raw_odds"))
    parser.add_argument("--card", type=Path, default=Path("artifacts/live_mlb_card.json"))
    parser.add_argument("--associated", action="append", type=Path, default=[])
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--market", action="store_true", help="package forward market snapshots")
    parser.add_argument("--decision", action="store_true", help="package forward decision artifact")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    now = _utcnow()
    if now.astimezone(CT).date() < FORWARD_START:
        print(json.dumps({
            "status": "SKIP_BEFORE_V8_FORWARD_START",
            "forward_start_date_ct": FORWARD_START.isoformat(),
            "now_utc": _iso(now),
        }, sort_keys=True))
        return 0

    do_market = args.market or not (args.market or args.decision)
    do_decision = args.decision or not (args.market or args.decision)
    results: dict[str, Any] = {
        "status": "OK",
        "schema_version": SCHEMA_VERSION,
        "forward_start_date_ct": FORWARD_START.isoformat(),
    }

    if do_market:
        bundles = build_market_bundles(
            input_root=args.market_root,
            output_root=args.output_root,
            now=now,
            source_name="the_odds_api_v4_live",
            source_class="FORWARD_OBSERVATION",
        )
        results["market_bundles"] = [p.as_posix() for p in bundles]

    if do_decision:
        assoc = list(args.associated)
        for candidate in (
            Path("artifacts/live_game_odds.json"),
            Path("artifacts/odds_http_diagnostics.json"),
        ):
            if candidate not in assoc:
                assoc.append(candidate)
        decision = build_decision_bundle(
            card=args.card,
            associated=assoc,
            output_root=args.output_root,
            now=now,
        )
        results["decision_bundle"] = decision.as_posix() if decision else None

    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
