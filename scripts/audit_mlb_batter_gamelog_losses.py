#!/usr/bin/env python3
"""Offline diagnostic for MLB StatsAPI batter game-log row losses.

This does NOT fetch data, repair historical gaps, price a market, or certify a
point-in-time observation. Feed it a previously captured raw gameLog JSON and
its *actual* capture time. Its accepted-row rules mirror the existing
MLBBatterPublicSource history parser so a blocked 10-game minimum is auditable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

CORE = (
    "plateAppearances", "hits", "totalBases", "rbi", "runs", "homeRuns",
    "stolenBases",
)
OPTIONAL = ("baseOnBalls", "strikeOuts", "doubles", "triples")


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError(label + "_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(label + "_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _count(value: Any, label: str) -> int:
    """Match the canonical source's strict nonnegative integer contract."""
    if isinstance(value, bool):
        raise ValueError(label + "_INVALID")
    try:
        parsed = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(label + "_INVALID") from exc
    if parsed < 0 or str(parsed) != str(value).strip():
        raise ValueError(label + "_INVALID")
    return parsed


def _row_date(value: Any) -> date:
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError) as exc:
        raise ValueError("HISTORY_DATE_INVALID") from exc


def audit_gamelog(
    payload: dict[str, Any], *, as_of_utc: str,
    kickoff_utc: str, observed_at_utc: str, max_games: int = 30,
) -> dict[str, Any]:
    """Count exactly why StatsAPI gameLog entries fail current ingestion.

    A parsed row is not independent evidence of source availability before
    first pitch. Full source receipts, player/fixture identity, the lineup and
    quote pairing are separate prerequisites. Counts are diagnostics only.
    """
    as_of = _utc(as_of_utc, "AS_OF")
    kickoff = _utc(kickoff_utc, "KICKOFF")
    observed = _utc(observed_at_utc, "OBSERVED_AT")
    if not isinstance(max_games, int) or isinstance(max_games, bool) or max_games < 10:
        raise ValueError("MAX_GAMES_BELOW_SOURCE_MINIMUM")
    if not isinstance(payload, dict) or not isinstance(payload.get("stats"), list):
        raise ValueError("MLB_BATTER_GAMELOG_UNAVAILABLE")

    rejection = Counter()
    records = []
    for group in payload["stats"]:
        if not isinstance(group, dict) or not isinstance(group.get("splits"), list):
            rejection["STATS_GROUP_WITHOUT_SPLITS"] += 1
            continue
        for entry in group["splits"]:
            if not isinstance(entry, dict):
                rejection["GAMELOG_ROW_NOT_OBJECT"] += 1
                continue
            try:
                when = _row_date(entry.get("date"))
                # Same conservative day-only rule as live batter source:
                # a same-day completed game cannot be called prior evidence.
                if when >= as_of.date():
                    rejection["NOT_PRIOR_TO_AS_OF_DATE"] += 1
                    continue
                if when >= kickoff.date():
                    rejection["NOT_PRIOR_TO_KICKOFF_DATE"] += 1
                    continue
                stat = entry.get("stat")
                if not isinstance(stat, dict):
                    rejection["STAT_OBJECT_MISSING"] += 1
                    continue
                pa = _count(stat.get("plateAppearances"), "PLATE_APPEARANCES")
                if pa < 1:
                    rejection["ZERO_PLATE_APPEARANCES"] += 1
                    continue
                game_id = _count((entry.get("game") or {}).get("gamePk"),
                                 "HISTORY_GAME_PK")
                if not game_id:
                    rejection["HISTORY_GAME_PK_INVALID"] += 1
                    continue
                fields = {k: _count(stat.get(k), k.upper()) for k in CORE}
                for name in OPTIONAL:
                    if name in stat:
                        fields[name] = _count(stat[name], name.upper())
                if "doubles" in fields and "triples" in fields:
                    singles = fields["hits"] - fields["doubles"] - fields["triples"] - fields["homeRuns"]
                    if singles < 0:
                        rejection["INCONSISTENT_EXTRA_BASE_HIT_COUNTS"] += 1
                        continue
                records.append((when, game_id, fields))
            except ValueError as exc:
                rejection[str(exc)] += 1
            except (AttributeError, TypeError):
                rejection["GAMELOG_ROW_STRUCTURE_INVALID"] += 1

    records.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = []
    seen = set()
    for entry in records:
        if entry[1] in seen:
            rejection["DUPLICATE_GAME_PK"] += 1
            continue
        seen.add(entry[1])
        if len(selected) < max_games:
            selected.append(entry)
        else:
            rejection["BEYOND_MAX_GAMES"] += 1

    coverage = {field: sum(field in stats for _, _, stats in selected)
                for field in CORE + OPTIONAL}
    total_pa = sum(stats["plateAppearances"] for _, _, stats in selected)
    return {
        "schema": "MLB_BATTER_GAMELOG_LOSS_AUDIT_V1",
        "diagnostic_only": True,
        "independent_model_validation": False,
        "backfilled_evidence": False,
        "pregame_observation_verified": observed < kickoff,
        "observed_at_utc": observed.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "kickoff_utc": kickoff.isoformat(),
        "retained_prior_games": len(selected),
        "retained_plate_appearances": total_pa,
        "history_minimum_met": len(selected) >= 10 and total_pa >= 20,
        "per_field_retained_game_count": coverage,
        "rejected_row_counts": dict(sorted(rejection.items())),
        "notes": [
            "No network access; input must be an authentic externally captured StatsAPI payload.",
            "A capture timestamp is supplied, not independently authenticated by this audit.",
            "Game-log counts alone do not validate lineup, market quote, model skill or an edge.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Locally archived raw StatsAPI JSON")
    parser.add_argument("--as-of", required=True, dest="as_of_utc",
                        help="UTC-aware intended prediction time")
    parser.add_argument("--kickoff", required=True, dest="kickoff_utc",
                        help="UTC-aware verified fixture start")
    parser.add_argument("--observed-at", required=True, dest="observed_at_utc",
                        help="UTC-aware *actual* source capture time")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(audit_gamelog(payload, as_of_utc=args.as_of_utc,
                                   kickoff_utc=args.kickoff_utc,
                                   observed_at_utc=args.observed_at_utc),
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
