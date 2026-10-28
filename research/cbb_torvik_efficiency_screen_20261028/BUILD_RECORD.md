# BUILD RECORD — CBB_TORVIK_EFFICIENCY_V1 forward runner

Date: 2026-10-28. Builder: Rocky (Muse), forward-runner build for
freeze-package finding **F-1** (no built forward runner existed on
main). State after this build: **DESIGN_PASS, NOT FROZEN** — the
freeze act has not happened; this build performs no part of it, and
nothing in it counts.

## What was built

| File | Role |
|---|---|
| `sportsedge/cbb_torvik_efficiency_v1.py` | Shared core: construction arithmetic of record, fitted forward constants, the R-1 morning-of vintage reader, the crosswalk resolver + Illinois rule, quote/record machinery (shared with the team-totals readout). |
| `sportsedge/cbb_efficiency_forward.py` | This family's runner: NON_COUNTED slate pricing (SPREAD + TOTAL records), separate settlement path, `games_from_board` intake helper. |
| `tests/test_cbb_torvik_efficiency_v1.py`, `tests/test_cbb_efficiency_forward.py` | 22 offline tests (see below). |
| `forward_landing_check_20261028/` | The NON_COUNTED landing check (`landing_check.py`, `LANDING_CHECK.json`, `entry_records_sample.jsonl`). |

Modeled on the frozen NFL team-totals runner/driver pair: pins
verified at construction (a pinned artifact whose on-disk sha256
disagrees with this package's SPEC_HASHES raises `PIN_MISMATCH`
before any pricing), create-only record writes (`RECORD_FILE_EXISTS`
rather than overwrite), per-row committed fields (identity, entry
line + both prices + both capture timestamps, no-vig pair, candidate
and simple-baseline model outputs, fitted terms used, seed, vintage
pin, construction/prereg/package pins), fail-closed named refusals,
settlement a separate path from pricing.

## The NOT_FROZEN contract

- `FREEZE_STATE = "DRAFT_NOT_IN_FORCE"` on the runner and on every
  record; every record carries `counted=False`,
  `label="NON_COUNTED"`, `verified_play=False`.
- Counted entry points refuse: `price_slate(..., counted=True)`,
  `price_counted_slate(...)`, and `run_forward_test(...)` all raise
  `CBB_EFFICIENCY_FORWARD_NOT_FROZEN`.
- The freeze checklist's remaining owner acts are untouched by this
  build: the act itself, the first counted slate designation, the
  k re-derivation at act time, and the Nov 1 capture-delivery
  pre-check (data gate (iii) stays OPEN).

## Landing check (NON_COUNTED) — PASS

`forward_landing_check_20261028/LANDING_CHECK.json` (19 assertions,
all ok; deterministic — a re-run reproduces the committed sample
records byte-identically):

- **Construction equivalence, 12/12 games exact.** Agreed fixtures
  of 2023-02-25 (8 games, all non-neutral) and 2023-03-12 (4 games,
  all neutral), rebuilt with the screen runner's own machinery from
  the pinned hoopR/CBR legs, Illinois excluded, identity via the
  crosswalk. The forward runner priced them from vintage stores
  converted out of the pinned D-1 archive files, read back through
  the production R-1 loader. Candidate and baseline expected
  points, totals, and margins (under the forward home-court
  constant) are float-identical to `run_screen_attempt4.py` on the
  same inputs; the vintage league means equal the archive parse's
  exactly.
- **Record path:** 24 records (2 per game), every one
  `counted=False`, pins verified at construction.
- **Fitted constants cross-checked:** the baseline fixed constant
  in the build (3.3756023216238145) equals the published screen
  result exactly; the 2022-23 candidate term recomputed during the
  build (3.2501022398177666) also equals the published value
  exactly, proving the fit machinery before it was extended.
- **R-1 refusals proven against the real pull store:** the
  2026-11-02 vintage refuses `TORVIK_VINTAGE_MISSING`; the real
  2026-10-28 morning-of vintage loads as a positive control (365
  teams); a copy of it carrying Amendment 1 §7's `snapshot_warning`
  refuses `TORVIK_VINTAGE_LATE_PULL`.
- **Illinois:** a Duke @ Illinois game on the landing vintage
  refuses `ILLINOIS_COLLEGE_EXCLUDED`, no records.
- **Counted refusals:** both counted entry points raise
  `CBB_EFFICIENCY_FORWARD_NOT_FROZEN`.
- Entry lines in the historical check are a labeled synthetic
  fixture (`capture_source="SYNTHETIC_LANDING_FIXTURE"` — the
  screen construction's outputs rounded to the nearest half point
  at −110/−110): no admitted DK capture exists before the Nov 1
  pre-check, so real captures cannot be used here; the fixture
  exercises the record path only and no record is counted.

## Refusal codes implemented

