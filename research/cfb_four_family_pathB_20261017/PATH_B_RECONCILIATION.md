# CFB four-family evaluation — Path B population reconciliation (R3 independent reproduction)

**Owner ruling 3 (Isaac, Oct 17 2026):** Path B (regular season only) is the
selected path. Reconcile the claimed 9,033-game population against the
frozen eligibility and exclusions. Complete independent R1–R3 verification,
immutable freeze identity, and exact-head CI. **Do not consume Attempt 1**
until those conditions are met and the execution GO is separately recorded.

**Status of this record:** evidence only. Attempt 1 is **not** consumed. No
probability was computed. The harness config is untouched (`freeze_sha:
null`, `status: PREREGISTRATION_DRAFT_NOT_FILED_NOT_IN_FORCE`). PR #2258 is
untouched.

## 1. Sources: all 15 pins reproduced byte-exact (fresh acquisition)

| Source | How acquired here | Pin check |
|---|---|---|
| ESPN CFB schedules 2021–2025 | `origin/data` @ `40f164b4…` (git) | 5/5 SHA-256 MATCH |
| ESPN CFB schedules 2013–2020 | GitHub release `sportsdataverse/sportsdataverse-data` `espn_cfb_schedules` | 8/8 SHA-256 MATCH |
| `cfb_line_odds.csv.gz` | `sportsdataverse/cfbfastR-data` @ `f5a05dc8…` (git) | `7ae899d9…` MATCH |
| `cfb_team_info_2024.parquet` | same repo/commit (git) | `503549b9…` MATCH |

## 2. Snapshots rebuilt: byte-identical to the freeze package

`scripts/build_cfb_eval_snapshots.py` on branch
`freeze/cfb-four-family-evaluation-v1-20261014` @ `5b18b72b`:

| Snapshot | Freeze package file SHA-256 | Rebuilt here |
|---|---|---|
| results (11,495 games) | `830ebe5a0262b26b…586389` | **identical** |
| lines | `72c4476f78f7b1b8…e0c578` | **identical** |
| directory (1,840 ids) | `503d29b60e05ff73…a3b6` | **identical** |

**Environment disclosure:** this sandbox has no PyPI access, so pyarrow was
unavailable. The pinned parquet (SHA-256-verified by the builder) was
decoded with hyparquet (pure JS, cloned from GitHub) through a one-file
`pyarrow.parquet` shim. The **directory snapshot is content-addressed**.
Its byte-identity with the freeze package proves this decode equals the
original pyarrow decode.

## 3. Independent recount (raw sources only; imports nothing from the repo)

`recount_independent.py` (this directory) reads only the raw schedule CSVs,
the decoded team table and the bound `fbs_membership_overrides`:

| Quantity | Freeze package (R3) | Independent recount |
|---|---|---|
| Decided games 2013–2025 | 11,495 | **11,495** |
| Illinois fixtures excluded | 511 | **511** |
| Non-FBS opponent excluded | 1,446 | **1,446** |
| Unresolved teams excluded | 2 | **2** |
| **Population (Path A, as frozen)** | **9,536** | **9,536** |
| Burn-in 2013–2020 | 5,754 | **5,754** |
| Folds 2021/22/23/24/25 | 739/747/757/765/774 | **739/747/757/765/774** |

R3 reproduces exactly.

## 4. Path B — the reconciled count, with one finding

Population by ESPN `season_type`: **9,032** regular (`2`), **503**
postseason (`3`), and **1 game with a blank `season_type`**.

- **The blank-type game:** ESPN `game_id 333200213`, 2013 week 12,
  2013-11-16, Purdue at Penn State (Beaver Stadium), 21–45, STATUS_FINAL.
  This is a regular-season Big Ten game. The source omits its
  `season_type`, and it is also wrong on `conference_competition`
  ("false"). It falls in **burn-in** (2013), so it is never scored.
- **So the claimed 9,033 = 9,536 − 503 is correct** only if this game is
  classified as regular season. It is, factually. But the frozen rule must
  say so explicitly: *"a game with blank season_type is classified by its
  week/date against the season's regular-season calendar"*, or an explicit
  per-game override listing `333200213`. Otherwise a strict
  `season_type == 2` filter yields **9,032**.
