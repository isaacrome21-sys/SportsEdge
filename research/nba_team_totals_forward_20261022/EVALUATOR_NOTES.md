# Evaluator notes — NBA Team Totals Forward V1

`eval_nba_team_totals_v1.py` implements the FROZEN prereg in this directory
(sha256 `0274e8cd…f55504`, checked by `verify_frozen_doc()`). Tests:
`test_eval_nba_team_totals_v1.py` (RED commit `f3222f6f` first, module
absent; GREEN in the implementation commit).

**Status: NOT YET PINNED OR REVIEWED.** Per §12 and the freeze record, no
slate counts until this evaluator is hash-pinned and independently reviewed;
the first counted slate is the first slate priced after that.

## Conservative resolutions of ambiguity (A1–A9)

- **A1 Verdict order.** Undeclared refusal code → gates
  (`INSUFFICIENT_SAMPLE`, no metrics emitted) → adverse moved sign test
  (`DOES_NOT_BEAT_MARKET`) → >20% invalid close (`INSUFFICIENT_CLOSE_DATA`)
  → >50% picked rows moved (`INSUFFICIENT_CLOSE_DATA`) → 6a–6d. The adverse
  sign test outranks the 20% rule because a failure verdict is the more
  conservative outcome (matches NFL v1.1: sign test before coverage).
- **A2 Entry.** First DK ENTRY capture (by earliest quote) with
  `is_main=true`. If that capture has zero or several two-sided main lines
  the row is `ENTRY_SINGLE_SIDED`; no entry quotes at all is
  `DK_PAIR_MISSING_OR_STALE` (the runner's own code for that state).
- **A3 Close.** Only the last fully pre-tip close capture is used; an earlier
  valid capture never rescues a bad last one. The 60:00 window is measured
  from that capture's earliest quote.
- **A4** A close side with a non-finite or |price|<100 price is treated as
  absent (not two-sided).
- **A5** If a moved close carries several valid lines, 6a uses the line
  whose no-vig P(over) is nearest 0.5 (DK's main line); direction uses all of
  them (straddle = ADVERSE).
- **A6** `p_close` is multiplicative two-sided no-vig. DK refunds pushes, so
  this is the push-removed probability for whole-number lines; pushes are
  excluded from 6d and counted.
- **A7** Engine/runner sha mismatch or a history hash not recorded before
  pricing → `HISTORY_HASH_MISMATCH` (the run record fails to prove frozen
  code, §11). Runner-prefixed engine codes (`NBA_ENGINE_<code>`,
  `NBA_ENGINE_FAILED:<type>`) normalize to the declared engine codes.
- **A8 Bootstrap.** Game-cluster percentile bootstrap, ratio of resampled
  sums, two-sided at 1−α/k; each metric uses a fresh
  `numpy.default_rng(seed)` stream so results do not depend on metric order.
  Output is `binding: true` only with k ≥ 9, seed 20261022, 10,000 resamples.
- **A9** 6c requires both picked and passed rows; with no passed rows the
  picked-beats-passed ordering cannot be shown, so 6c fails
  (`NO_PASSED_ROWS`).
- **Gate counting.** "Rows with valid CLV pairing" = rows whose valid close is
  at the entry line (moved rows have a valid close but no CLV). Consequence:
  a heavily-moved sample reaches review later; it never reaches it sooner.
  Full slates come from the operator's per-slate capture-job record.

## Test fixture corrections after RED

Three RED fixtures under-sized the sample for the §4 gates (moved or
invalid-close rows don't count toward the 150 valid-CLV rows): slate counts
raised 8→12, 8→30, 8→10. No assertion changed. One test added
(`test_binding_flag`).

## Audit round 1 fixes (2026-10-22) and AMENDMENT_1

New refusal/CLV-missing codes are declared in `AMENDMENT_1.md`
(sha256 `7f5e55ef946d699069502b5ec3448e0cb66cb373733202bb437589e23f56e8d6`,
first committed on the prereg branch at `15b8fce8`; ruling by Grok under
owner delegation t234u; effective before the first counted slate). The
evaluator's code list = frozen §8 + AMENDMENT_1; `evaluate()` verifies both
hashes and raises on mismatch.

- **F1** Rows keyed on (game_id, team); every duplicate copy is
  `DUPLICATE_ROW`. Conflicting prices within one capture/line/side:
  entry → `ENTRY_QUOTE_CONFLICT`; close → that line invalid
  (`CLOSE_QUOTE_CONFLICT`). Identical repeats are not conflicts.
- **F2** `binding` requires doc + amendment hash OK and
  `len(clock_ids) == k` (distinct ids), plus k ≥ 9, frozen seed, 10,000.
- **F3** Each row parsed alone: bad/zoneless tipoff or priced_at, or
  non-finite b1/b2 → `ROW_MALFORMED`; bad entry quote time →
  `QUOTE_TIMESTAMP_INVALID`; bad close quote time →
  `CLOSE_TIMESTAMP_INVALID`; non-finite line → `PRICE_INVALID`;
  non-finite final → `RESULT_UNAVAILABLE`.
- **F4** 0 ≤ priced_at − entry quote ≤ 180 s (`PRICED_BEFORE_QUOTE` /
  `QUOTE_STALE_180S`); slate_date must equal tipoff's America/Chicago date
  (`SLATE_DATE_MISMATCH`).
- **F5** The last capture is chosen over all captures; if it holds any
  quote at/after tip → `CLOSE_NOT_PRETIP` (an earlier pre-tip capture never
  rescues it). Only `is_main=true` close quotes are used; a non-boolean or
  missing flag in the last capture → `CLOSE_MAIN_FLAG_MISSING`.
- **Minor** Missing capture_id: entry → `CAPTURE_ID_MISSING` (refusal);
  close → `CLOSE_CAPTURE_ID_MISSING`. `PUSH` count omitted before review.

`SPEC_HASHES_DRAFT.txt` is superseded by `SPEC_HASHES.txt`
(see `SPEC_HASHES_SUPERSEDED_NOTE.md`).

## AMENDMENT_2 (2026-10-22, re-audit of 2d2094b7)

`AMENDMENT_2.md` (sha256
`2e6f98d1e9ef01bf347ad404ff378a3f157c7f14291d36a8eb92af3133f38a8a`, prereg
branch `01d91eae`; no new codes) narrows F5: the close is the last capture
with at least one pre-tip quote; if it also has a quote at/after tip →
`CLOSE_NOT_PRETIP` (earlier captures never rescue it); fully post-tip
captures are ignored; no pre-tip capture → `CLOSE_NOT_PRETIP`.
`verify_amendment()` checks both amendment hashes.
