"""Test helper: write a pinned capture-receipt store for synthetic rows.

Mirrors what a live capture adapter must persist: the raw sportsbook read
bytes, a receipt bound to them by SHA-256, and a manifest whose SHA-256 is
pinned through an independent channel. Test data only.
"""
import hashlib
import json
import tempfile
from pathlib import Path

OFFER_FIELDS = ("game_id", "book", "market", "selection", "period", "line", "player")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def write_store(rows, root=None):
    root = Path(root or tempfile.mkdtemp(prefix="capture-receipts-"))
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "receipts").mkdir(exist_ok=True)
    entries, seen = [], set()
    for r in rows:
        ver = r.get("verification")
        if not isinstance(ver, dict) or not ver.get("read_id"):
            continue
        rid = str(ver["read_id"])
        if rid in seen:
            continue
        ts = str(r.get("quote_captured_at") or "")
        if not (ts.endswith("Z") or "+" in ts[10:] or "-" in ts[10:]):
            continue  # a capture adapter cannot receipt a timezone-less read
        seen.add(rid)
        offer = {k: r.get(k) for k in OFFER_FIELDS}
        offer["price"] = r.get("price", r.get("odds"))
        raw = json.dumps({"book": r.get("book"), "read_id": rid,
                          "captured_at": r.get("quote_captured_at"), "offers": [offer]},
                         sort_keys=True).encode()
        raw_path = f"raw/{rid}.json"
        (root / raw_path).write_bytes(raw)
        receipt = {**offer, "receipt_id": "rc-" + rid, "read_id": rid,
                   "captured_at": r.get("quote_captured_at"),
                   "raw_path": raw_path, "raw_sha256": _sha(raw)}
        rb = json.dumps(receipt, sort_keys=True).encode()
        rpath = f"receipts/{rid}.json"
        (root / rpath).write_bytes(rb)
        entries.append({"receipt_id": receipt["receipt_id"], "path": rpath, "sha256": _sha(rb)})
    mb = json.dumps({"schema": "SPORTSEDGE_CAPTURE_RECEIPTS_V1", "receipts": entries},
                    sort_keys=True).encode()
    (root / "manifest.json").write_bytes(mb)
    return root, _sha(mb)


def receipts_for(rows):
    """Load a pinned store and stamp each row's verification with the raw-read
    hash its receipt binds (what a live capture adapter records at read time)."""
    from sportsedge.capture_preflight import load_capture_receipts
    root, pin = write_store(rows)
    rc = load_capture_receipts(root, manifest_sha256=pin)
    for r in rows:
        ver = r.get("verification")
        if isinstance(ver, dict) and str(ver.get("read_id")) in rc:
            ver.setdefault("raw_sha256", rc[str(ver["read_id"])]["raw_sha256"])
    return rc
