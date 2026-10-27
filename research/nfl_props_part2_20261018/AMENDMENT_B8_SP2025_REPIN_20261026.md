# AMENDMENT B8 — sp_2025 played-game re-pin (Part 2)

**Status:** Owner-ruled amendment to the frozen Part 2 package
(PREREG_NFL_PROPS_CALIBRATION_V1.md + PREREG_NFL_PROPS_PART2_FORWARD_V1.md).
Prepared Oct 26, 2026. It supersedes exactly ONE pin in this package's
SPEC_HASHES.txt. No construction, threshold, evaluator, prereg term, or
other pin changes.

**Authority — Isaac's ruling, Oct 26, 2026 (verbatim substance):** "B8 —
require a re-pin. Do not count any affected rows under the old freeze.
Preserve the original version and evidence, publish the corrected version
and its effective date, and count only eligible forward rows after the new
freeze. No backfill."

## 1. What drifted

The nflverse `sp_2025.csv.gz` season file (the new "sp" schema) emits a
row for every rostered player each week, including players who did not
play. The frozen evaluator loader counts every REG row as a played game,
so zero-usage roster rows act as phantom 0.0 games in priors, role means
and league pools.

Measured (Oct 24, 2026 sweep, `nfl_props/REPORT.md` §4 B8 / probes.py S12;
independently replicated exactly on Oct 26, 2026 while preparing this
amendment):

- **771 zero-usage skill-position REG rows** (WR 378, RB 218, TE 160,
  FB 13, QB 2), vs ~16–18 per season in the ps-era files.
- **434 skill-player-weeks in 2025 reach "3 prior games" with fewer than
  3 actually played** (141 distinct players). Example: WR `00-0031763`,
  whose first four 2025 rows are all zero-usage.

The ps-era files (2018–2024) are not re-pinned: their pins are unchanged
and the measured defect is the sp-schema file's.

## 2. The corrected artifact and the played-game predicate

New artifact: **`sp_2025_played_v2.csv.gz`**, built from the preserved
original by `build_sp_2025_played_v2.py` (this package; the artifact and
the tool are shared with Part 2B, as the original file and its pin were).

A row is removed **iff** its own `position` field is a skill position
(QB, RB, WR, TE, FB) **and** `f(attempts) + f(carries) + f(targets) == 0`,
where `f()` is the evaluator loader's own cell coercion (float, 0.0 on a
blank or non-numeric cell). Attempts, carries and targets are the file's
own participation evidence for a skill player. Rows for every other
position pass through untouched — defenders, kickers and punters record
no attempts/carries/targets by construction, and their rows are not this
correction's to delete.

- Removed: **804 rows of 19,422** (771 REG + 33 POST). Kept: 18,618.
- Schema, column order and row order unchanged; every kept row is
  byte-identical to the original's row.
- Deterministic build (gzip mtime=0, compresslevel=9): rebuilding from
  the original reproduces the pinned sha256.

## 3. Pin changes (old → new)

| Artifact | Old pin (pre-amendment freeze) | New pin (this amendment) |
|---|---|---|
| 2025 season file | `c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b` (`sp_2025.csv.gz`) | `f2768ac1c71e5ed616307106df32ef8ad4fc7d548bb96600f6a616fb631f7b48` (`sp_2025_played_v2.csv.gz`) |

Every other line of SPEC_HASHES.txt is unchanged: the calibration prereg
(`bef8d74e…`), ps_2018–ps_2024. The evaluator file is unchanged
(sha256 `66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b`,
its prereg §1 pin), so the pricer's embedded EVALUATOR_SHA256 pin stands.

**Lockstep:** SPEC_HASHES.txt is the single registry read by both the
evaluator's `check_hashes` (which hash-verifies every listed `.gz`
against the data dir before any calibration run) and the pricer's
`check_training_pins`. Moving this one line moves the evaluator and the
pricer to the same corrected input at the same moment; neither can hash
a different 2025 file than the other. Verified Oct 26, 2026: under the
amended registry, `check_hashes` passes on a data dir composed per §4
and fails closed on a data dir still carrying the old composition.

## 4. Data-dir composition rule (operational)

A player-data dir used under this amendment contains
`sp_2025_played_v2.csv.gz` and must **not** contain `sp_2025.csv.gz`: the
loader globs `sp_*.csv.gz`, so carrying both would double-load the 2025
season. Staged composition prepared with this amendment:
`~/workspace/sportsedge/nfl_player_data_repin_20261026/` (ps_2018–2024 +
sp_2026 copied unmodified from the standing dir, plus the corrected
artifact).

## 5. Effective date, counting, no backfill

- **Effective date:** this amendment takes effect on publication — the
  merge of the re-pin branch to main. Counted forward rows are only rows
  priced from slates priced **after** that moment, from a data dir
  composed per §4.
- Rows priced under the old pins — whenever priced, including any priced
  after the Oct 26 ruling but before publication — are **research-only**
  and never count toward the forward test.
- **No backfill:** no historical row is re-priced, re-pinned or
  re-counted under the corrected artifact. The original
  `sp_2025.csv.gz` is preserved unmodified, and its pin above remains the
  pin of record for the pre-amendment freeze; the old-freeze evidence
  chain (Oct 24 sweep measurements, committed run records) is untouched.
- Zero counted forward rows exist under this package at the effective
  date, so the re-pin invalidates nothing already counted.

## 6. Verification (Oct 26, 2026, all run — not read)

- Evidence replicated exactly: 771 zero-usage skill REG rows; 434
  affected skill-player-weeks (sweep probe arithmetic, this package's
  loader).
- Artifact audit by independent code: the corrected file is an
  order-preserving subsequence of the original; 0 removed lines fall
  outside the §2 predicate; 0 phantom skill rows remain; under both
  packages' loaders the 2018–2024 and 2026 loads are identical to the
  original composition and the 2025 load is exactly
  original-minus-phantoms; the 434-measure reads **0** on the corrected
  artifact.
- Capture equivalence: all 6 Oct 25 operative captures (83 rows) priced
  with base pricers + old composition vs amended pricers + corrected
  composition, whole output dirs diffed — **byte-identical**
  (`DIFF_EMPTY_ALL_OUTPUTS_IDENTICAL`), and the base CLI reproduces the
  lane's own committed AM priced_rows.json byte-for-byte. The Oct 25
  captures are 2026-season, so no priced row's priors touch the 2025
  file: this proves the re-pin disturbs nothing outside the drift. The
  drift's removal is proven by the loader audit above and the packages'
  synthetic B8 regression tests.
- Package suites (Part 2 + Part 2B): 43/43 pass, including 8 new B8
  tests. Ruff PR gate (`--select E9,F821,F822,F823,F811`) on all changed
  Python files: all checks passed. Dependency manifests untouched.
