#!/usr/bin/env python3
"""Pinned retrieval for the BartTorvik T-Rank archive (DESIGN use only).

Fetches the by-date archive CSV from the toRvik-data mirror at a PINNED
COMMIT (never a moving branch), verifies that every row's date equals the
requested archive date, and prints a JSON manifest entry with the SHA-256
of the exact bytes received.

The archive is a MORNING-OF product: the file for date D holds ratings as
of the morning of D. Using any other vintage for D is lookahead and is
refused by the admission record this script ships with
(research/cbb_barttorvik_admission_20261027/ADMISSION_RECORD.md).

Stdlib only. Usage:
    python3 pull_bart_archive.py 20220113
Exit codes: 0 ok, 2 SOURCE_UNAVAILABLE / ARCHIVE_DATE_MISSING,
3 DATE_MISMATCH / SCHEMA_INVALID.
"""

import csv
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request

PINNED_COMMIT = "46d1036443ca452fdd1c6cf25cf5dff50de68337"
URL_PATTERN = (
    "https://raw.githubusercontent.com/andreweatherman/toRvik-data/"
    + PINNED_COMMIT
    + "/ratings/archive/by_date/ratings_archive_{date}.csv"
)
REQUIRED_COLUMNS = {"team", "conf", "barthag", "adj_o", "adj_d", "date"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-admission-probe"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main(argv):
    if len(argv) != 2 or len(argv[1]) != 8 or not argv[1].isdigit():
        print("usage: pull_bart_archive.py YYYYMMDD", file=sys.stderr)
        return 2
    date = argv[1]
    url = URL_PATTERN.format(date=date)
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        refusal = "ARCHIVE_DATE_MISSING" if exc.code == 404 else "SOURCE_UNAVAILABLE"
        print(json.dumps({"refusal": refusal, "http_status": exc.code, "url": url}))
        return 2
    except urllib.error.URLError as exc:
        print(json.dumps({"refusal": "SOURCE_UNAVAILABLE", "error": str(exc.reason), "url": url}))
        return 2

    text = raw.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or not REQUIRED_COLUMNS.issubset(set(rows[0].keys())):
        print(json.dumps({"refusal": "SCHEMA_INVALID", "url": url}))
        return 3
    expected = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    if any(row["date"] != expected for row in rows):
        print(json.dumps({"refusal": "DATE_MISMATCH", "expected": expected, "url": url}))
        return 3

    print(json.dumps({
        "archive_date": expected,
        "url": url,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "team_rows": len(rows),
        "evidence_state": "verified-by-pull",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
