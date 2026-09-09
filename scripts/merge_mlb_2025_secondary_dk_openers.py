#!/usr/bin/env python3
"""Merge verified secondary DK openers into full-season acquisition accounting.

Only rows emitted by recover_mlb_2025_secondary_dk_openers.py are accepted.
Primary valid prices are never overwritten. Secondary rows must match the same
official gamePk and exact team identity. Remaining unavailable rows stay
unavailable and are excluded from the confirmatory price join.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_SECONDARY_GAMEPKS = {777861, 778247, 778552}
EXPECTED_OFFICIAL_GAMEPKS = 2430


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def norm(value: str) -> str:
    return " ".join((value or "").lower().replace(".", "").split())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-accounting", required=True)
    parser.add_argument("--primary-summary", required=True)
    parser.add_argument("--secondary-csv", required=True)
    parser.add_argument("--secondary-manifest", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    primary_path = Path(args.primary_accounting)
    primary_summary_path = Path(args.primary_summary)
    secondary_path = Path(args.secondary_csv)
    secondary_manifest_path = Path(args.secondary_manifest)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    with primary_path.open(newline="", encoding="utf-8") as handle:
        primary_rows = list(csv.DictReader(handle))
    with secondary_path.open(newline="", encoding="utf-8") as handle:
        secondary_rows = list(csv.DictReader(handle))

    primary_summary = json.loads(primary_summary_path.read_text(encoding="utf-8"))
    secondary_manifest = json.loads(
        secondary_manifest_path.read_text(encoding="utf-8")
    )
    if not primary_summary.get("full_season_acquisition_accounting_complete"):
        raise SystemExit("PRIMARY_ACCOUNTING_NOT_COMPLETE")
    if not secondary_manifest.get("no_outcomes_read"):
        raise SystemExit("SECONDARY_PROVENANCE_OUTCOME_GUARD_MISSING")
    if not secondary_manifest.get("no_consensus_or_other_book_substitution"):
        raise SystemExit("SECONDARY_BOOK_IDENTITY_GUARD_MISSING")

    by_pk: dict[int, dict[str, str]] = {}
    for row in primary_rows:
        pk = int(row["gamePk"])
        if pk in by_pk:
            raise SystemExit(f"PRIMARY_ACCOUNTING_DUPLICATE_GAMEPK:{pk}")
        by_pk[pk] = dict(row)
    if len(by_pk) != EXPECTED_OFFICIAL_GAMEPKS:
        raise SystemExit(
            f"PRIMARY_ACCOUNTING_COUNT_MISMATCH:{len(by_pk)}!={EXPECTED_OFFICIAL_GAMEPKS}"
        )

    secondary_by_pk: dict[int, dict[str, str]] = {}
    for row in secondary_rows:
        pk = int(row["gamePk"])
        if pk in secondary_by_pk:
            raise SystemExit(f"SECONDARY_DUPLICATE_GAMEPK:{pk}")
        secondary_by_pk[pk] = row
    if set(secondary_by_pk) != EXPECTED_SECONDARY_GAMEPKS:
        raise SystemExit(
            "SECONDARY_ALLOWLIST_MISMATCH:"
            f"{sorted(secondary_by_pk)}!={sorted(EXPECTED_SECONDARY_GAMEPKS)}"
        )

    applied: list[int] = []
    for pk in sorted(secondary_by_pk):
        primary = by_pk.get(pk)
        secondary = secondary_by_pk[pk]
        if primary is None:
            raise SystemExit(f"SECONDARY_GAMEPK_NOT_OFFICIAL:{pk}")
        if truthy(primary.get("confirmatory_price_eligible")):
            raise SystemExit(f"SECONDARY_WOULD_OVERWRITE_VALID_PRIMARY:{pk}")
        if norm(primary.get("away", "")) != norm(secondary.get("away", "")):
            raise SystemExit(f"SECONDARY_AWAY_IDENTITY_MISMATCH:{pk}")
        if norm(primary.get("home", "")) != norm(secondary.get("home", "")):
            raise SystemExit(f"SECONDARY_HOME_IDENTITY_MISMATCH:{pk}")

        primary["acquisition_status"] = "VALID_SECONDARY_DK_OPEN"
        primary["awayML_open_DK"] = secondary["awayML_open_DK"]
        primary["homeML_open_DK"] = secondary["homeML_open_DK"]
        primary["binding_mode"] = secondary["binding_mode"]
        primary["source_row_id"] = f"secondary:{pk}"
        primary["confirmatory_price_eligible"] = "True"
        primary["price_source"] = secondary["source"]
        primary["source_url"] = secondary["source_url"]
        primary["source_sha256"] = secondary["source_sha256"]
        applied.append(pk)

    for row in by_pk.values():
        row.setdefault("price_source", "SportsBookReview __NEXT_DATA__")
        row.setdefault("source_url", "")
        row.setdefault("source_sha256", "")

    final_rows = [by_pk[pk] for pk in sorted(by_pk)]
    eligible = [
        int(row["gamePk"])
        for row in final_rows
        if truthy(row.get("confirmatory_price_eligible"))
    ]
    unavailable = [
        int(row["gamePk"])
        for row in final_rows
        if not truthy(row.get("confirmatory_price_eligible"))
    ]

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
        "price_source",
        "source_url",
        "source_sha256",
    ]
    final_csv = outdir / "dk_opening_acquisition_accounting_2025_final.csv"
    with final_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(final_rows)

    summary = {
        "schema_version": 1,
        "purpose": "FROZEN_2025_PREREG_FINAL_DK_OPENING_ACCOUNTING",
        "official_gamePks": len(final_rows),
        "accounted_gamePks": len(by_pk),
        "primary_or_secondary_valid_dk_open_gamePks": len(eligible),
        "explicit_dk_open_unavailable_gamePks": unavailable,
        "secondary_recovered_gamePks": applied,
        "no_price_imputation": True,
        "all_official_gamePks_accounted": len(by_pk) == EXPECTED_OFFICIAL_GAMEPKS,
        "confirmatory_test_executed": False,
        "model_or_threshold_changed": False,
        "promotion_claimed": False,
        "source_artifacts": {
            "primary_accounting_sha256": sha256_bytes(primary_path.read_bytes()),
            "primary_summary_sha256": sha256_bytes(primary_summary_path.read_bytes()),
            "secondary_csv_sha256": sha256_bytes(secondary_path.read_bytes()),
            "secondary_manifest_sha256": sha256_bytes(
                secondary_manifest_path.read_bytes()
            ),
        },
        "output_csv_sha256": sha256_bytes(final_csv.read_bytes()),
    }
    summary_path = outdir / "final_acquisition_accounting_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))

    if len(by_pk) != EXPECTED_OFFICIAL_GAMEPKS:
        raise SystemExit("FINAL_ACCOUNTING_NOT_COMPLETE")


if __name__ == "__main__":
    main()
