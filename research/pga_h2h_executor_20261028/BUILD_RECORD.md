# BUILD RECORD — PGA H2H Leg 1 screen executor (Workstream B, 2026-10-28)

Branch: `rocky/pga-h2h-executor-20261028` (DRAFT PR for Rocky
clearance; this record is builder-reported until independently
verified).

## What was built

- `pga_h2h_executor.py` (`PGA_H2H_EXECUTOR_V1`) — the design §4/§6
  executor: pin-verified corpus loading; `FeatureWindow` PIT door
  (strictly-prior events only, `PITViolation` on any other access;
  composite `(event_id, year)` identity); §4 pricing (trailing-24-month
  SG skill, 6-month half-life, 40-round UNPRICED floor, course fit,
  field-percentile-clamped residual SD); seeded field simulation with
  simulated cut; reference (a) field-normalized outright-Close pairs;
  reference (b′) exactly per Amendment 1 §3.2 (validity rule, BT form,
  golden-section α ML on fit-window decided pairs); log-loss /
  calibration / volume scoring; and the gated verdict path
  (`run_leg1`).
- `run_landing_check.py` — the wiring-only landing check.
- `landing_check_result.json` — its output on the real corpus.
- `READINGS_REGISTER.md` — 3 unpinned design parameters (verdict path
  refuses without them) + 10 named readings, all flagged for the
  adoption/freeze review.
- `tests/test_pga_h2h_executor.py` — 24 tests.

## Refusal behavior (the point of the build)

`run_leg1` refuses — `ScreenRefusal`, verdict `NOT_EXECUTABLE`, stamp
`PRE_ADOPTION_CHECK` — unless ALL of: Amendment 1 adopted, content pin
admitted (attested AND the manifest's own status reads ADMITTED), and
every design parameter pinned. No artifact in existence satisfies the
first two conditions, so no verdict can be produced. The landing check
invokes the verdict path only to record the refusal:
`['AMENDMENT_1_NOT_ADOPTED', 'CONTENT_PIN_NOT_ADMITTED']` against the
current draft manifest. Note the executor does not depend on the
Workstream A PR: it consumes any extracted store + manifest handed to
it; the landing check ran against A's DRAFT manifest in the workspace
store, and still refused on both grounds.

## Landing-check outcome (2026-10-28, plumbing config labeled PLUMBING_ONLY)

- Corpus loaded through the executor's own pin verification: 157
  events, 19,630 rows, corpus sha256
  `cef59544a3f9f813db90154eed0715ccd2d4cd09acb486dbe12ae7585eec96d6`.
- Amendment 1 §3.2 headroom reproduced exactly: both-valid-rank pairs
  per test season **161,012 (2023) / 170,476 (2024) / 167,977 (2025)**.
- Fit-window decided both-valid pairs (§3.2 step 4 accumulation):
  343,598 (≤2022) / 467,042 (≤2023) / 599,572 (≤2024). Test-event
  decided pairs: 123,444 / 132,530 / 127,714.
- Pricing wiring (PLUMBING_ONLY values): priced pairs per test season
  121,156 / 112,679 / 112,189 over 27 / 30 / 29 events — the
  criterion-4 floor is 1,500; these are wiring counts, NOT criterion
  results.
- Simulation wiring: 2025 Masters priced 69 players; 2,346 pairs with
  decided simulations at 200 sims; probabilities computed and
  discarded.
- Runtime: ~7 s for the full landing check (pure stdlib).

## Tests

24/24 in `tests/test_pga_h2h_executor.py`: (b′) math incl. the
amendment's worked illustration (rank 2 vs 39 at α=0.5 → 0.815), α
recovery from synthetic pairs at known scale, α determinism, finish
parsing/decided-pair rules, tie/undecided exclusion from scoring,
reference (a) normalization + sentinel exclusion, PIT (future event
cannot enter a window; direct access raises; editions are distinct
composite keys), the 40-round floor (39 rounds → UNPRICED), the
dg_pts/dg_rank exclusion (not in consumed fields, not on the row
type), simulation determinism and count completeness, all three
refusal layers, and corpus pin verification incl. tamper failure.
Ruff gate (E9,F821,F822,F823,F811) clean. Stdlib only.

## What remains before any verdict run

Owner adoption of Amendment 1; the governed G-PGA-2 admission act;
the freeze act pinning the three UNPINNED parameters and confirming
the readings register; the design's own freeze. Until then the screen
stays NOT_EXECUTABLE and this executor produces wiring records only.
