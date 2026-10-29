#!/usr/bin/env python3
"""Extract the content the PGA H2H design actually consumes from the
hash-pinned DataGolf past-results pull store (PR #2886) and pin that
EXTRACTED CONTENT, per event — the G-PGA-2 content-level pin.

Why content, not page bytes: Amendment 1 (PR #2896) §6 records that page
bytes drift between pulls (a fresh 36-page re-pull matched 0/36 byte
pins) while the extracted `reload_data` content is identical. The
governed admission must therefore pin the extracted content. This
extractor is the extraction of record for that pin:

  * every source page is re-hashed against the #2886 raw manifest
    (dg_pages_manifest.json) before its content is read — a page that
    does not reproduce its raw pin aborts the whole extraction;
  * the corpus universe is the IDENTITY-MATCHED subset: a page enters
    only if its embedded (event_id, calendar_year) equals the request
    key it was pulled under (the universe definition whose counts the
    Amendment 1 census measured: 157 events, 19,630 rows, owgr_rank
    valid on 16,567 rows = 84.4%); events are deduped on the composite
    (event_id, date) key per design §5;
  * each event's content is serialized in a canonical form (JSON, keys
    sorted, compact separators, ASCII-escaped, one trailing newline)
    and sha256-pinned in content_manifest.json, together with a corpus
    hash over the per-event pins.

Extracted fields are exactly the fields the design consumes, plus the
two fields Amendment 1 set aside, carried under an "excluded" object so
the exclusion is auditable in the pinned bytes themselves:
  consumed  — per-round score/par/SG (rounds present only), finish,
              total, outright open/close, owgr_rank, player identity;
  excluded  — dg_pts (DISQUALIFIED by Amendment 1 §3.1: an outcome of
              the event, not a rating — using it would be lookahead)
              and dg_rank (DataGolf's proprietary ordering; the design's
              reference (b) role belongs to the official ranking).
Source values are preserved as published, sentinels included
(-9999 / -9998); validity rules belong to consumers, not extraction.

Determinism: the extractor emits no timestamps and no host-dependent
values; two runs over the same store produce byte-identical files and
an identical manifest. verify_content_pins.py proves it.

Stdlib only.
Usage: extract_dg_content.py --store <pulls_dir> --out <extracted_dir>
       [--raw-manifest <path to dg_pages_manifest.json>]
Exit 0 on success; 1 on any pin/parse failure (nothing is written to
the manifest in that case).
"""
import argparse
import hashlib
import json
import os
import sys

EXTRACTOR_VERSION = "PGA_DG_CONTENT_EXTRACT_V1"
MARKER = "var reload_data = JSON.parse('"

CONSUMED_ROW_KEYS = (
    "dg_id",
    "player_name",
    "fin",
    "total",
    "rounds",
    "open",
    "close",
    "owgr_rank",
    "excluded",
)


def canonical_bytes(obj) -> bytes:
    """The canonical serialization every content pin is taken over."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def content_sha256(obj) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def extract_reload(html: str):
    """The established #2886 extraction of the embedded reload_data JSON."""
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


def build_row(lb_row: dict) -> dict:
    """Map one source leaderboard row to its extracted content record."""
    rounds = []
    for r in range(1, 5):
        score = lb_row.get(f"R{r}")
        sg = lb_row.get(f"R{r}_sg")
        if score is None and sg is None:
            continue  # round not played (e.g. R3/R4 for a missed cut)
        rounds.append(
            {"r": r, "score": score, "par": lb_row.get(f"R{r}_par"), "sg": sg}
        )
    return {
        "dg_id": lb_row.get("dg_id"),
        "player_name": lb_row.get("player_name"),
        "fin": lb_row.get("fin"),
        "total": lb_row.get("total"),
        "rounds": rounds,
        "open": lb_row.get("open"),
        "close": lb_row.get("close"),
        "owgr_rank": lb_row.get("owgr_rank"),
        "excluded": {
            "dg_pts": lb_row.get("dg_pts"),
            "dg_rank": lb_row.get("dg_rank"),
        },
    }


def build_event_content(info: dict, lb: list, source_page: dict) -> dict:
    """Build one event's canonical content record from its page payload."""
    return {
        "event_id": str(info.get("event_id")),
        "calendar_year": info.get("calendar_year"),
        "season": info.get("season"),
        "date": info.get("date"),
        "name": info.get("display_name"),
        "tour": info.get("tour"),
        "num_rounds": info.get("num_rounds"),
        "source_pages": [source_page],
        "rows": [build_row(r) for r in lb],
    }


