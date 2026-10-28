# BUILD RECORD — CBB team-totals forward runner (readout of CBB_TORVIK_EFFICIENCY_V1)

Date: 2026-10-28. Builder: Rocky (Muse), forward-runner build for
freeze-package finding **F-1** (no built forward runner existed on
main). State after this build: **DESIGN_PASS, NOT FROZEN** — the
freeze act has not happened; this build performs no part of it, and
nothing in it counts.

## What was built

| File | Role |
|---|---|
| `sportsedge/cbb_team_total_forward.py` | This family's runner: NON_COUNTED slate pricing (one TEAM_TOTAL record per team per game, from the capture's TEAM_TOTAL_AWAY / TEAM_TOTAL_HOME sections), separate settlement path. |
| `sportsedge/cbb_torvik_efficiency_v1.py` | The shared core it is built on (construction, R-1 vintage reader, crosswalk + Illinois rule, record machinery) — see the parent family's BUILD_RECORD. |
| `tests/test_cbb_team_total_forward.py` | 5 offline tests. |
| `forward_landing_check_20261028/` | The NON_COUNTED landing check (`landing_check.py`, `LANDING_CHECK.json`, `entry_records_sample.jsonl`). |

Runner discipline is the parent family's: pins verified at
construction (`PIN_MISMATCH` before any pricing), create-only
record writes, per-row committed fields (subject team + venue,
entry line + both prices + capture timestamps, no-vig pair,
candidate and simple-baseline model team points, gap stamps,
vintage pin, construction/prereg/package pins), fail-closed named
refusals, settlement separate from pricing.

## The NOT_FROZEN contract

- `FREEZE_STATE = "DRAFT_NOT_IN_FORCE"`; every record carries
  `counted=False`, `label="NON_COUNTED"`, `verified_play=False`.
- Counted entry points refuse: `price_slate(..., counted=True)`,
  `price_counted_slate(...)`, and `run_forward_test(...)` all raise
  `CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN`.
- The package's recorded condition on the parent stands: this
  readout's freeze act may only be recorded alongside or after the
  parent family's act and its data gate (the Nov 1 capture-delivery
  pre-check). This build performs neither.

## Landing check (NON_COUNTED) — PASS

`forward_landing_check_20261028/LANDING_CHECK.json` (10 assertions,
all ok; deterministic — a re-run reproduces the committed sample
records byte-identically):

- **Readout equivalence, 24/24 records exact.** The parent check's
  landing slate (agreed fixtures of 2023-02-25 and 2023-03-12,
  rebuilt from the pinned hoopR/CBR legs, Illinois excluded,
  identity via the crosswalk) priced from the same converted
  vintage stores: every record's candidate AND simple-baseline
  model team points are float-identical to the construction of
  record (`cbb_team_totals.py`: `candidate_team_points` /
  `simple_baseline_team_points`) on the same inputs.
- **Record path:** 24 team records (2 per game), every one
  `counted=False`; every record asserts `forward_baselines =
  ["SIMPLE_RATINGS"]` and carries NO naive field (answer A-1).
- **Illinois:** a Duke @ Illinois game refuses
  `ILLINOIS_COLLEGE_EXCLUDED`, no records.
- **Counted refusals:** both counted entry points raise
  `CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN`.
- Entry lines are the labeled synthetic fixture described in the
  parent family's BUILD_RECORD (`SYNTHETIC_LANDING_FIXTURE`); no
  record is counted.

## Refusal codes implemented

Run/slate level (raise): `CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN`,
`PIN_MISMATCH`, `RECORD_FILE_EXISTS`, `FORM_INVALID`, and the
shared core's vintage family (see the parent BUILD_RECORD).
Per game/team (recorded refusals): `SLATE_DATE_MISMATCH`,
`DUPLICATE_GAME`, `DUPLICATE_ROW`, `IDENTITY_UNVERIFIED`,
`ILLINOIS_COLLEGE_EXCLUDED`, `TORVIK_TEAM_NOT_CARRIED`,
`ENTRY_CAPTURE_MISSING`, `ENTRY_SINGLE_SIDED`,
`ENTRY_CAPTURE_TIMESTAMP_INVALID`, `ENTRY_NOT_PRE_EVENT`,
`PRICE_INVALID`, `LINE_INVALID`.

## Where the design underdetermines the runner — readings chosen

1. **No home-court term in team points.** The parent design applies
   its home-court term to the MARGIN (§1's margin definition); the
   construction of record's `candidate_team_points` has no
   home-court input, and the screened team-totals MAE (8.341) is a
   property of THAT construction. The alternative reading — adding
   a share of the term to the home team's expected points — would
   silently change the construction after its screen and was
   rejected. The records carry the parent outputs' home-court term
   fields for traceability; they do not enter team points.
2. **G-1/G-2/G-3 stamped, not filled** — identically to the parent:
   `classification="PICK_RULE_UNDEFINED"`, `pick=None`, the G-2
   interval stamp, and closes recorded as reported under
   `close_rule="CLOSE_RULE_UNDEFINED_GAP_G3"`; framework defaults
   in CONFIG_DRAFT are applied nowhere (they carry no
   preregistration force).
3. **Section mapping.** Capture team-total sections are mapped to
   subjects by the fixture's identity (TEAM_TOTAL_AWAY /
   TEAM_TOTAL_HOME, the capture-scope module's section names),
   never by display-name matching at pricing time. The shared
   intake parser has no CBB adapter yet (see the parent
   BUILD_RECORD, reading 5); `games_from_board` consumes its output
   shape.
4. **R-1 refusal granularity** — whole-slate, as in the parent.

## Verification run with this build

- New tests: 5, all passing; the shared-core suite pins arithmetic
  equivalence against this family's construction module over 200
  randomized inputs.
- Full CBB selection (`pytest -k cbb`): 172 passed, including this
  family's untouched screen suite.
- Repo PR gates: dependency parity 11 = 11; `ruff check --select
  E9,F821,F822,F823,F811 .` clean.
- Freeze-coverage self-check: none of this build's paths are
  covered by the registry; every pinned package file is
  byte-unchanged (the build only adds files).
