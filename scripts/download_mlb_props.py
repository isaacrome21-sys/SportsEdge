"""Stream SmartStake/mlb-player-props and keep strikeout / hit / total-base lines.
Read-only data pull. Prints the schema first so the filter can be checked.
Output is gzipped CSV, never committed to the repo.
"""
import argparse, csv, gzip, os, sys
from collections import Counter

KEYWORDS = ("strikeout", "hit", "total_bases", "total bases", "player bases")

# The published SmartStake 2026 archive is month-partitioned. Only the
# March-June partitions contain settled outcomes at the source freeze.
SETTLED_MONTHS = ("2026-03", "2026-04", "2026-05", "2026-06")


def dataset_options(month: str) -> dict:
    """Select an exact source partition without changing default all-data intake."""
    if not month:
        return {}
    if month not in SETTLED_MONTHS:
        raise ValueError("MLB_MONTH_NOT_SETTLED_OR_NOT_PUBLISHED")
    return {"data_files": {"train": f"mon={month}/part-*.parquet"}}

def keep(row) -> bool:
    text = " ".join(str(row.get(k, "")) for k in ("market", "market_name", "prop")).lower()
    return any(k in text for k in KEYWORDS)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=2_000_000)
    ap.add_argument("--month", default="", help="Optional exact settled SmartStake partition, e.g. 2026-04")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.max_rows < 0:
        ap.error("--max-rows must be nonnegative (0 means unbounded within the chosen partition)")
    try:
        source_options = dataset_options(args.month)
    except ValueError as exc:
        ap.error(str(exc))
    from datasets import load_dataset  # Optional network dependency, only after input validation.

    os.makedirs(args.out, exist_ok=True)
    ds = load_dataset("SmartStake/mlb-player-props", split="train", streaming=True, **source_options)
    first = next(iter(ds))
    print("SCHEMA:", sorted(first.keys()))
    fields = list(first.keys())
    suffix = f"_{args.month}" if args.month else ""
    path = os.path.join(args.out, f"mlb_props_targets{suffix}.csv.gz")
    kept = seen = 0
    markets = Counter()
    game_ids = set()
    event_dates = set()
    with gzip.open(path, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in ds:
            seen += 1
            if keep(row):
                w.writerow(row)
                kept += 1
                markets[str(row.get("market") or "").strip().lower()] += 1
                if row.get("game_id") is not None:
                    game_ids.add(str(row["game_id"]))
                if row.get("start_time") is not None:
                    event_dates.add(str(row["start_time"])[:10])
            if args.max_rows and kept >= args.max_rows:
                break
            if seen % 5_000_000 == 0:
                print(f"scanned {seen:,} kept {kept:,}", file=sys.stderr)
    print(f"DONE scanned={seen} kept={kept} games={len(game_ids)} "
          f"dates={len(event_dates)} markets={dict(sorted(markets.items()))} file={path}")
    print("CANDIDATE HISTORICAL DATA ONLY — neither closing-price certification "
          "nor forward-validation rows; count dates and verify timestamp/book/side pairs.")
    if args.month and not kept:
        print("REFUSED: SELECTED_MONTH_HAS_NO_MATCHING_ROWS", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
