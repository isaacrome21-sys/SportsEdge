"""One-time AUDIT: download a Kaggle dataset to a temp dir and emit ONLY a
schema/coverage/provenance report (no raw rows). Credentials come from env only and
are never printed. Research audit; grants no market-baseline status."""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections import Counter

API = "https://www.kaggle.com/api/v1"
PRICE = re.compile(r"(ml|moneyline|juice|odds|price|vig)", re.I)
TIME = re.compile(r"(time|timestamp|updated|captured|open|close|clos)", re.I)
BOOK = re.compile(r"(book|sportsbook|source|vendor)", re.I)
SCORE = re.compile(r"(score|pts|points|result|final|winner|cover)", re.I)
DATE = re.compile(r"(date|season)", re.I)


def _auth() -> str:
    u, k = os.environ.get("SPORTSEDGE_KAGGLE_USERNAME"), os.environ.get("SPORTSEDGE_KAGGLE_KEY")
    if not u or not k:
        raise SystemExit("KAGGLE_CREDENTIALS_MISSING")
    return "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()


def _get(url: str, auth: str) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": auth, "User-Agent": "sportsedge-audit"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:  # never include headers/credentials
        raise SystemExit(f"KAGGLE_HTTP_{e.code}") from None


def profile_csv(name: str, text: str, max_uniques: int = 25) -> dict:
    rows = list(csv.DictReader(io.StringIO(text)))
    cols = list(rows[0].keys()) if rows else []
    n = len(rows)
    out = {"file": name, "rows": n, "columns": cols, "null_rate": {}, "kinds": {}, "samples_distinct": {}}
    for c in cols:
        vals = [(r.get(c) or "").strip() for r in rows]
        empty = sum(1 for v in vals if v == "" or v.lower() in {"nan", "na", "null", "none"})
        out["null_rate"][c] = round(empty / n, 4) if n else None
        kinds = [k for k, rx in (("price", PRICE), ("time_or_open_close", TIME), ("book", BOOK),
                                 ("settlement_score", SCORE), ("date_or_season", DATE)) if rx.search(c)]
        out["kinds"][c] = kinds
        if "book" in kinds or c.lower() in {"season", "playoffs", "type", "regular"}:
            out["samples_distinct"][c] = Counter(vals).most_common(max_uniques)
    datecol = next((c for c in cols if c.lower() in {"date", "game_date"}), None)
    if datecol:
        ds = sorted(v for v in ((r.get(datecol) or "").strip() for r in rows) if v)
        out["date_range"] = [ds[0], ds[-1]] if ds else None
    seascol = next((c for c in cols if c.lower() == "season"), None)
    if seascol:
        out["rows_per_season"] = dict(sorted(Counter((r.get(seascol) or "").strip() for r in rows).items()))
    pc = [c for c in cols if "price" in out["kinds"][c]]
    out["price_columns"] = pc
    out["two_sided_hint"] = {
        "moneyline": sum(bool(re.search(r"ml|moneyline", c, re.I)) for c in pc) >= 2,
        "spread_prices": sum(bool(re.search(r"spread", c, re.I)) for c in pc) >= 2,
        "total_prices": sum(bool(re.search(r"over|under|total", c, re.I)) for c in pc) >= 2,
    }
    out["timestamp_columns"] = [c for c in cols if "time_or_open_close" in out["kinds"][c]]
    out["book_columns"] = [c for c in cols if "book" in out["kinds"][c]]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    auth = _auth()
    owner, slug = a.dataset.split("/")
    meta = {}
    try:
        meta = json.loads(_get(f"{API}/datasets/view/{owner}/{slug}", auth))
    except SystemExit as e:
        meta = {"error": str(e)}
    keep = ("title", "subtitle", "licenseName", "lastUpdated", "currentVersionNumber", "totalBytes",
            "description", "ownerRef", "url", "usabilityRating")
    report = {"schema": "KAGGLE_DATASET_AUDIT_REPORT_V1", "dataset": a.dataset,
              "metadata": {k: meta.get(k) for k in keep if k in meta} | ({"error": meta["error"]} if "error" in meta else {}),
              "files": [], "raw_data_committed": False, "market_baseline": "MISSING_UNTIL_DK_PAIRING_AND_TIMING_VERIFIED"}
    with tempfile.TemporaryDirectory() as td:
        blob = _get(f"{API}/datasets/download/{owner}/{slug}", auth)
        report["download_bytes"] = len(blob)
        import hashlib
        report["download_sha256"] = hashlib.sha256(blob).hexdigest()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            report["archive_members"] = [{"name": i.filename, "bytes": i.file_size} for i in z.infolist()]
            for i in z.infolist():
                if i.filename.lower().endswith(".csv"):
                    report["files"].append(profile_csv(i.filename, z.read(i).decode("utf-8", "replace")))
    with open(a.out, "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    # Print the report (schema/coverage only; contains no credentials or raw rows).
    print(json.dumps(report, indent=1, default=str)[:60000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
