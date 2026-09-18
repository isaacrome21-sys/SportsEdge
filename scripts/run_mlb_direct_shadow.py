#!/usr/bin/env python3
"""Run MLB game markets from DraftKings' direct web board into the shadow ledger.

This is a keyless acquisition path for MONEYLINE/RUN_LINE/TOTALS. It preserves
SportsEdge's existing market-blind Model_P and deployment gates. MODEL_CANDIDATE
rows may be marked SHADOW_BET/SHADOW_PASS, but this runner grants no OFFICIAL or
promotion authority and never edits deployment eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
from zoneinfo import ZoneInfo

from sportsedge.mlb_direct_dk_game_source import fetch_mlb_direct_dk_game_quotes
from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256
from sportsedge.mlb_run_machine import machine_report_to_dict, run_it_mlb

CHICAGO_TZ = ZoneInfo("America/Chicago")
LEDGER_SCHEMA = "MLB_DIRECT_DK_SHADOW_LEDGER_V1"
SOURCE_CLASS = "DRAFTKINGS_DIRECT_WEB_V1"


def _canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _persist_raw(root: Path, raw: bytes, digest: str) -> str:
    target = root / "raw" / f"{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise RuntimeError("DIRECT_DK_RAW_HASH_COLLISION")
    else:
        with target.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    return str(target)


def _write_shadow_ledger(*, report: dict, source: dict, root: Path) -> dict | None:
    rows = [dict(row) for row in report.get("results", []) if row.get("model_p") is not None and row.get("shadow_status") in {"SHADOW_BET", "SHADOW_PASS", "MODEL_CANDIDATE_ONE_SIDED"}]
    if not rows:
        return None
    record = {
        "schema_version": LEDGER_SCHEMA,
        "slate_date_ct": report.get("slate_date_ct"),
        "generated_at_utc": report.get("generated_at_utc"),
        "source": source,
        "model_artifact_sha256": mlb_model_artifact_sha256(),
        "official_authority": False,
        "promotion_authority": False,
        "deployment_eligibility_changed": False,
        "row_count": len(rows),
        "rows": rows,
    }
    canonical = _canonical_bytes(record)
    digest = hashlib.sha256(canonical).hexdigest()
    generated = datetime.fromisoformat(str(report["generated_at_utc"]).replace("Z", "+00:00"))
    stamp = generated.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = root / str(report["slate_date_ct"])
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stamp}_{digest}.json"
    raw = canonical + b"\n"
    try:
        with target.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        created = True
    except FileExistsError:
        if target.read_bytes() != raw:
            raise RuntimeError("SHADOW_LEDGER_IMMUTABILITY_COLLISION")
        created = False
    return {"schema_version": LEDGER_SCHEMA, "path": str(target), "sha256": digest, "row_count": len(rows), "created": created}


def run(*, now: datetime, output: Path, raw_root: Path, ledger_root: Path, require_confirmed_lineup: bool = True) -> tuple[dict, int]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = now.astimezone(timezone.utc)
    slate_date = current.astimezone(CHICAGO_TZ).date()
    try:
        snapshot = fetch_mlb_direct_dk_game_quotes(target_date=slate_date, now=current)
        raw_path = _persist_raw(raw_root, snapshot.raw, snapshot.raw_sha256)
        source = {
            "source_class": SOURCE_CLASS,
            "source_uri": snapshot.source_uri,
            "observed_at_utc": snapshot.received_at.isoformat(),
            "timestamp_semantics": "HTTP_RESPONSE_RECEIPT_UPPER_BOUND",
            "raw_sha256": snapshot.raw_sha256,
            "raw_path": raw_path,
            "quote_count": len(snapshot.quotes),
            "failures": [dict(x) for x in snapshot.failures],
        }
        if not snapshot.quotes:
            payload = {
                "status": "BLOCKED_NO_DIRECT_DK_QUOTES",
                "report": {"mode": "HYBRID", "slate_date_ct": slate_date.isoformat(), "generated_at_utc": current.isoformat(), "run_status": "BLOCKED_NO_DIRECT_DK_QUOTES", "results": [], "source_failures": [*source["failures"], {"reason": "DIRECT_DK_NO_ADMISSIBLE_QUOTES"}], "summary": {"quote_count": 0, "model_priced": 0, "official_bets": 0}},
                "direct_dk_source": source,
                "governance": {"official_authority": False, "promotion_authority": False, "deployment_eligibility_changed": False},
            }
            rc = 2
        else:
            machine = run_it_mlb(mode="HYBRID", quotes=list(snapshot.quotes), now=current, require_confirmed_lineup=require_confirmed_lineup)
            report = machine_report_to_dict(machine)
            report.setdefault("source_failures", []).extend(source["failures"])
            payload = {"status": report.get("run_status"), "report": report, "direct_dk_source": source, "governance": {"official_authority": False, "promotion_authority": False, "deployment_eligibility_changed": False}}
            ledger = _write_shadow_ledger(report=report, source=source, root=ledger_root)
            if ledger is not None:
                payload["shadow_ledger"] = ledger
            rc = 0 if report.get("results") else 2
    except Exception as exc:
        payload = {
            "status": "BLOCKED",
            "report": {"mode": "HYBRID", "slate_date_ct": slate_date.isoformat(), "generated_at_utc": current.isoformat(), "run_status": "BLOCKED", "results": [], "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}], "summary": {"quote_count": 0, "model_priced": 0, "official_bets": 0}},
            "governance": {"official_authority": False, "promotion_authority": False, "deployment_eligibility_changed": False},
        }
        rc = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return payload, rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/run_it/mlb_direct_shadow_card.json")
    parser.add_argument("--raw-dir", default="artifacts/mlb_direct_dk")
    parser.add_argument("--shadow-ledger-dir", default="artifacts/shadow_ledger/mlb")
    parser.add_argument("--require-confirmed-lineup", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    payload, rc = run(now=datetime.now(timezone.utc), output=Path(args.output), raw_root=Path(args.raw_dir), ledger_root=Path(args.shadow_ledger_dir), require_confirmed_lineup=args.require_confirmed_lineup)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
