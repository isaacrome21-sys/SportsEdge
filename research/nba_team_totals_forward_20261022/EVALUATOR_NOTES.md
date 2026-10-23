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
