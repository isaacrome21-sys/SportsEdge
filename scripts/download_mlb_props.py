"""Stream SmartStake/mlb-player-props and keep strikeout / hit / total-base lines.
Read-only data pull. Prints the schema first so the filter can be checked.
Output is gzipped CSV, never committed to the repo.
"""
import argparse, csv, gzip, os, sys
from datasets import load_dataset

KEYWORDS = ("strikeout", "hit", "total_bases", "total bases")

def keep(row) -> bool:
    text = " ".join(str(row.get(k, "")) for k in ("market", "market_name", "prop")).lower()
    return any(k in text for k in KEYWORDS)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=2_000_000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    ds = load_dataset("SmartStake/mlb-player-props", split="train", streaming=True)
    first = next(iter(ds))
    print("SCHEMA:", sorted(first.keys()))
    fields = list(first.keys())
    path = os.path.join(args.out, "mlb_props_targets.csv.gz")
    kept = seen = 0
    with gzip.open(path, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        from itertools import chain
        for row in chain([first], ds):
            seen += 1
            if keep(row):
                w.writerow(row)
                kept += 1
            if args.max_rows and kept >= args.max_rows:
                break
            if seen % 5_000_000 == 0:
                print(f"scanned {seen:,} kept {kept:,}", file=sys.stderr)
    print(f"DONE scanned={seen} kept={kept} file={path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
