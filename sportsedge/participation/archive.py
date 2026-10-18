"""Append-only participation archive.

Implements the integrity rules of the foundation doc section 6.3:

- Raw payloads are stored BEFORE normalization, content-addressed by
  SHA-256, and are immutable once written.
- Parsed records are appended to per-signal JSONL files. Existing bytes
  are never modified: a correction is a new record that supersedes the
  old one via ``supersedes_record_id``.
- Every collector run writes a receipt (what was fetched, when, from
  where, row counts, raw payload SHA, and fail-closed rejection counts).

Layout under the archive root::

    raw/<sha256>.csv            immutable raw payloads
    records/<signal_type>.jsonl append-only parsed records
    receipts.jsonl              append-only collector receipts
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schema import ParticipationRecord, iso_z, validate_record


def _now_iso() -> str:
    return iso_z(datetime.now(timezone.utc))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ParticipationArchive:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.records_dir = self.root / "records"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.receipts_path = self.root / "receipts.jsonl"

    # -- raw payloads -------------------------------------------------------
    def store_raw_payload(self, data: bytes, suffix: str = ".csv") -> tuple[str, str]:
        """Store a raw payload immutably. Returns (sha256, relative_ref).

        If the payload already exists (identical bytes), the existing file
        is left untouched and its ref returned -- content addressing makes
        re-storage a no-op, never a rewrite.
        """
        digest = sha256_bytes(data)
        ref = f"raw/{digest}{suffix}"
        path = self.root / ref
        if not path.exists():
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        return digest, ref

    def read_raw_payload(self, ref: str) -> bytes:
        return (self.root / ref).read_bytes()

    # -- records ------------------------------------------------------------
    def _records_path(self, signal_type: str) -> Path:
        return self.records_dir / f"{signal_type}.jsonl"

    def append_record(self, rec: ParticipationRecord) -> str:
        """Validate and append one record. Returns the assigned record_id.

        Supersede semantics: if ``rec.supersedes_record_id`` names an
        existing record, the new record is appended and the old one remains
        byte-identical in the file; readers resolve the chain.
        """
        validate_record(rec)
        if rec.record_id is None:
            rec.record_id = uuid.uuid4().hex
        line = json.dumps(rec.to_dict(), sort_keys=True, separators=(",", ":"))
        path = self._records_path(rec.signal_type)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return rec.record_id

    def append_records(self, records) -> int:
        """Batch append (one file handle per signal). Same validation and
        append-only semantics as append_record."""
        by_signal: dict[str, list[str]] = {}
        count = 0
        for rec in records:
            validate_record(rec)
            if rec.record_id is None:
                rec.record_id = uuid.uuid4().hex
            line = json.dumps(rec.to_dict(), sort_keys=True, separators=(",", ":"))
            by_signal.setdefault(rec.signal_type, []).append(line)
            count += 1
        for signal_type, lines in by_signal.items():
            with open(self._records_path(signal_type), "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        return count

    def iter_records(self, signal_type: str | None = None):
        """Yield records in append order (all signals if not specified)."""
        if signal_type is not None:
            paths = [self._records_path(signal_type)]
        else:
            paths = sorted(self.records_dir.glob("*.jsonl"))
        for path in paths:
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield ParticipationRecord.from_dict(json.loads(line))

    def load_records(self, signal_type: str | None = None) -> list[ParticipationRecord]:
        return list(self.iter_records(signal_type))

    def current_records(self, signal_type: str | None = None) -> list[ParticipationRecord]:
        """Records with superseded versions resolved away (chain heads)."""
        records = self.load_records(signal_type)
        superseded = {
            r.supersedes_record_id for r in records if r.supersedes_record_id
        }
        return [r for r in records if r.record_id not in superseded]

    # -- receipts -----------------------------------------------------------
    def append_receipt(self, receipt: dict) -> None:
        receipt = dict(receipt)
        receipt.setdefault("receipt_id", uuid.uuid4().hex)
        receipt.setdefault("recorded_at_utc", _now_iso())
        with open(self.receipts_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt, sort_keys=True) + "\n")

    def load_receipts(self) -> list[dict]:
        if not self.receipts_path.exists():
            return []
        out = []
        with open(self.receipts_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    # -- integrity ----------------------------------------------------------
    def verify_integrity(self) -> dict:
        """Recompute raw-payload hashes and supersede-chain integrity."""
        raw_ok, raw_bad = 0, []
        for path in sorted(self.raw_dir.iterdir()):
            if path.suffix == ".tmp":
                continue
            digest = sha256_bytes(path.read_bytes())
            if digest == path.stem:
                raw_ok += 1
            else:
                raw_bad.append(path.name)
        ids: set[str] = set()
        dangling = []
        for rec in self.iter_records():
            if rec.record_id:
                ids.add(rec.record_id)
        for rec in self.iter_records():
            if rec.supersedes_record_id and rec.supersedes_record_id not in ids:
                dangling.append(rec.record_id)
        return {
            "raw_payloads_verified": raw_ok,
            "raw_payloads_hash_mismatch": raw_bad,
            "records_total": len(ids),
            "dangling_supersede_refs": dangling,
        }
