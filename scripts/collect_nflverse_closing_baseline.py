"""Archive the nflverse games file as the NFL game-line MARKET BASELINE.

EVALUATION-SIDE ONLY. This archive is the market baseline for NFL game-line
backtests and screens: closing spread/total (and moneylines) against which
model constructions are judged. It is NEVER a pricing input — no pricing
path may read it, and its lines must never be blended into a model number.

Source: nflverse/nfldata games.csv (consensus closing lines), free, no key.
    https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv

Sign convention (verified 2026-10-24): nflverse `spread_line` is the home
team's closing spread expressed as expected home margin — positive means the
home team is favored. In betting notation the home spread is `-spread_line`.
`total_line` is the closing game total.

Admission evidence (Rocky, 2026-10-24, against the live file):
  - Columns spread_line / total_line / away_moneyline / home_moneyline all
    present (7,548 rows at admission).
  - Population 2019-2025: 100% of games carry both closing lines every
    season (267-285 games/season). 2026: populated for all played games
    through week 7 at admission time.
  - Spot-checks vs independent records (3 games, 6 line values):
    totals 3/3 exact; spreads 2/3 exact and one off by 1.0
    (PIT @ NE 2026-09-20: nflverse NE -4.5 vs TheOddsGap 19-book consensus
    NE -5.5; DK-capture check NE @ CHI 2026-10-22 matched exactly on both
    spread and total). Consensus sources can differ slightly; treat this
    baseline as consensus-grade, not single-book truth.

Writes (under --out-dir):
  games_closing_baseline.csv   (closing-line subset of the games file)
  manifest.json                (source URL, sha256 of source and archive,
                                row counts, per-season population, labels)

Exit codes: 0 = archived, 2 = failed closed (bad source / missing columns /
a covered season with zero populated closing lines).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
)
REQUIRED_COLUMNS = {
    "game_id",
    "season",
    "week",
    "gameday",
    "away_team",
    "home_team",
    "away_score",
    "home_score",
    "spread_line",
    "total_line",
    "away_moneyline",
    "home_moneyline",
}
ARCHIVE_COLUMNS = [
    "game_id",
    "season",
    "week",
    "gameday",
    "away_team",
    "home_team",
    "spread_line",
    "total_line",
    "away_moneyline",
    "home_moneyline",
    "away_score",
    "home_score",
]
LABELS = {
    "role": "NFL game-line MARKET BASELINE (evaluation-side only)",
    "pricing_input": False,
    "source": "nflverse",
    "sportsbook": "UNIDENTIFIED",
    "is_draftkings_quote": False,
    "is_immutable_capture_receipt": False,
    "source_quote_timestamp_available": False,
    "clv_eligible": False,
    "price_role": "historical consensus CLOSE baseline only",
    "provenance_limit": "Fetched timestamp is archive retrieval time, NOT pregame quote time",
    "usage": "backtests and screens only; never blended into a model number",
    "spread_line_semantics": (
        "home team's closing spread as expected home margin "
        "(positive = home favored); betting-notation home spread = -spread_line"
    ),
}


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SportsEdge/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_games(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"games file missing required columns: {sorted(missing)}")
    return [dict(row) for row in reader]


def _populated(row: dict[str, str]) -> bool:
    """A complete four-field baseline, never a timestamped DK closing quote."""
    fields = ("spread_line", "total_line", "away_moneyline", "home_moneyline")
    present = []
    for key in fields:
        raw = row.get(key)
        if raw is None or str(raw).strip() in ("", "NA"):
            present.append(False)
            continue
        try:
            number = Decimal(str(raw).strip())
        except InvalidOperation as exc:
            raise ValueError(f"NFLVERSE_CLOSE_VALUE_INVALID:{key}:{raw}") from exc
        if not number.is_finite():
            raise ValueError(f"NFLVERSE_CLOSE_VALUE_INVALID:{key}:{raw}")
        if key in ("away_moneyline", "home_moneyline") and (
            number != number.to_integral_value() or abs(number) < 100
        ):
            raise ValueError(f"NFLVERSE_CLOSE_PRICE_INVALID:{key}:{raw}")
        present.append(True)
    return all(present)


def coverage(rows: list[dict[str, str]]) -> dict[int, dict[str, int]]:
    cov: dict[int, dict[str, int]] = {}
    for row in rows:
        season = int(row["season"])
        entry = cov.setdefault(season, {"games": 0, "closing_populated": 0})
        entry["games"] += 1
        if _populated(row):
            entry["closing_populated"] += 1
    return cov


def archive(payload: bytes, out_dir: Path, source_url: str = SOURCE_URL) -> dict:
    rows = parse_games(payload)
    cov = coverage(rows)
    for season, entry in sorted(cov.items()):
        if 2019 <= season and entry["closing_populated"] == 0:
            raise ValueError(f"season {season} has zero populated closing lines")
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / "games_closing_baseline.csv"
    with archive_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ARCHIVE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in ARCHIVE_COLUMNS})
    manifest = {
        "source": "nflverse/nfldata games.csv",
        "source_url": source_url,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "archive_file": archive_path.name,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "rows": len(rows),
        "coverage": {str(s): cov[s] for s in sorted(cov)},
        "labels": LABELS,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--source-file",
        type=Path,
        default=None,
        help="use an already-downloaded games.csv instead of fetching",
    )
    args = parser.parse_args(argv)
    try:
        payload = (
            args.source_file.read_bytes()
            if args.source_file
            else fetch_bytes(SOURCE_URL)
        )
        manifest = archive(payload, args.out_dir)
    except Exception as exc:  # fail closed
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        f"archived {manifest['rows']} games; "
        f"sha256 {manifest['archive_sha256'][:16]}..."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
