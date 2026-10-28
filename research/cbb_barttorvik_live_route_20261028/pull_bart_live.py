#!/usr/bin/env python3
"""Pinned retrieval for the LIVE BartTorvik T-Rank season file (DESIGN only).

Fetches ``https://barttorvik.com/{year}_team_results.csv`` — the exact file
that hoopR's ``torvik_ratings()`` reads (verified in hoopR source:
``.torvik_text(paste0("/", year, "_team_results.csv"))``) — and prints a
JSON manifest entry with the SHA-256 of the exact bytes received.

Unlike the historical archive admitted in
research/cbb_barttorvik_admission_20261027 (a dead GitHub mirror pinned by
commit), this route is a LIVING file: barttorvik.com regenerates it as the
season progresses. The pin is therefore the PULL, not a commit: each pull
is timestamped, hash-pinned, and treated as the snapshot of record for the
America/Chicago date on which it was taken. The morning-of rule in the
admission record shipped with this script
(research/cbb_barttorvik_live_route_20261028/ADMISSION_RECORD.md) makes the
morning pull — taken before that day's first tip — the only admitted
vintage for that date. A later re-pull whose hash differs is a DIFFERENT
vintage, never a silent replacement (SOURCE_CHANGED_AFTER_SNAPSHOT).

Stdlib only. Usage:
    python3 pull_bart_live.py 2027 [--expect-sha256 HEX]
Exit codes: 0 ok, 2 SOURCE_UNAVAILABLE / SEASON_NOT_PUBLISHED,
3 SCHEMA_INVALID / SOURCE_CHANGED_AFTER_SNAPSHOT.
"""

import csv
import hashlib
import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

URL_PATTERN = "https://barttorvik.com/{year}_team_results.csv"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUIRED_COLUMNS = {"rank", "team", "conf", "record", "adjoe", "adjde", "barthag"}
RECORD_RE = re.compile(r"^\d+-\d+$")
CHICAGO = ZoneInfo("America/Chicago")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, dict(resp.headers), resp.read()


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    expect = None
    for a in argv[1:]:
        if a.startswith("--expect-sha256="):
            expect = a.split("=", 1)[1].strip().lower()
    if len(args) != 1 or len(args[0]) != 4 or not args[0].isdigit():
        print("usage: pull_bart_live.py YYYY [--expect-sha256=HEX]", file=sys.stderr)
        return 2
    year = args[0]
    url = URL_PATTERN.format(year=year)
    try:
        status, headers, raw = fetch(url)
    except urllib.error.HTTPError as exc:
        refusal = "SEASON_NOT_PUBLISHED" if exc.code == 404 else "SOURCE_UNAVAILABLE"
        print(json.dumps({"refusal": refusal, "http_status": exc.code, "url": url}))
        return 2
    except urllib.error.URLError as exc:
        print(json.dumps({"refusal": "SOURCE_UNAVAILABLE", "error": str(exc.reason), "url": url}))
        return 2

    pulled_at = datetime.now(timezone.utc)
    digest = hashlib.sha256(raw).hexdigest()
    if expect is not None and digest != expect:
        print(json.dumps({
            "refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
            "expected_sha256": expect,
            "actual_sha256": digest,
            "url": url,
        }))
        return 3

    text = raw.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or not REQUIRED_COLUMNS.issubset(set(rows[0].keys())):
        print(json.dumps({"refusal": "SCHEMA_INVALID", "url": url}))
        return 3
    try:
        for row in rows:
            if not RECORD_RE.match(row["record"].strip()):
                raise ValueError("record")
            barthag = float(row["barthag"])
            if not 0.0 < barthag < 1.0:
                raise ValueError("barthag")
    except (ValueError, KeyError, AttributeError):
        print(json.dumps({"refusal": "SCHEMA_INVALID", "url": url}))
        return 3
    if not 300 <= len(rows) <= 400:
        print(json.dumps({"refusal": "SCHEMA_INVALID", "team_rows": len(rows), "url": url}))
        return 3

    games_played = sum(
        sum(int(part) for part in row["record"].split("-")) for row in rows
    )
    print(json.dumps({
        "season_year": int(year),
        "url": url,
        "http_status": status,
        "pulled_at_utc": pulled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of_local_date": pulled_at.astimezone(CHICAGO).strftime("%Y-%m-%d"),
        "as_of_timezone": "America/Chicago",
        "site_last_modified_utc": headers.get("Last-Modified"),
        "site_date_utc": headers.get("Date"),
        "etag": headers.get("ETag"),
        "bytes": len(raw),
        "sha256": digest,
        "team_rows": len(rows),
        "games_played_total": games_played,
        "evidence_state": "verified-by-pull",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
