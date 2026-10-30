# FAILURE RECORD — `NFL_RUSH_REC_PROPS_V1` — SCREEN_FAIL, construction retired

**Records-only landing.** This file is the cover memo for landing the
executed screen's record on main. It creates no verdict (the verdict
already exists — it was rendered by the screen itself, below), changes
no code, and resurrects nothing. **FAILED constructions stay retired.**

## Why this exists

The conformance audit of Oct 29, 2026 (gap A5: "failure records living
only on unmerged branches") found that this family's completed,
rule-bound retirement existed **only on PR #2916's still-open branch**.
If that branch rots, the program loses the record that the construction
was tried, failed on calibration, and retired — and a future lane could
honestly re-propose it. This PR lands the record on main; PR #2916
itself stays open on its own merits (it is the design PR).

## Source

| Item | Value |
| --- | --- |
| Source PR | #2916 (`Design: NFL_RUSH_REC_PROPS_V1 … (DESIGN ONLY)`, still OPEN) |
| Source branch | `grok/nfl-rush-rec-props-v1-design-20261028` |
| Source commit (results) | `85a566df95f8d126bfdc9a57f292bcc8da0233ab` — "NFL_RUSH_REC_PROPS_V1 screen: SCREEN_FAIL on RUSH_YDS, REC_YDS, RECEPTIONS - construction retired, no retune" |
| Build record commit | `c8bef924` — committed **before** any outcome statistic was computed |
| Construction/screen code commit | `55cfa6ac` — code committed before the run; **not** landed by this PR (see below) |
| Design | `research/nfl_rush_rec_props_design_20261028/DESIGN_NFL_RUSH_REC_PROPS_V1.md`, sha256 `d088676745914f11215352bbafcdbde5cd759d9d1e7d21d2c5ebaccfe222ad8c` (lives on the #2916 branch; independently reviewed SOUND-WITH-FLAGS, PR #2916 comment 6486781392; owner build authorization on the same PR) |

## What ran

One declared screen run, Wed Oct 28, 2026, 10:12 PM CT, under the
design's preregistered §5 criteria and the pre-outcome readings in
`BUILD_RECORD.md` (review flags F1–F6 pinned before outcomes; bootstrap
seed **20261028**, flag F3). Integrity checks (R12: input hashes,
evaluator hash, loader parity, prior alignment, incumbent arm reproduced
by the pinned evaluator's own `evaluate()`) all passed; 0 unpriceable
rows. Markets: RUSH_YDS (n = 3,226), REC_YDS (n = 8,278), RECEPTIONS
(n = 8,278), on the B8 file set.

## Verdict (the screen's own, verbatim in `SCREEN_REPORT.md`)

**SCREEN_FAIL on all three markets.** The challenger beat both
baselines' CRPS everywhere and beat the incumbent's CRPS outright on
RUSH_YDS (Δ −0.1783 [−0.2582, −0.1014]) and RECEPTIONS (Δ −0.0047
[−0.0090, −0.0006]), but **leg 3 — the calibration leg — failed in every
market**: the construction's top-decile gap stayed above the 0.05 cap
(RUSH_YDS 0.0985, REC_YDS 0.0830, RECEPTIONS 0.0973), and on RUSH_YDS
and RECEPTIONS it was larger than the incumbent's. The overconfidence on
the strongest over calls was not fixed. REC_YDS also failed leg 1
(ΔCRPS CI upper bound +0.0119).

## Effect

Per design §5: construction **FAILED_SCREEN and retired for all three
markets**. No retune, re-bucketing, or constant change. No freeze, no
forward clock, no adoption, no market claim. The incumbent (Part 2) and
its frozen forward test are untouched.

## Files landed by this PR (byte-identical to the source commit)

| File | sha256 |
| --- | --- |
| `BUILD_RECORD.md` | `cb9e254094b3d6ccad544791410dfbb42da8f21e97c9b03b35920396a809a589` |
| `SCREEN_REPORT.md` | `8f680f116d06668503d5cfe010bde298823de7f27d957a40f4394c593c891d8c` |
| `screen_results_v1.json` | `7e89435a464b4347d14893e54a1a74a7176f50602cdec72be1306227d8c0caf4` |

(Internal consistency check: `screen_results_v1.json` records
`build_record_sha256 = cb9e2540…`, matching the landed `BUILD_RECORD.md`.)

## Deliberately NOT landed

- `screen_nfl_rush_rec_props_v1.py` and `test_nfl_rush_rec_props_v1.py`
  (source commit `55cfa6ac`) — executable code of a retired
  construction. Landing code would imply a live construction; the
  record is what the program needs. Both remain readable on the #2916
  branch.
- The design package (`research/nfl_rush_rec_props_design_20261028/`)
  — that is PR #2916's own subject and lands (or not) with that PR.
