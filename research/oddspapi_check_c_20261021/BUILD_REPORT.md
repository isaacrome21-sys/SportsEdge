# Check C — ALCS reproduction and MLB SBR comparator

Authority: #2447 comments 6308060982 and 6315337229. Synthetic only,
never ADMITTED. API `evaluate_check_c` with `{version, alcs_g6, sbr_sample}`.
Complete fixtures/schema are in `tests/test_oddspapi_check_c.py`.

C1 requires exactly the TB -158 / CLE +130 moneylines and TB -1.5 run line,
same declared MLB ALCS game 6 fixture, DraftKings identity, timezone-aware
timestamps strictly before the independently claimed first-play anchor.
Missing quotes fail; duplicate/foreign quotes and mismatched anchors refuse.
No run-line price was specified by the governing bar, so none is invented.
Fixture/anchor/hash authentication belongs to the admission runner.

C2 directly adapts #2449's comparator at commit
`a31ef589e818cf6db25a14062159e4f7fd217f0e`, with MLB calendar-year season IDs.
Same >=200 distinct games, >=4 seasons, latest-complete-season final-week
cohort, ML gap <=10 on >=97%, exact lines >=95%, <=0.5 gap >=99%, zero gaps
>1.0, explicit book identity and missing-quote denominator. Per-season
counts disclosed; no additional stratification floor invented. C2 remains
self-contained so its draft does not modify or race the verified B branch.

Local execution: `python -m unittest discover -s tests -p
'test_oddspapi_check_c.py' -v` — 13 tests passed. Tests use synthetic fixtures,
including C1 values prescribed by policy; no real ALCS record is claimed.
Independent exact-head review and hosted CI pending. Authenticated SBR,
provider records, final-week schedule and actual first-play proofs remain
the acquisition lane's responsibility. No source admission or forward count.
