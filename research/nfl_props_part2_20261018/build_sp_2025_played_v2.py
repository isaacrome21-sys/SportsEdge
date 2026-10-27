"""Build the corrected 2025 season file: sp_2025_played_v2.csv.gz.

B8 re-pin tooling (AMENDMENT_B8_SP2025_REPIN_20261026.md in this package and
in research/nfl_props_part2b_20261020/). The as-published nflverse
sp_2025.csv.gz (pinned in both packages' SPEC_HASHES.txt before this
re-pin at sha256
c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b)
carries a row for every rostered player each week, including players who
did not play. The frozen evaluator loader counts every row as a played
game, so 771 zero-usage skill-position REG rows act as phantom 0.0 games:
434 skill-player-weeks in 2025 reach the construction's "3 prior games"
with fewer than 3 actually played (Oct 24, 2026 sweep, probes.py S12;
replicated exactly before this artifact was built).

Played-game predicate (the ONLY rows removed): a row is removed iff
  * its own "position" field is a skill position (QB, RB, WR, TE, FB), AND
  * f(attempts) + f(carries) + f(targets) == 0,
where f() is the evaluator loader's own coercion (float(v), 0.0 when the
cell is blank or non-numeric). Attempts/carries/targets are the file's own
participation evidence: a skill player who took part in a play either
threw, carried, or was targeted. Rows for every other position pass
through untouched (defenders, kickers and punters record no
attempts/carries/targets by construction; their rows are not phantom
evidence for these packages and are not this correction's to delete).

The original file is never modified. The corrected artifact keeps the
original's schema, column order and row order; every kept row is
byte-identical to the original's. Serialization is deterministic
(csv, LF line endings, gzip mtime=0, compresslevel=9), so rebuilding from
the same source reproduces the same sha256.

Usage:
  python3 build_sp_2025_played_v2.py --src sp_2025.csv.gz \
      --out sp_2025_played_v2.csv.gz
Prints the kept/removed counts and the output sha256 (the value pinned in
SPEC_HASHES.txt under the re-pin).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

SKILL_POSITIONS = ("QB", "RB", "WR", "TE", "FB")
USAGE_COLUMNS = ("attempts", "carries", "targets")
SOURCE_NAME = "sp_2025.csv.gz"
ARTIFACT_NAME = "sp_2025_played_v2.csv.gz"


def fnum(v) -> float:
    """The evaluator loader's cell coercion (eval load(): float, else 0.0)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def is_phantom(row: dict) -> bool:
    """True iff the row is a no-participation skill-position roster row."""
    if row.get("position") not in SKILL_POSITIONS:
        return False
    return sum(fnum(row.get(c)) for c in USAGE_COLUMNS) == 0.0


def build_corrected(src: Path) -> tuple[bytes, dict]:
    """Return (gzip bytes of the corrected artifact, counts dict)."""
    text = gzip.decompress(src.read_bytes()).decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    idx = {name: i for i, name in enumerate(header)}
    kept: list[list[str]] = []
    removed = {"REG": 0, "POST": 0, "other": 0}
    for r in body:
        row = {name: r[i] for name, i in idx.items()}
        if is_phantom(row):
            st = row.get("season_type")
            removed[st if st in removed else "other"] += 1
            continue
        kept.append(r)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(kept)
    payload = gzip.compress(buf.getvalue().encode("utf-8"),
                            compresslevel=9, mtime=0)
    counts = {"source_rows": len(body), "kept_rows": len(kept),
              "removed_rows": len(body) - len(kept), "removed_by_type": removed,
              "sha256": hashlib.sha256(payload).hexdigest()}
    return payload, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    payload, counts = build_corrected(a.src)
    a.out.write_bytes(payload)
    print(json.dumps({"artifact": str(a.out), **counts}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
