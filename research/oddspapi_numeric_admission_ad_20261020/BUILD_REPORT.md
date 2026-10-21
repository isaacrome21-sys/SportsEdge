# A/D numeric admission diagnostics — DRAFT BUILD RECORD (2026-10-20 CT)

**Build branch:** `feat/oddspapi-numeric-admission-ad-20261020`  
**Base at creation:** `0cdcf7dfa3500dc6b1a0efd40f3c5b6cf3bc8cad`  
**Scope:** New additive module and synthetic tests only. **No** modification to #2436 or Rocky's merge sequence #2435 → #2434 → #2438; **no** secrets read, live calls, frozen config edits, or admission-state changes. No own-work verification.

## Motivation and governing boundary

The #2436 OddsPapi candidate parser is **structural-only**, and source admission must not be inferred from its CI or from successful provider catalog/bookmaker-auth calls. Owner/Rocky independently reported real provider HTTP 200 successes for sports and bookmaker catalogs; we did not verify these calls ourselves. The frozen `config/mlb_v8_oddspapi_evidence_contract.json` governs **MLB V8 PIT replay**, including <first-pitch paired quote synchronization and source provenance. That contract does not publish the separately requested **SBR archive Check B numeric thresholds**; do not invent those numbers or claim Check B passes.

This additive **offline** diagnostic calculates two precisely defined numeric quantities on caller-supplied (UNAUTHENTICATED) receipts:

### A: independent-DK cross-check *numeric* diagnostic

For each pre-listed independently claimed DK observation, compare one OddsPapi observation for the identical canonical event, bookmaker `draftkings`, market, and side. Compare offered line numerically with no tolerances or interpolation; convert provider decimal odds to American odds using half-up nearest integer; require absolute American-price difference **≤10** and quote time difference **≤1,800 seconds**. Missing pairing stays in the **original denominator**, never silently filtered. Compute passing rows / *all supplied rows*; exact **≥95%** passes the numerical threshold. A row with missing counterpart fails; a wrong fixture/book/side/line/time/price fails or refuses. No array count proves a cohort is complete; the manifest hash is **not independent authentication**. No claim about final actual first pitch, executable offers, two-sided bookmaker depth, or paired CLV.

### D: independently claimed actual-first-play *numeric* diagnostic

Require actual-first-play timestamp **for the exact game** and separate source SHA shape for each candidate close. For every submitted candidate close require provider quote timestamp **strictly BEFORE** the actual first play. One candidate at exact first pitch or later causes the observed valid share to be below **100%**. Missing or conflicting actual-first-play evidence fails. Neither timing checks nor hash shape prove official source authenticity; no scheduled-start fallback is accepted. Caller could omit bad candidates, so closed-world cohort completeness must be separately verified.

### B: SBR archive checks

**NOT EVALUATED.** The current branch carries **no threshold parameter** and **no mechanism that could accept caller-supplied B pass flags**. Its output explicitly reports `NOT_EVALUATED_SBR_ARCHIVE_THRESHOLDS_NOT_PINNED`, `numeric_threshold_met:false`. A later version requires a source-pinned, owner-approved, timestamped B protocol and independent verifier.

## Fail-closed output

Every code path returning a report has `status: NOT_ADMITTED_NUMERIC_DRYRUN`, `admission: NOT_ADMITTED`, `eligible:false`, `play_authority:false`, `clock_started:false`, `market_test:NOT_STARTED`; even A 100% + D 100% cannot lift B. Input flags such as `owner_approved`, `B_passed`, or `independent_source_verified` are refused. All data belongs to offline synthetic test or later explicitly supplied unverified receipts; **no actual provider or DK data used**. No source/frozen rubric/gate/registry writes.

## Exact Git blob SHA-1s

- `sportsedge/oddspapi_numeric_admission_ad.py` — `016c6fd4b9cd0a2d58dd0984c4eeb6672737c6c1`
- `tests/test_oddspapi_numeric_admission_ad.py` — `021778229ad8d8bf6736e7ced9718e1e6ef173f5`

21 authored synthetic test functions (plus parameterizations) include exact 30:00 vs 30:01, American price gap 10 vs 11, exactly 95/100 vs 94/100, missing pair in denominator, mismatched bookmaker/line/fixture, D at first pitch vs 1 second before, 99/100 D fail, missing and cross-fixture first play, duplicates, hostile unknown flags and no fake ADMITTED. **Not independently run by the author in a verified execution; hosted CI must be checked at exact head, and test runner must actually invoke new pytest tests.**

## Rocky verifier checklist and future work

1. Verify numeric bars at boundaries by independent hand-count (a ratio claim is not evidence of a complete sample); test A and D against synthetic adversarial cases, including 11-cent discrepancy, 94% cohort and post-actual-first-pitch candidate.
2. Confirm that these are **only unverified diagnostics** and can never emit ADMITTED. Check presence of exact frozen B numeric protocol; if found, independently record file+hash and owner ruling before adding B on a future branch.
3. Run targeted `python -m pytest tests/test_oddspapi_numeric_admission_ad.py -q` and hosted CI on latest head; compare failure set with main.
4. Make *separate* official admission-run contract for independently authenticated DK quote/cohort, provider price archive, actual-start source, and SBR comparator; receipt hashes alone never supply verification.
5. **No merge, promotion, credential handling or admission authority** for the builder.
