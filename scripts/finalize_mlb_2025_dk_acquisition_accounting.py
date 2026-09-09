#!/usr/bin/env python3
"""Finalize 2025 DK-opening acquisition accounting for the frozen v2B prereg.

This is an acquisition/provenance step only. It does not read model features,
outcomes, scores, grades, or 2025 model results. The frozen prereg requires an
archived DK opening price for a game to be evaluated, but it does not authorize
inventing a price when DraftKings is absent from the historical source.

Every official regular-season gamePk is therefore classified as exactly one of:
- VALID_PRIMARY_DK_OPEN
- PRIMARY_DK_OPEN_UNAVAILABLE
- PRIMARY_SOURCE_ROW_UNAVAILABLE

Unavailable rows are explicit exclusions from the later confirmatory join, not
imputed observations and not evidence of a failed model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_OFFICIAL_GAMEPKS = 2430
EXPECTED_PREREG_SHA256 = (
    "4f9e571b0b7c5ba735c18682563e28adf873418e40b5fcf747918680be4e6cc7"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def official_inventory(schedule_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, list[dict[str, Any]]] = {}
    for block in schedule_payload.get("dates", []):
        block_date = str(block.get("date", ""))
        for item in block.get("games", []):
            if item.get("gameType") != "R":
                continue
            pk = int(item["gamePk"])
            rows.setdefault(pk, []).append(
                {
                    "gamePk": pk,
                    "schedule_date": block_date,
                    "gameDate": item.get("gameDate"),
                    "away": item["teams"]["away"]["team"]["name"],
                    "home": item["teams"]["home"]["team"]["name"],
                    "state": (item.get("status") or {}).get("detailedState", ""),
                }
            )

    out: dict[int, dict[str, Any]] = {}
    for pk, occurrences in rows.items():
        finals = [
            row
            for row in occurrences
            if str(row["state"]).lower() in {"final", "game over", "completed early"}
        ]
        pool = finals or occurrences
        out[pk] = max(pool, key=lambda row: (str(row["gameDate"]), row["schedule_date"]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-report", required=True)
    parser.add_argument("--openings-csv", required=True)
    parser.add_argument("--schedule-json", required=True)
    parser.add_argument("--expected-prereg-sha-file", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    recovery_report_path = Path(args.recovery_report)
    openings_path = Path(args.openings_csv)
    schedule_path = Path(args.schedule_json)
    prereg_sha_path = Path(args.expected_prereg_sha_file)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    prereg_sha = prereg_sha_path.read_text(encoding="utf-8").strip()
    if prereg_sha != EXPECTED_PREREG_SHA256:
        raise SystemExit(
            f"FROZEN_PREREG_SHA_MISMATCH:{prereg_sha}!={EXPECTED_PREREG_SHA256}"
        )

    recovery = json.loads(recovery_report_path.read_text(encoding="utf-8"))
    schedule_payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    official = official_inventory(schedule_payload)
    if len(official) != EXPECTED_OFFICIAL_GAMEPKS:
        raise SystemExit(
            f"OFFICIAL_GAMEPK_COUNT_MISMATCH:{len(official)}!={EXPECTED_OFFICIAL_GAMEPKS}"
        )

    with openings_path.open(newline="", encoding="utf-8") as handle:
        opening_rows = list(csv.DictReader(handle))

    by_pk: dict[int, dict[str, str]] = {}
    duplicate_csv_gamepks: list[int] = []
    for row in opening_rows:
        pk = int(row["gamePk"])
        if pk in by_pk:
            duplicate_csv_gamepks.append(pk)
        else:
            by_pk[pk] = row

    report_recon = recovery.get("reconciliation") or {}
    source_duplicates = list(report_recon.get("duplicate_bound_gamePks") or [])
    source_ambiguities = list(report_recon.get("ambiguous_rows") or [])
    if duplicate_csv_gamepks or source_duplicates or source_ambiguities:
        raise SystemExit(
            "ACQUISITION_IDENTITY_NOT_UNIQUE:"
            f"csv={duplicate_csv_gamepks}:source={source_duplicates}:"
            f"ambiguous={len(source_ambiguities)}"
        )

    foreign_gamepks = sorted(set(by_pk) - set(official))
    if foreign_gamepks:
        raise SystemExit(f"OPENING_ROWS_OUTSIDE_OFFICIAL_SCHEDULE:{foreign_gamepks}")

    accounting: list[dict[str, Any]] = []
    valid_gamepks: list[int] = []
    unavailable_gamepks: list[int] = []
    missing_source_row_gamepks: list[int] = []

    for pk in sorted(official):
        game = official[pk]
        price_row = by_pk.get(pk)
        if price_row is None:
            status = "PRIMARY_SOURCE_ROW_UNAVAILABLE"
            missing_source_row_gamepks.append(pk)
            away_open = None
            home_open = None
            binding_mode = None
            source_row_id = None
        elif truthy(price_row.get("draftkings_open_valid")):
            status = "VALID_PRIMARY_DK_OPEN"
            valid_gamepks.append(pk)
            away_open = price_row.get("awayML_open_DK")
            home_open = price_row.get("homeML_open_DK")
            binding_mode = price_row.get("binding_mode")
            source_row_id = price_row.get("source_row_id")
        else:
            status = "PRIMARY_DK_OPEN_UNAVAILABLE"
            unavailable_gamepks.append(pk)
            away_open = price_row.get("awayML_open_DK") or None
            home_open = price_row.get("homeML_open_DK") or None
            binding_mode = price_row.get("binding_mode")
            source_row_id = price_row.get("source_row_id")

        accounting.append(
            {
                "gamePk": pk,
                "official_date": game["schedule_date"],
                "official_start": game["gameDate"],
                "away": game["away"],
                "home": game["home"],
                "acquisition_status": status,
                "awayML_open_DK": away_open,
                "homeML_open_DK": home_open,
                "binding_mode": binding_mode,
                "source_row_id": source_row_id,
                "confirmatory_price_eligible": status == "VALID_PRIMARY_DK_OPEN",
            }
        )

    accounted_gamepks = {int(row["gamePk"]) for row in accounting}
    unresolved_identity_gamepks = sorted(set(official) - accounted_gamepks)
    complete = bool(
        len(accounting) == EXPECTED_OFFICIAL_GAMEPKS
        and len(accounted_gamepks) == EXPECTED_OFFICIAL_GAMEPKS
        and not unresolved_identity_gamepks
        and not duplicate_csv_gamepks
        and not source_duplicates
        and not source_ambiguities
    )

    accounting_csv = outdir / "dk_opening_acquisition_accounting_2025.csv"
    fields = [
        "gamePk",
        "official_date",
        "official_start",
        "away",
        "home",
        "acquisition_status",
        "awayML_open_DK",
        "homeML_open_DK",
        "binding_mode",
        "source_row_id",
        "confirmatory_price_eligible",
    ]
    with accounting_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(accounting)

    summary = {
        "schema_version": 1,
        "purpose": "FROZEN_2025_PREREG_DK_OPENING_ACQUISITION_ACCOUNTING",
        "frozen_prereg_sha256": prereg_sha,
        "official_gamePks": len(official),
        "accounted_gamePks": len(accounted_gamepks),
        "confirmatory_price_eligible_gamePks": len(valid_gamepks),
        "primary_dk_open_unavailable_gamePks": unavailable_gamepks,
        "primary_source_row_unavailable_gamePks": missing_source_row_gamepks,
        "unresolved_identity_gamePks": unresolved_identity_gamepks,
        "no_price_imputation": True,
        "confirmatory_test_executed": False,
        "model_or_threshold_changed": False,
        "promotion_claimed": False,
        "full_season_acquisition_accounting_complete": complete,
        "source_artifacts": {
            "recovery_report_sha256": sha256_bytes(recovery_report_path.read_bytes()),
            "openings_csv_sha256": sha256_bytes(openings_path.read_bytes()),
            "schedule_json_sha256": sha256_bytes(schedule_path.read_bytes()),
        },
        "output_artifacts": {
            "accounting_csv_sha256": sha256_bytes(accounting_csv.read_bytes()),
        },
    }
    summary_path = outdir / "acquisition_accounting_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))

    if not complete:
        raise SystemExit("FULL_SEASON_ACQUISITION_ACCOUNTING_INCOMPLETE")


if __name__ == "__main__":
    main()
