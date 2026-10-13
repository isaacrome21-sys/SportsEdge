#!/usr/bin/env python3
"""Append settlements for forward-captured MLB records once games are Final.

For every capture in the archive without a settlement, look up the game on
the MLB StatsAPI schedule for its league-local date, require a verified
Final score, grade the selection with the harness's own settle_game, and
APPEND one line to settlements.jsonl. Capture files are never modified;
existing settlements are never rewritten (a wrong settlement is corrected
only by appending a later line with "correction": true, which the
assembler honors while preserving the original).

Pushes grade 0.5 in the harness; the strict evaluator accepts only binary
outcomes, so a push settlement is appended with outcome=null and the
assembler excludes that record with an explicit reason.

Example:
    python scripts/settle_strict_mlb_captures.py \
        --archive-dir archive/strict-forward-capture
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.backtest import forward_capture as fc
from sportsedge.backtest.outcomes import (fetch_mlb_schedule,
                                          parse_completed_mlb_games,
                                          settle_game)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path,
                        default=Path("archive") / fc.ARCHIVE_DIRNAME)
    args = parser.parse_args(argv)
    settled_keys = {fc._settlement_key(s)
                    for s in fc.read_settlements(args.archive_dir)}
    settled, skipped = [], []
    for path, record in fc.read_captures(args.archive_dir):
        key = (str(record["fixture_id"]), str(record["market"]),
               str(record["selection"]), str(record["line"]))
        if key in settled_keys:
            continue
        parts = record["fixture_id"].split(":")
        local_date, away, home = parts[1], parts[2], parts[3]
        dates = fetch_mlb_schedule(local_date, local_date)
        games = parse_completed_mlb_games(dates)
        match = [g for g in games if g["home_team"] == home
                 and g["away_team"] == away]
        if len(match) != 1:
            skipped.append({"capture": path.name,
                            "reason": "FINAL_GAME_NOT_FOUND_OR_AMBIGUOUS"})
            continue
        game = match[0]
        line = None if record["market"] == "ML" else float(record["line"])
        grade = settle_game(game, record["market"], record["selection"],
                            line)
        settlement = {
            "fixture_id": record["fixture_id"],
            "market": record["market"],
            "selection": record["selection"],
            "line": record["line"],
            "outcome": (None if grade == 0.5 else int(grade)),
            "outcome_state": ("PUSH" if grade == 0.5
                              else "WIN" if grade == 1.0 else "LOSS"),
            "outcome_grade": grade,
            "note": ("PUSH_NOT_BINARY_SETTLEABLE" if grade == 0.5
                     else "SETTLED_FINAL"),
            "home_score": game["home_score"],
            "away_score": game["away_score"],
            "game_pk": game["event_id"],
            "source": "MLB_STATSAPI_FINAL",
            "settled_at_utc": datetime.now(timezone.utc).isoformat(),
            "correction": False,
        }
        fc.append_settlement(args.archive_dir, settlement)
        settled.append(settlement)
    print(json.dumps({"settled": settled, "skipped": skipped},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
