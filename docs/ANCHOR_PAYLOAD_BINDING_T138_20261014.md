# Anchor payload binding: MLB_RECEIPT_JOURNAL_ANCHOR_V1 x dual-TSA (t138, Grok lane, #2219)

Status: CODE/REVIEW ONLY. Capture OFF, admission OFF, DigiCert unpinned. No activation authority.

## Compatibility finding
- The TSA layer (`sportsedge/evidence_anchor.py`, t130 @ 48bf3351) stamps `batch_root(leaves)`,
  where each leaf is any lowercase 64-hex SHA-256. RFC 3161 requests carry only that root as the
  message imprint (+ nonce). So a TSA token can stamp the publisher's payload digest unchanged:
  the two layers compose; no parallel envelope is needed.
- `sportsedge/mlb_receipt_anchor_publisher.py` (Muse, local anchor-port commit `035f0db64`) is
  NOT on the remote as of 2026-10-14 ~05:30 CT (no branch, no code-search hit). The schema has
  not been read here; everything below is against the reported contract (anchor_id over the
  payload only, location/carrier not bound). Re-check on the exact pushed SHA.

## Gap
If `anchor_id` binds only the payload, a TSA token over it proves the bytes existed by time T,
not where they were stored or how they were carried. A copy at another location, or the same
payload presented via a different carrier, verifies identically.

## Proposal (this branch: `sportsedge/anchor_payload_binding.py`)
leaf = SHA-256( canonical JSON {carrier, domain="SPORTSEDGE_ANCHOR_LEAF_BINDING_V1", location,
payload_sha256, schema} ), sorted keys, no whitespace, ASCII.
- payload_sha256 = the publisher's existing payload digest (unchanged).
- location: canonical `s3|git|https|file://authority/path`; no query/fragment, dot segments,
  trailing slash or whitespace.
- carrier in {RFC3161_TSA, OPENTIMESTAMPS, GIT_RECORDS_BRANCH, S3_OBJECT_LOCK}.
- The bound leaf goes into `batch_root` beside (or instead of) the bare payload digest.
- `verify_bound_leaf` fail-closes on WRONG_DOMAIN, LEAF_MISMATCH, PAYLOAD_MISMATCH,
  LOCATION_MISMATCH, CARRIER_MISMATCH and any non-canonical field.
Option for Muse: set `anchor_id = bound leaf` in the publisher (one-line change in Muse's file;
not edited here), or keep `anchor_id` payload-only and stamp the bound leaf as a sibling.

## Open questions for the owner / integration
- Is S3 object version id part of location? (Currently refused as a query string; add a field
  if Object Lock version binding is wanted.)
- Registration of the two new paths in freeze reconciliation.
