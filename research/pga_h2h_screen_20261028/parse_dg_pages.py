#!/usr/bin/env python3
"""Parse the embedded reload_data JSON from pulled DataGolf past-results
pages and summarize coverage: identity match, rows, outright odds coverage,
per-round SG presence. Stdlib only."""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(BASE, "pulls", "dg_pages")
MANIFEST = os.path.join(BASE, "pulls", "dg_pages_manifest.json")

MARKER = "var reload_data = JSON.parse('"


def extract_reload(html: str):
    i = html.find(MARKER)
    if i < 0:
        return None
    start = i + len(MARKER)
    end = html.find("')", start)
    if end < 0:
        return None
    raw = html[start:end]
    txt = raw.encode("utf-8").decode("unicode_escape")
    return json.loads(txt)


def main() -> int:
    with open(MANIFEST) as f:
        manifest = json.load(f)
    out = []
    for key, rec in sorted(manifest.items()):
        if rec.get("http") != 200:
            continue
        path = os.path.join(PAGES, rec["file"])
        with open(path, encoding="utf-8", errors="replace") as f:
            html = f.read()
        data = extract_reload(html)
        _, eid, year = key.split("/")
        row = {"key": key, "req_event": int(eid), "req_year": int(year)}
        if data is None:
            row["parse"] = "NO_RELOAD_DATA"
            out.append(row)
            continue
        info = data.get("info", {})
        lb = data.get("lb", [])
        row.update(
            {
                "parse": "OK",
                "info_event_id": info.get("event_id"),
                "info_year": info.get("calendar_year"),
                "season": info.get("season"),
                "date": info.get("date"),
                "name": info.get("display_name"),
                "num_rounds": info.get("num_rounds"),
                "rows": len(lb),
                "identity_match": str(info.get("event_id")) == eid
                and info.get("calendar_year") == int(year),
            }
        )
        if lb:
            has_close = sum(1 for r in lb if r.get("close") not in (-9999.0, None))
            has_open = sum(1 for r in lb if r.get("open") not in (-9999.0, None))
            has_sg = sum(
                1
                for r in lb
                if all(r.get(f"R{k}_sg") is not None for k in range(1, 5))
            )
            has_scores = sum(
                1 for r in lb if all(r.get(f"R{k}") is not None for k in range(1, 3))
            )
            row.update(
                {
                    "rows_with_close": has_close,
                    "rows_with_open": has_open,
                    "rows_with_4r_sg": has_sg,
                    "rows_with_r1r2_scores": has_scores,
                }
            )
        out.append(row)
    dest = os.path.join(BASE, "pulls", "dg_pages_coverage.json")
    with open(dest, "w") as f:
        json.dump(out, f, indent=1)
    ok = [r for r in out if r.get("parse") == "OK"]
    matched = [r for r in ok if r.get("identity_match")]
    print(f"pages 200: {len(out)}; parsed OK: {len(ok)}; identity-matched: {len(matched)}")
    for season in (2021, 2022, 2023, 2024, 2025, 2020):
        ev = [r for r in matched if r.get("season") == season]
        if not ev:
            continue
        rows = sum(r["rows"] for r in ev)
        wc = sum(r.get("rows_with_close", 0) for r in ev)
        print(
            f"season {season}: events {len(ev)} rows {rows} rows_with_close {wc} "
            f"({(100.0 * wc / rows if rows else 0):.1f}%)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
