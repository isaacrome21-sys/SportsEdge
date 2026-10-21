# Check D sections 5.2–5.4

Authority: #2447 comments 6308060982 and 6315337229. Supplements merged
`sportsedge/oddspapi_numeric_admission_ad.py` D5.1; never overrides it.
API `evaluate_check_d_sections`. Complete synthetic input examples in tests.

- 5.2: >=95% in [actual-first-play minus 6 hours, actual-first-play), exact
  boundary arithmetic. The close schema is exactly the merged #2446 schema.
  Missing/mismatched anchors fail in the denominator. Duplicate close units
  refuse even with different receipt hashes. D5.1 still separately requires
  **100% pre-start**; passing 5.2 can never rescue a D5.1 failure.
- 5.3: reuses #2446 DK sample schema. Match fixture/book/market/side/line,
  enforce the existing 30-minute A matching window, rank by precise UTC time
  gap then sample_id, take ten. Require one explicit ISO timezone-offset
  difference across all ten. Fewer than ten never passes. No guessing naive
  zones or adjusting quote timestamps to make data agree. This calculates
  **declared-offset consistency only**; a claimed UTC stamp cannot prove the
  provider's underlying timezone semantics. That requires independent raw
  source verification by the acquisition/admission lane. Price agreement
  remains Check A's job; it does not select this temporal diagnostic sample.
- 5.4: scan every submitted quote; malformed/nonfinite/nonpositive decimal
  odds, invalid line/side/book/timestamp/schema, quotes after retrieval,
  conflicting prices at the same identity/time, and post-start quotes claimed
  pregame fail visibly. Existing A parser price-domain bounds are reused,
  not a new market-admission threshold. No inference about unprovided market
  settlement rules. Empty scans do not pass. Invalid quotes remain failures
  in the scan count, not silently dropped.

Local execution: `python -m unittest discover -s tests -p
'test_oddspapi_check_d_sections.py' -v` — 15 tests passed. No network, secrets,
real historical prices, registry updates or forward-count changes. Output
always NOT_ADMITTED, eligible false, play_authority false. The supplied hash
does not authenticate cohort completeness: admission runner must bind the
entire scan/close/sample lists to the frozen raw pull and independent anchors.
Hosted CI and independent exact-head review remain pending.