def corpus_hash(event_entries: list) -> str:
    """sha256 over 'event_id|date|content_sha256' lines, events sorted
    by (date, event_id). The corpus pin of record."""
    lines = []
    for e in sorted(event_entries, key=lambda x: (x["date"], x["event_id"])):
        lines.append(f"{e['event_id']}|{e['date']}|{e['content_sha256']}")
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def extract_corpus(store_dir: str, raw_manifest: dict):
    """Verify raw pins and extract the identity-matched corpus.

    Returns (events, stats) where events maps (event_id, date) ->
    content dict. Raises ValueError on any integrity failure."""
    pages_dir = os.path.join(store_dir, "dg_pages")
    events = {}
    stats = {
        "raw_pages": 0,
        "raw_pages_reverified": 0,
        "pages_parsed": 0,
        "pages_identity_matched": 0,
        "pages_identity_mismatched": 0,
        "pages_no_reload_data": 0,
    }
    for key in sorted(raw_manifest):
        rec = raw_manifest[key]
        if rec.get("http") != 200:
            continue
        stats["raw_pages"] += 1
        path = os.path.join(pages_dir, rec["file"])
        if not os.path.exists(path):
            raise ValueError(f"pull store missing page file for {key}: {rec['file']}")
        with open(path, "rb") as f:
            body = f.read()
        digest = hashlib.sha256(body).hexdigest()
        if digest != rec["sha256"]:
            raise ValueError(
                f"raw pin mismatch for {key}: store sha256 {digest} "
                f"!= manifest {rec['sha256']}"
            )
        stats["raw_pages_reverified"] += 1
        data = extract_reload(body.decode("utf-8", errors="replace"))
        if data is None:
            stats["pages_no_reload_data"] += 1
            continue
        stats["pages_parsed"] += 1
        info = data.get("info", {})
        _, req_eid, req_year = key.split("/")
        if str(info.get("event_id")) != req_eid or info.get(
            "calendar_year"
        ) != int(req_year):
            stats["pages_identity_mismatched"] += 1
            continue
        stats["pages_identity_matched"] += 1
        source_page = {
            "request_key": key,
            "file": rec["file"],
            "page_sha256": rec["sha256"],
        }
        content = build_event_content(info, data.get("lb", []), source_page)
        ekey = (content["event_id"], content["date"])
        if ekey in events:
            if content_sha256(events[ekey]) != content_sha256(content):
                raise ValueError(
                    f"two identity-matched pages disagree on event {ekey}"
                )
            continue
        events[ekey] = content
    return events, stats


def build_manifest(events: dict, stats: dict) -> dict:
    entries = []
    row_count = 0
    for (event_id, date), content in events.items():
        fname = f"{event_id}_{date}.json"
        entries.append(
            {
                "event_id": event_id,
                "calendar_year": content["calendar_year"],
                "season": content["season"],
                "date": date,
                "name": content["name"],
                "rows": len(content["rows"]),
                "content_file": fname,
                "content_sha256": content_sha256(content),
                "source_page_sha256": content["source_pages"][0]["page_sha256"],
            }
        )
        row_count += len(content["rows"])
    entries.sort(key=lambda x: (x["date"], x["event_id"]))
    return {
        "packet": "pga_datagolf_content_admission_20261028",
        "status": "DRAFT — NOT ADMITTED",
        "scope": (
            "PGA H2H design-screen use only (family PGA / "
            "TOURNAMENT_MATCHUPS_72H, Leg 1 historical calibration screen)"
        ),
        "extractor_version": EXTRACTOR_VERSION,
        "canonical_form": (
            "JSON, keys sorted, separators (',',':'), ensure_ascii, "
            "one trailing newline; sha256 over the UTF-8 bytes"
        ),
        "universe_rule": (
            "identity-matched pages only (embedded event_id and "
            "calendar_year equal the pull request key), deduped on the "
            "composite (event_id, date) key"
        ),
        "raw_source": {
            "manifest": "research/pga_h2h_screen_20261028/dg_pages_manifest.json",
            "pages": stats["raw_pages"],
            "pages_reverified_against_raw_pins": stats["raw_pages_reverified"],
            "pages_parsed": stats["pages_parsed"],
            "pages_identity_matched": stats["pages_identity_matched"],
            "pages_identity_mismatched": stats["pages_identity_mismatched"],
            "pages_no_reload_data": stats["pages_no_reload_data"],
        },
        "event_count": len(entries),
        "row_count": row_count,
        "corpus_sha256": corpus_hash(entries),
        "events": entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="pull store dir (holds dg_pages/)")
    ap.add_argument("--out", required=True, help="extracted-content output dir")
    ap.add_argument(
        "--raw-manifest",
        default=None,
        help="path to dg_pages_manifest.json (default: the #2886 packet's, "
        "resolved relative to this script's repo)",
    )
    args = ap.parse_args()

    raw_manifest_path = args.raw_manifest
    if raw_manifest_path is None:
        repo = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        raw_manifest_path = os.path.join(
            repo, "research", "pga_h2h_screen_20261028", "dg_pages_manifest.json"
        )
    with open(raw_manifest_path) as f:
        raw_manifest = json.load(f)

    try:
        events, stats = extract_corpus(args.store, raw_manifest)
    except ValueError as e:
        print(f"EXTRACTION ABORTED: {e}", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    for (event_id, date), content in sorted(
        events.items(), key=lambda kv: (kv[0][1], kv[0][0])
    ):
        fname = f"{event_id}_{date}.json"
        with open(os.path.join(args.out, fname), "wb") as f:
            f.write(canonical_bytes(content))

    manifest = build_manifest(events, stats)
    with open(os.path.join(args.out, "content_manifest.json"), "wb") as f:
        f.write(canonical_bytes(manifest))

    print(f"raw pages reverified: {stats['raw_pages_reverified']}/{stats['raw_pages']}")
    print(f"identity-matched pages: {stats['pages_identity_matched']}")
    print(f"events extracted: {manifest['event_count']}")
    print(f"rows extracted: {manifest['row_count']}")
    print(f"corpus_sha256: {manifest['corpus_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
