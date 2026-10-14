"""Bind an anchor payload's storage location and carrier into the leaf the TSA layer stamps.

Coordination (#2219, #2218): Muse's ``sportsedge/mlb_receipt_anchor_publisher.py`` (registry
``MLB_RECEIPT_JOURNAL_ANCHOR_V1``) reportedly derives ``anchor_id`` from the payload alone,
so the same id can be presented from any storage location or by any carrier.  The dual-TSA
layer (the RFC 3161 anchor module) stamps ``batch_root(leaves)`` where each leaf is a
lowercase 64-hex SHA-256.  Any payload digest can therefore be stamped as-is; this module
adds an optional, domain-separated *bound leaf* so a TSA token also commits to where the
payload lives and how it was carried.  It does not replace or re-encode the payload, and it
creates no parallel envelope: the publisher's payload digest is an input, unchanged.

Code only.  No network, no activation, no admission authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

BINDING_DOMAIN = "SPORTSEDGE_ANCHOR_LEAF_BINDING_V1"
KNOWN_SCHEMAS = frozenset({"MLB_RECEIPT_JOURNAL_ANCHOR_V1"})
KNOWN_CARRIERS = frozenset({"RFC3161_TSA", "OPENTIMESTAMPS", "GIT_RECORDS_BRANCH", "S3_OBJECT_LOCK"})

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Location must be a canonical URI-like string: scheme://authority/path, no whitespace,
# no query/fragment, no dot segments, no trailing slash.
_LOCATION = re.compile(r"^(s3|git|https|file)://[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-~@:+=,]+)+$")


class BindingError(ValueError):
    pass


@dataclass(frozen=True)
class BoundLeaf:
    schema: str
    payload_sha256: str
    location: str
    carrier: str
    leaf: str           # hex SHA-256 to pass to the anchor module's batch_root

    def as_record(self) -> dict:
        return {"domain": BINDING_DOMAIN, "schema": self.schema,
                "payload_sha256": self.payload_sha256, "location": self.location,
                "carrier": self.carrier, "leaf": self.leaf}


def _canon(schema: str, payload_sha256: str, location: str, carrier: str) -> bytes:
    return json.dumps({"carrier": carrier, "domain": BINDING_DOMAIN, "location": location,
                       "payload_sha256": payload_sha256, "schema": schema},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _check(schema, payload_sha256, location, carrier) -> None:
    if schema not in KNOWN_SCHEMAS:
        raise BindingError(f"UNKNOWN_SCHEMA:{schema!r}")
    if not isinstance(payload_sha256, str) or not _HEX64.match(payload_sha256):
        raise BindingError("PAYLOAD_DIGEST_NOT_LOWER_HEX64")
    if not isinstance(location, str) or not _LOCATION.match(location) or "/./" in location \
            or "/../" in location or location.endswith(("/.", "/..")):
        raise BindingError("LOCATION_NOT_CANONICAL")
    if carrier not in KNOWN_CARRIERS:
        raise BindingError(f"UNKNOWN_CARRIER:{carrier!r}")


def bind_leaf(*, schema: str, payload_sha256: str, location: str, carrier: str) -> BoundLeaf:
    """Return the domain-separated leaf committing payload digest + location + carrier."""
    _check(schema, payload_sha256, location, carrier)
    leaf = hashlib.sha256(_canon(schema, payload_sha256, location, carrier)).hexdigest()
    return BoundLeaf(schema, payload_sha256, location, carrier, leaf)


def verify_bound_leaf(record: dict, *, expected_payload_sha256: str, observed_location: str,
                      observed_carrier: str) -> tuple[bool, str]:
    """Fail-closed check that a stamped leaf matches what was actually fetched, where, and how."""
    try:
        if not isinstance(record, dict) or record.get("domain") != BINDING_DOMAIN:
            return False, "WRONG_DOMAIN"
        rebuilt = bind_leaf(schema=record.get("schema"), payload_sha256=record.get("payload_sha256"),
                            location=record.get("location"), carrier=record.get("carrier"))
    except BindingError as e:
        return False, str(e)
    if rebuilt.leaf != record.get("leaf"):
        return False, "LEAF_MISMATCH"
    if rebuilt.payload_sha256 != expected_payload_sha256:
        return False, "PAYLOAD_MISMATCH"
    if rebuilt.location != observed_location:
        return False, "LOCATION_MISMATCH"
    if rebuilt.carrier != observed_carrier:
        return False, "CARRIER_MISMATCH"
    return True, "OK"
