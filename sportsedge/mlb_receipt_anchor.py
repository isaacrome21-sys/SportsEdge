"""External timestamp anchor for the MLB receipt journal -- DARK implementation.

The receipt journal (:mod:`sportsedge.mlb_source`) proves *local* consistency
only: a hash chain one machine wrote and one machine re-reads. Anyone holding
the directory can rewrite the whole history and reseal the chain, and nothing
external contradicts them. An anchor closes that specific hole: the journal's
head hash is published to a GitHub records branch, and GitHub's own commit
receipt (server-side time, outside this machine's control) then proves the
head existed at or before the publication moment -- existence-by-publication-
time. That is the strongest claim this design makes, and it is deliberately
narrower than attestation:

* it does NOT prove the fetch times claimed inside individual receipts;
* it does NOT prove the journal accumulated gradually -- only a cadence of
  anchors bounds how much history could have been written at once;
* it is NOT a cryptographic signature and carries no promotion authority.

DARK / DISABLED BY DEFAULT: :data:`ANCHORING_ENABLED` is ``False`` and the
publishing entrypoint refuses while it is ``False``, even with a publisher
supplied. Preparation and verification are pure and local and change nothing.
An absent anchor is the honest ``UNANCHORED`` state, never an error.

OWNER DECISION (made Oct 13, 2026, by delegation; memo
``ANCHOR_HOST_DECISION.md``): Option A -- anchors publish to the
``records/evidence-anchors`` branch of this repository, daily roll-up
cadence, via the records-branch publisher in
:mod:`sportsedge.mlb_receipt_anchor_publisher`. The decision does NOT flip
:data:`ANCHORING_ENABLED`: that flip is a separate reviewed change, and
until it lands no code path in this module performs a real publication.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from .mlb_source import (
    GENESIS_SHA256,
    RECEIPT_JOURNAL_NAME,
    MLBSourceError,
    _trusted_now,
    verify_receipt_journal,
)

ANCHORING_ENABLED = False
ANCHOR_SCHEMA = "MLB_RECEIPT_JOURNAL_ANCHOR_V1"
ANCHOR_CLAIM = "EXISTENCE_BY_GITHUB_PUBLICATION_RECEIPT"
ANCHOR_HONEST_LIMITS = (
    "Proves only that this journal head hash existed at or before the anchor's publication receipt time.",
    "Publication time is issued by the publishing platform (GitHub), not by this machine.",
    "Does NOT prove the fetch times claimed inside individual receipts.",
    "Does NOT prove the journal accumulated gradually; only a cadence of anchors bounds rewriting.",
    "NOT a cryptographic signature or attestation; carries no promotion authority.",
)
_ANCHOR_IDENTITY_FIELDS = (
    "schema", "receipt_journal", "receipt_chain_head_sha256",
    "journal_genesis_sha256", "journal_first_sequence", "journal_last_sequence",
    "journal_entry_count", "journal_sha256",
)


class ReceiptAnchorPublisher(Protocol):
    """The publication seam. A production implementation would commit the
    payload to a records branch and return GitHub's receipt; tests supply a
    fake. Nothing in this module implements a real publisher."""

    def publish(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        """Publish ``payload`` and return a receipt mapping carrying at least
        ``anchor_id`` (echoing the payload), ``published_at_utc`` and
        ``location``."""
        ...


def _anchor_id(payload: Mapping[str, Any]) -> str:
    body = {k: payload.get(k) for k in _ANCHOR_IDENTITY_FIELDS}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def prepare_receipt_anchor(root: str | Path, *, verifier_now: datetime | None = None) -> dict[str, Any]:
    """Compute the anchor payload for the journal's current head.

    Fails closed on any journal defect (verification runs first): an anchor
    must never certify a torn or tampered journal. Pure and local -- this
    prepares a payload; it publishes nothing and changes no state.
    """
    root = Path(root)
    entries = verify_receipt_journal(root, verifier_now=verifier_now)
    if not entries:
        raise MLBSourceError("RECEIPT_ANCHOR_NO_ENTRIES")
    journal_bytes = (root / RECEIPT_JOURNAL_NAME).read_bytes()
    payload: dict[str, Any] = {
        "schema": ANCHOR_SCHEMA,
        "anchor_claim": ANCHOR_CLAIM,
        "anchored": False,
        "external_time_anchor": False,
        "receipt_journal": RECEIPT_JOURNAL_NAME,
        "receipt_chain_head_sha256": entries[-1]["record_sha256"],
        "journal_genesis_sha256": GENESIS_SHA256,
        "journal_first_sequence": entries[0]["sequence"],
        "journal_last_sequence": entries[-1]["sequence"],
        "journal_entry_count": len(entries),
        "journal_sha256": hashlib.sha256(journal_bytes).hexdigest(),
        "prepared_at_utc": _trusted_now().isoformat(),
        "prepared_clock": "PREPARER_SYSTEM_CLOCK_NOT_EVIDENCE",
        "honest_limits": list(ANCHOR_HONEST_LIMITS),
        "promotion_authority": False,
    }
    payload["anchor_id"] = _anchor_id(payload)
    return payload


def verify_receipt_anchor(root: str | Path, anchor: Mapping[str, Any] | None, *,
                          verifier_now: datetime | None = None) -> dict[str, Any]:
    """Check an anchor against the journal as it stands now.

    ``anchor=None`` is the honest UNANCHORED state and is NOT an error --
    local journal verification is unaffected either way. A present anchor
    whose identity fields no longer match the journal (extended, rewritten,
    or resealed) is refused by field name.
    """
    if anchor is None:
        return {"anchor_status": "UNANCHORED", "external_time_anchor": False}
    expected = prepare_receipt_anchor(root, verifier_now=verifier_now)
    for field in _ANCHOR_IDENTITY_FIELDS + ("anchor_id",):
        if anchor.get(field) != expected[field]:
            raise MLBSourceError(f"RECEIPT_ANCHOR_MISMATCH:{field}")
    publication = anchor.get("publication")
    return {
        "anchor_status": "MATCHES_LOCAL_JOURNAL",
        "anchor_id": expected["anchor_id"],
        "external_time_anchor": bool(anchor.get("external_time_anchor")),
        "publication_receipt_present": isinstance(publication, Mapping),
    }


def publish_receipt_anchor(root: str | Path, publisher: ReceiptAnchorPublisher | None, *,
                           verifier_now: datetime | None = None) -> dict[str, Any]:
    """Publish a prepared anchor through ``publisher`` -- DISABLED BY DEFAULT.

    Refuses while :data:`ANCHORING_ENABLED` is False (the standing state;
    the Option A target/cadence decision exists but the enablement flip is
    a separate reviewed change), and refuses
    without an explicit publisher. A publication attempt that errors, or a
    receipt that does not echo the payload's anchor id, never produces an
    object claiming to be anchored.
    """
    if not ANCHORING_ENABLED:
        raise MLBSourceError("RECEIPT_ANCHORING_DISABLED")
    if publisher is None:
        raise MLBSourceError("RECEIPT_ANCHOR_PUBLISHER_REQUIRED")
    payload = prepare_receipt_anchor(root, verifier_now=verifier_now)
    receipt = publisher.publish(payload)
    if not isinstance(receipt, Mapping) or receipt.get("anchor_id") != payload["anchor_id"]:
        raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_RECEIPT_INVALID")
    return {
        **payload,
        "anchored": True,
        "external_time_anchor": True,
        "publication": dict(receipt),
    }
