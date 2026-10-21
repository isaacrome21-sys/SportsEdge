# OddsPapi MLB V8 archived-payload resume integrity — DRAFT build report

**Base main at branch creation:** `4a1fbaf63951434d020c678a69538eb95e3a5d89`  
**Branch:** `fix/oddspapi-archive-resume-hash-check-20261020`  
**Classification:** Repair existing historical raw archive durability; research/source storage only, **not** a market source admission verdict.

## Concrete existing defect and corrective logic

Existing `scripts/backfill_mlb_v8_oddspapi.py` wrote exact provider response bytes plus a SHA-256 metadata sidecar, but its **resume** route:
- Reused cached fixture response if the JSON path alone existed, without reading/checking the associated metadata/SHA;
- Skipped `history_completed` historical files solely if both paths existed; bytes could change after download without detection;
- Could re-fetch/rewrite a complete raw history file when the raw+meta bytes had survived a crash but the progress-state entry had not;
- Could replace missing/partial archived state silently with a network fetch.

The new `_verified_cached_raw` only accepts cached byte payload when *both* raw file and metadata exist, metadata is valid JSON, `source`, exact endpoint, original secret-free request parameters, raw-byte `payload_sha256` and byte length match. Any half-written/tampered/metadata-missing pair fails with a stable source-safe error code, **before making another provider request**. If the raw+metadata pair is intact but `history_completed` was lost on crash, the state is repaired from the immutable intact evidence and no second API request is made. If a completed record lacks both files, it refuses instead of redownloading. If raw fixture/history JSON has matching hash sidecar but invalid content/fixture identity, it refuses.

The hash is an **internal storage-integrity check**, *not independent authentication* of provider, bookmaker, market, quote, game start, B numeric SBR thresholds, or source completeness. It cannot make OddsPapi data ADMITTED. Existing freeze contracts, credential handling, network routing, quota parameters, HTTP request logic, selectors, pricing, and governance are not altered.

## Changed files / exact initial Git blobs (SHA-1)

- Existing `scripts/backfill_mlb_v8_oddspapi.py` patched on isolated branch, new blob `d15f6f6cc9abc133172cf59b7efd2424078e0f55`.
- New `tests/test_oddspapi_archive_resume_integrity.py` 13 authored pytest function definitions (with parameterizations), blob `091d46aeb9bd5b39c5afae93dd4d3c1119479499`.
- This document.

Test design: synthetic in-memory provider envelope and intercepted `_request`; **no network, paid calls or credentials**. Covers clean first archive + no-replay resume; valid-JSON fixture/history tampering while keeping old SHA; deleted raw or metadata; mismatched sidecar bytes/source/endpoint/parameters; invalid metadata JSON; crash between durable bytes and state registration; state marked complete with missing *both* files; source fixture ID mismatch despite recomputed sidecar; corrupt cached fixture JSON despite recomputed sidecar; source-storage outcome never being an admitted price.

**Execution honesty:** tests are authored, but the builder has not independently executed them against the exact branch through a Python runtime. Host-required CI may not invoke the new test file; reviewer must run **`python -m pytest tests/test_oddspapi_archive_resume_integrity.py -q`**, plus existing collector self-test / regression and base comparison. Do not treat green unrelated CI as these tests' result.

## Safety / operation

This change intentionally fails CLOSED rather than mutating an existing archive on mismatch. An interrupted write that persisted only raw or only sidecar now requires manual evidence reconciliation, not silent destructive retry. No forced redownload, no hash forgery, no source-label reassignment, no hidden source admission, no new budget spending.

## Coordination

- Claimed exclusively by ChatGPT in issue #2447, while Grok tracks frozen Check B SBR numeric thresholds and Rocky independently reviews/merges existing work.
- Merge sequence #2435 → #2434 → #2438 untouched. #2436 structural parser and #2446 A/D numeric dry-run untouched.
- Owner authorized ChatGPT for **mechanical merging** only after a genuinely independent Rocky/other verifier provides an explicit exact-PR exact-head approval, current-head required CI green and branch protection; never self-approve this PR.
- Rocky independently verify file diff, synthetic adversarial behavior, library source tags, exact-head CI and approval. If it needs rebase for moved main, preserve the reviewed diff and re-run CI before merge.
