# NFL props v1.1 — moved-line amendment (DRAFT, NOT FROZEN)

Applies to: Part 2 (`PREREG_NFL_PROPS_PART2_FORWARD_V1.md`, #2396) and 2B
(`PREREG_NFL_PROPS_PART2B_FORWARD_V1.md`, #2415). Owner ruling #1, 2026-10-22.
The v1 documents and records are not edited. Status: draft for owner freeze.

## 1. Scope and effective date
- Governs only rows whose kickoff is strictly after the v1.1 freeze timestamp.
- Freeze must occur before Sun 2026-10-25 12:00 CT (17:00Z). Week 7 is the
  first v1.1 slate. The 2026-10-22 slate stays scored under v1 exactly as recorded.
- Everything not stated here is unchanged from v1 (pricing, entry, sample and
  review gates, primary CLV test incl. 2B's QB-clustered check, 180 s/150 s freshness).

## 2. Buckets (replaces v1 §4.5 counting, not its close definition)
- READABLE: v1 readable close. Only these rows enter the CLV average.
- LINE_MOVED: v1 reason `LINE_MOVED`. Never repriced; no model touches the close.
  Recorded with `move_direction` relative to the pick:
  FAVORABLE (all close lines moved toward the pick: up for OVER, down for UNDER),
  ADVERSE (all moved away), AMBIGUOUS (close lines on both sides of entry),
  NO_PICK (no determinate pick). Stays in win/loss.
- A row is LINE_MOVED only if the close capture holds a readable two-sided,
  pre-kickoff close at the new line, captured no more than 60 minutes
  (v1 CLOSE_MAX_AGE_MINUTES) before kickoff. v1's `attach_close` labels
  LINE_MOVED before its timestamp and two-sided checks, so v1.1 re-checks every
  v1 LINE_MOVED row against the closes at other lines. If none qualifies, the row
  is a CAPTURE_FAILURE with reason, by precedence: NO_CLOSE_ROW (no other-line
  close) → CLOSE_SINGLE_SIDED (none two-sided) → CLOSE_NOT_PREKICKOFF (two-sided
  but none pre-kickoff) → CLOSE_STALE (two-sided pre-kickoff but all too old).
  A close without a timestamp is a hard error.
- Direction uses only the final (latest) qualifying pre-kickoff capture.
- CAPTURE_FAILURE: NO_CLOSE_ROW, CLOSE_SINGLE_SIDED, CLOSE_STALE, CLOSE_NOT_PREKICKOFF.
- Any other close state is a hard error (fail closed).

## 3. Verdict, per market, in order
1. v1 sample/review gates (INSUFFICIENT_SAMPLE, REVIEW_NOT_OPEN) unchanged.
2. CAPTURE_FAILURE share > 20% of graded rows → INSUFFICIENT_CLOSE_DATA.
3. Required co-test: exact one-sided binomial sign test on the moved bucket,
   H0 p=0.5, H1 adverse > favorable, α = 0.05; AMBIGUOUS counts as adverse,
   NO_PICK excluded. Counting AMBIGUOUS as adverse makes the test
   conservative against the family: under a true null its real
   false-rejection rate is above the nominal 5%. Rejection → DOES_NOT_BEAT_MARKET
   (reason MOVED_BUCKET_ADVERSE_SIGN_TEST).
4. LINE_MOVED share > 50% of graded rows → LOW_COVERAGE: reported, cannot open PLAY alone.
5. v1 primary CLV test on READABLE rows passes → BEATS_MARKET; else DOES_NOT_BEAT_MARKET.

PLAY eligibility still requires every other program gate; BEATS_MARKET is necessary, not sufficient.

## 4. Implementation
`nfl_props_v1_1.py` (overlay; v1 code untouched), tests `test_nfl_props_v1_1.py`.
At freeze, record sha256 of this document and both files in a SPEC_HASHES file.