Run/slate level (raise): `CBB_EFFICIENCY_FORWARD_NOT_FROZEN`,
`PIN_MISMATCH`, `RECORD_FILE_EXISTS`, `FORM_INVALID`, and the
vintage family — `TORVIK_VINTAGE_MISSING`,
`TORVIK_VINTAGE_UNAVAILABLE`, `TORVIK_VINTAGE_DATE_MISMATCH`,
`TORVIK_VINTAGE_HASH_MISMATCH`, `TORVIK_VINTAGE_LATE_PULL`,
`TORVIK_VINTAGE_SCHEMA_INVALID` (plus
`IDENTITY_CROSSWALK_INVALID` from the crosswalk loader).
Per game/market (recorded refusals): `SLATE_DATE_MISMATCH`,
`DUPLICATE_GAME`, `DUPLICATE_ROW`, `IDENTITY_UNVERIFIED`,
`ILLINOIS_COLLEGE_EXCLUDED`, `TORVIK_TEAM_NOT_CARRIED`,
`ENTRY_CAPTURE_MISSING`, `ENTRY_SINGLE_SIDED`,
`ENTRY_CAPTURE_TIMESTAMP_INVALID`, `ENTRY_NOT_PRE_EVENT`,
`PRICE_INVALID`, `LINE_INVALID`.

## Where the design underdetermines the runner — readings chosen

1. **Forward home-court fit.** §3 fits the candidate term
   walk-forward per scored season; the forward scored season is
   2026-27, so the term is ONE fit over the agreed non-neutral
   fixtures of all admitted archive seasons (26,553 fixtures):
   **3.260655725219634**. The baseline constant stays the 2014-15
   window estimate (3.3756023216238145) — the design freezes it
   after the first window. Both constants are pinned in the shared
   core with provenance; the freeze act re-pins them, and any refit
   is a new build. No in-season refit is performed (the design's
   scored season is the whole season).
2. **Home-court placement.** The term enters the margin only,
   exactly as §1 defines it and as the construction of record
   computes it; expected team points carry no home-court term (the
   alternative — adding it to the home team's points — would change
   the team-totals readout from the construction that was actually
   screened, so it was rejected; see the team-totals BUILD_RECORD).
3. **R-1 refusal granularity.** A missing/mismatched/late vintage
   refuses the WHOLE slate (a run-level NO_DATA), never a partial
   slate priced from a neighboring date — R-1 names the slate
   date's own vintage as the only lawful input.
4. **G-1/G-2/G-3 are stamped, not filled.** Records carry
   `classification="PICK_RULE_UNDEFINED"`, `pick=None`,
   `interval_construction="INTERVAL_CONSTRUCTION_UNDEFINED_GAP_G2"`,
   `close_rule="CLOSE_RULE_UNDEFINED_GAP_G3"`. Settlement records a
   supplied close as reported and grades accuracy only; nothing is
   aged out or excluded (the CONFIG_DRAFT framework defaults carry
   no preregistration force, so the build applies none of them).
   The only temporal rule enforced is capture-integrity: both sides
   of a quote must exist and be timestamped before tip.
5. **No CBB adapter exists in the shared intake parser**
   (`ADAPTERS` covers MLB/NFL/CFB/NBA/NHL; `adapter_for("CBB")`
   raises). The runner therefore does not parse issue text: it
   consumes the parser's output shape through `games_from_board`,
   with identity supplied by a fixture table keyed on the board's
   display-name pair — display names are never identity, and a
   board game with no fixture is never priced. Building the CBB
   adapter belongs to the Nov 1 pre-check workstream, not this
   build.
6. **Spread line semantics.** The captured line is recorded as
   captured (the away team's spread, the parser's convention) with
   `line_semantics` stated on the record; model margins are
   recorded home-minus-away. No gap or side is derived (G-1).
7. **Vintage integrity envelope.** The R-1 parser requires the
   live-route columns (team/adjoe/adjde/adjt/barthag — the pull
   store's actual format), league means over the file as published,
   and a 300–400 team-row envelope (a build-level integrity guard,
   not a design term; the manifest's own `team_rows` must also
   agree). A vintage outside the envelope refuses
   `TORVIK_VINTAGE_SCHEMA_INVALID` rather than pricing.
8. **Moneyline** is not priced: amendment answer A-1 registers
   SPREAD and TOTAL only for the forward test.

## Verification run with this build

- New tests: 22 in the two files above, all passing; construction
  equivalence vs the screen of record is pinned over 400 randomized
  inputs in the unit suite.
- Full CBB selection (`pytest -k cbb`): 172 passed — the existing
  family suites (attempt-4 screen, team totals, capture scope,
  crosswalk) are untouched and green.
- Repo PR gates: dependency parity 11 = 11; `ruff check --select
  E9,F821,F822,F823,F811 .` clean.
- Freeze-coverage self-check (repo matcher over all bundles): none
  of this build's paths are covered; every pinned package file is
  byte-unchanged (the build only adds files).
