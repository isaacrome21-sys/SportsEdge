# NFL_PERIOD_DRIVE_STATE_V2 forward runner — BUILD RECORD (2026-10-28)

**The family is NOT FROZEN. Counted rows from this build: zero.**
This build closes the build half of PR #2914 §14 FLAG 3 (no forward
runner existed). It adopts nothing: PR #2914 (the prereg revision
draft, in this directory by branch) remains an unmerged draft, and
the freeze remains the owner's separate act.

## What was built

- `sportsedge/nfl_period_forward.py` — library-only forward runner
  mirroring the NBA period-lines build (PR #2893) and the CBB
  forward runners (PR #2907):
  - Construction of record: the pinned screen implementation
    `research/nfl_period_drive_state_screen_20261028/screen_nfl_period_drive_state_v2.py`,
    pin `nfl_period_drive_state_v2@sha256:16593a8779986f653705c481eaf0e079387933975123e386f8efd7e865b4658c`
    — **verified byte-exact against the file on main**, as were all
    eight pins in PR #2914's SPEC_HASHES (config, design, v1
    machinery, v1 prereg draft, sibling engine, team-half pricing,
    screen results, screen tests). Mismatch or absence refuses
    `PIN_MISMATCH` at construction, before any pricing.
  - Every counted entry point refuses
    **`NFL_PERIOD_FORWARD_NOT_FROZEN`** (`price_counted_slate`,
    `run_forward_test`, and `price_slate(..., counted=True)`). All
    emitted rows carry the NON_COUNTED stamps (counted False,
    validation/forward-clock/PLAY credit all False).
  - Markets: the 20 config markets (TOTAL/SPREAD/ML/TEAM_TOTAL ×
    1Q–4Q + 1H), verified against
    `sportsedge/forward_validation/configs/nfl_period_lines.json`
    at construction (`CONFIG_MISMATCH` otherwise; the config still
    carries `model_version: "UNPINNED"` and status DRAFT — NOT
    FROZEN, and the config flip remains the freeze act's own step,
    §14 FLAG 4).
  - Pick rule (§6): totals/team totals/spreads picked at |gap| ≥
    1.5 points (quarter) / ≥ 2.0 (1H) on the gap of construction
    mean vs entry line; ML picked when the construction's win
    probability exceeds the entry no-vig probability by ≥ 0.04.
  - Close rule (§8, the Oct 22, 2026 v1.1 rule): validity checks
    first (both prices, pre-kickoff, ≤ 60:00 before kickoff —
    exactly 60:00 valid), then moved classification; exactly one
    CLV_MISSING reason per row from {NO_CLOSE_ROW,
    CLOSE_SINGLE_SIDED, CLOSE_NOT_PREKICKOFF, CLOSE_STALE,
    LINE_MOVED}; moved rows form the separate bucket with
    favorable/adverse direction vs the model-selected side; the
    20% INSUFFICIENT_CLOSE_DATA trip counts **only** the four
    capture failures; moved share > 50% labels the CLV verdict
    LOW_COVERAGE. ML closes have no line, so they can be valid or
    capture failures, never LINE_MOVED.
  - Settlement (§3): regulation period scoring only (OT never
    enters, by the panel's construction); VOID for
    postponed/cancelled/no-score finals; PUSH counted and reported;
    RESULT_UNAVAILABLE never filled.
  - §2 seed derivation: per-game streams from
    `SeedSequence([20261028, game index])`, the game index order
    committed in every run record.
- `tests/test_nfl_period_forward.py` — 17 tests (below).
- This directory: `run_landing_check.py`, `LANDING_CHECK.json`,
  `entry_records_sample.jsonl` (350 NON_COUNTED rows).

## Stamped readings and gaps (never filled)

- **FLAG 5 B0 forward share-fit — a READING.** The quarter-market
  §7b baseline ships in its drafted forward form: sibling full-game
  mean × league period shares fit on games final before the entry
  capture (same-season priors, else the prior season's final
  shares, else uniform), stamped `B0_SHARE_FIT_READING_FLAG5` with
  the fit's sha256 committed per run record. Freeze review must
  still confirm the form (§14 FLAG 5). Where the forward form
  coincides with the pinned screen's `baseline_rows` (week-opening
  games), the two are float-exact — asserted in tests and in the
  landing check.
- **1H baseline emissions.** `sportsedge/team_half_pricing.py` is
  a live ESPN-fixture surface (it refuses non-future fixtures), so
  it cannot emit derivatives for a historical slate. The runner
  records caller-supplied emissions verbatim; where none is
  supplied the row carries `BASELINE_1H_EMISSION_ABSENT` and no
  value. The landing check's 1H rows are stamped exactly so.
- **Completion convention — a READING.** "Games final before the
  entry capture" is evaluated as kickoff + 4h ≤ entry capture time
  (the cached schedules carry no final-at timestamps), stamped
  `COMPLETION_CONVENTION_KICKOFF_PLUS_4H` in every run record.

## Landing check (NON_COUNTED)

Slate 2024 Week 10 (14 REG games) priced + settled end to end on
the pinned screen's cached inputs (input hashes in
LANDING_CHECK.json; they equal the screen package's INPUT_PINS).
Entry/close quotes are a labeled `SYNTHETIC_LANDING_FIXTURE`
(static per-market lines, flat fixture prices, five engineered
close exceptions) — **no real DraftKings period capture exists**;
see the precondition below. **24/24 checks pass**, including:

- counted entry points refuse `NFL_PERIOD_FORWARD_NOT_FROZEN`;
- 350 rows priced (one per fixture quote), all NON_COUNTED,
  counted_rows 0, zero refusals;
- TNF (2024_10_CIN_BAL): runner model means / ML probability equal
  the pinned construction invoked directly, **float-exact**;
- TNF B0 means and sibling mus equal the pinned `baseline_rows`
  output, **float-exact**;
- the five engineered closes land exactly as designed: one
  LINE_MOVED, one NO_CLOSE_ROW, one CLOSE_SINGLE_SIDED, one
  CLOSE_STALE, one CLOSE_NOT_PREKICKOFF; 345 valid closes, 34
  pushes in settlement.

Tests: `tests/test_nfl_period_forward.py` 17/17 pass (pin
verification + mismatch refusal, counted refusals, pick-rule
boundaries, all close dispositions incl. validity-before-moved
precedence, trip counting excluding LINE_MOVED, form gates, B0
float-exactness vs `baseline_rows`, pricing float-exactness vs
the pinned construction on a synthetic history, settlement
end-to-end). PR-only CI gates run locally: dependency parity
(pyproject dev set == requirements-test.txt, 11 = 11, no new
dependencies) and `ruff check --select E9,F821,F822,F823,F811`
clean. Neighboring suites (screen, NBA period, CBB forwards)
39/39 pass unchanged.

## What a freeze still requires (all open)

1. **The owner freeze act** on the reviewed revision prereg —
   including closing §14 FLAG 1 (moved-cap label), FLAG 2
   (sign-test level), FLAG 5 (B0 form), FLAG 6 (entry/close
   designation), and re-striking the §2 pin if this runner becomes
   the priced artifact (FLAG 3).
2. **The capture-expansion precondition (§4/§15), still open:**
   DraftKings period lines are not in the priced capture subset
   today (they exist only inside issue line-3 comments) and the
   intake grammar has no period line forms. This runner consumes
   capture **records** in its own `PeriodQuote` form; it invents no
   capture pipeline, and until the expansion lands with its own
   parser tests, no counted slate can exist.
3. Independent review CLEARED on the exact freeze head; the
   bootstrap seed and the §10 k list in the freeze record; the
   first counted slate named by the act.
