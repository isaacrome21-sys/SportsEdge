"""Fail-closed input preflight for the NBA early-season V2 screen.

This utility checks structure only.  A column name or caller-supplied value
does not authenticate an event, result receipt, player identity, or source.
It exists to prevent the repository's current NBA results artifact from being
silently upgraded into chronology it does not carry.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


SCREEN_ID = "NBA_EARLY_SEASON_V2_INPUT_PREFLIGHT_V1"

# The V2 construction consumes these canonical row fields.  Aliases cover the
# existing uppercase results-pull values only; chronology/provenance fields are
# deliberately not inferred from GAME_ID, file names, or workflow run time.
REQUIRED_FIELDS = (
    "player_id",
    "game_id",
    "season",
    "game_date",
    "tipoff",
    "observed_at",
    "source_ref",
    "event_state",
    "result_state",
    "finalized_at",
    "role_source_ref",
    "role_observed_at",
    "position",
    "team_id",
    "minutes",
    "points",
    "rebounds",
    "assists",
)

ALIASES = {
    "player_id": ("player_id", "PLAYER_ID"),
    "game_id": ("game_id", "GAME_ID"),
    "season": ("season", "SEASON"),
    "game_date": ("game_date", "GAME_DATE"),
    "tipoff": ("tipoff", "TIPOFF"),
    "observed_at": ("observed_at", "OBSERVED_AT", "RESULT_OBSERVED_AT"),
    "source_ref": ("source_ref", "SOURCE_REF"),
    "event_state": ("event_state", "EVENT_STATE"),
    "result_state": ("result_state", "RESULT_STATE"),
    "finalized_at": ("finalized_at", "FINALIZED_AT"),
    "role_source_ref": ("role_source_ref", "ROLE_SOURCE_REF"),
    "role_observed_at": ("role_observed_at", "ROLE_OBSERVED_AT"),
    "position": ("position", "POSITION"),
    "team_id": ("team_id", "TEAM_ID", "TEAM_ABBREVIATION"),
    "minutes": ("minutes", "MIN"),
    "points": ("points", "PTS"),
    "rebounds": ("rebounds", "REB"),
    "assists": ("assists", "AST"),
}


def audit_columns(columns) -> dict:
    """Return a deterministic structural verdict for an input header."""
    header = [str(value or "").strip() for value in columns]
    if not header or any(not value for value in header):
        raise ValueError("NBA_EARLY_INPUT_HEADER_INVALID")
    folded = [value.casefold() for value in header]
    if len(folded) != len(set(folded)):
        raise ValueError("NBA_EARLY_INPUT_HEADER_DUPLICATE")

    by_fold = {value.casefold(): value for value in header}
    resolved = {}
    for field in REQUIRED_FIELDS:
        match = next(
            (by_fold[name.casefold()] for name in ALIASES[field]
             if name.casefold() in by_fold),
            None,
        )
        if match is not None:
            resolved[field] = match
    missing = [field for field in REQUIRED_FIELDS if field not in resolved]
    return {
        "screen_id": SCREEN_ID,
        "status": (
            "INPUT_CONTRACT_INCOMPLETE" if missing
            else "INPUT_CONTRACT_STRUCTURALLY_READY"
        ),
        "required_fields": list(REQUIRED_FIELDS),
        "resolved_columns": resolved,
        "missing_fields": missing,
        "historical_screen_can_run": not missing,
        "source_authentication": "NOT_ESTABLISHED_BY_COLUMN_NAMES",
        "timestamp_policy": "NEVER_INFER_FROM_GAME_ID_FILENAME_OR_WORKFLOW_TIME",
        "market_validation": "NONE",
        "research_only": True,
        "play_authority": False,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_csv(path: str | Path) -> dict:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        columns = next(csv.reader(handle), None)
    if columns is None:
        raise ValueError("NBA_EARLY_INPUT_HEADER_MISSING")
    result = audit_columns(columns)
    result["input_sha256"] = _sha256(source)
    result["input_name"] = source.name
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit NBA early-season V2 historical input columns")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = audit_csv(args.csv)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["historical_screen_can_run"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