- **This needs your ruling (one line):** count `333200213` as regular
  season (→ **9,033**), or exclude it as unclassified (→ **9,032**). It
  affects burn-in only. The scored folds are identical either way.

**Path B scored folds (regular season only):**

| Fold | Path A | **Path B** | Removed (postseason) |
|---|---|---|---|
| 2021 | 739 | **699** | 40 |
| 2022 | 747 | **706** | 41 |
| 2023 | 757 | **717** | 40 |
| 2024 | 765 | **721** | 44 |
| 2025 | 774 | **730** | 44 |
| Pooled | 3,782 | **3,573** | 209 |
| Burn-in | 5,754 | **5,459 or 5,460** (blank game) | 295 |

Every Path B fold stays above the frozen 500-game population floor. The
per-family **matched** counts are restated under Path B in §7.

## 5. What remains before the execution GO (nothing here consumes Attempt 1)

1. **Your one-line ruling** on game `333200213` (9,033 vs 9,032).
2. **Path B config change:** set `population_rule` to the
   regular-season-only rule in the draft config at freeze time. The
   matched counts are already restated in §7 (NOT_RUN); a separate
   verifier still has to reproduce them.
3. **R1** (Bovada descriptive-only comparator) and **R2** (13-program FBS
   override table): reviewed and independently reproduced. The override
   table is a public-record list, checked line by line.
4. Immutable freeze identity (`freeze_sha` set at the freeze commit),
   governance registration, and a fresh all-green hosted CI on the exact
   head.
5. **Your separate execution GO.**

## 6. R2 spot-check: FBS override table vs the public record

All 13 bound overrides match the public NCAA FBS membership record:

- **Moved up from FCS, with their FCS seasons:** App State, Georgia
  Southern and Old Dominion (FBS from 2014); Charlotte (2015); Coastal
  Carolina (2017); Liberty (2018); James Madison (2022); Sam Houston and
  Jacksonville State (2023); Kennesaw State (2024).
- **FBS seasons for programs the table lists as FCS:** Delaware and
  Missouri State (2025); Idaho (2013–2017, before dropping to FCS in
  2018).
- **No omissions found among the 2013–2025 transitions.** UAB's
  2015–2016 hiatus has no games, so it needs no override. Georgia State,
  South Alabama, UMass and the other pre-2013 movers are already FBS in
  the table for every season in the window.

This is a reviewer's check against public knowledge, not a ruling. R2
ratification remains Isaac's.

## 7. Path B dry-run restatement of matched counts (NOT_RUN, zero probabilities)

`pathB_dry_restatement.py` runs the frozen bindings loaders and
`build_dry_run_manifest` on the rebuilt, byte-verified snapshots. It
filters games to the regular season and does not edit the draft config.
Each run asserts `probabilities_computed == False` and
`attempts_consumed == 0`. Output: `pathB_dry_restatement_results.json`.

**Control:** Path A reproduces the freeze package's published matched
counts exactly (pooled ML 3,335 / spread 3,773 / total 3,773; per-fold
646/633/691/682/683 ML).

| Fold | Pop (B) | ML matched (cov) | Spread | Total | Team total |
|---|---|---|---|---|---|
| 2021 | 699 | 629 (90.0%) | 698 | 698 | 0 |
| 2022 | 706 | 617 (87.4%) | 702 | 702 | 0 |
| 2023 | 717 | 662 (92.3%) | 717 | 717 | 0 |
| 2024 | 721 | 649 (90.0%) | 720 | 720 | 0 |
| 2025 | 730 | 653 (89.5%) | 730 | 730 | 0 |
| **Pooled** | **3,573** | **3,210** | **3,567** | **3,567** | **0** |

- Every fold passes the 500-game floor (lowest is 617, ML 2022) and the
  0.75 coverage floor.
- Every pooled count passes the 2,500 floor.
- Team totals remain unscoreable historically (0 lines; forward-only, as
  already on record).
- The blank-type game is in 2013 burn-in, so the scored counts are
  identical for 9,033 vs 9,032.
