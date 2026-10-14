# R3 recount — remote reproduction package

**Purpose.** The R3 recount for `CFB_FOUR_FAMILY_EVALUATION_V1` was
published on this branch (`docs/RECOUNT_R3.md`, `docs/recount_r3.py`,
`docs/recount_r3_raw.py`) with a reported result of **144/144 checks
matching**. The owner's review (PR #2258, Oct 14) could not independently
certify that result from the remote evidence, for two stated reasons:

1. the published scripts depend on local workspace paths (the staging
   sources under `~/workspace/tmp/cfbbind/sources/`, a config file in
   `/tmp`);
2. they reference the frozen commit abbreviations `bfba59f3f` /
   `b68114e0f`, which are local-only commit objects that GitHub cannot
   resolve.

This directory removes both blockers:

- `recount_repro.py` — a self-contained merge of the two published
  recount scripts (all check logic verbatim; see its docstring) that
  takes `--sources-dir` / `--snapshots-dir` / `--config`, **hash-verifies
  every input against the frozen pins before counting** (any mismatch
  aborts, naming the file, exit 2), and prints the same summary lines as
  the originals plus a combined total.
- **Every input file is published on this branch** in chunked base64
  form under `sources/` and `snapshots/` (manifest:
  `PUBLISHED_INPUTS_MANIFEST.json`; reassembly:
  `reassemble_inputs.py`). Nothing in the recount's input set remains
  holder-only.
- §2 below establishes the candidate's frozen identity **without** the
  local commits, from artifacts already on GitHub.
- `REPRO_RUN_OUTPUT.txt` — the full output of the verification run
  performed with exactly this package and procedure (144/144).

This package is **additive**: `FREEZE_PACKAGE.md`, the candidate files,
`docs/RECOUNT_R3.md`, `docs/ERRATUM_POPULATION.md`, and the two original
recount scripts are byte-untouched. It contains no ruling language: it
establishes reproduction feasibility only. The postseason Path A/B
decision remains the owner's.

---

## 1. Input inventory

All 20 files the recount reads (or, for the parquet, that the frozen
bindings build consumed to derive the directory snapshot). SHA-256 and
size are the frozen pins; the recount verifies them before counting.

### 1a. Raw sources (phase 2 re-derivation; also the bindings build's inputs)

Origin for all three groups: public SportsDataverse repositories. The
lines archive and the team table are **commit-pinned** raw URLs recorded
in the frozen bindings config itself (`raw_url` / `upstream_commit`), so
the bytes at those URLs are immutable. The schedules come from a GitHub
**release** whose assets are periodically refreshed by the publisher's
automation (piggyback); the frozen pin — not the live asset — is the
identity, and any holder whose download differs from the pin should use
the branch-published parts (§3, route B), which are the pinned bytes.

| File | Size (B) | SHA-256 | Public origin |
|---|---|---|---|
| `schedules/cfb_schedule_2013.csv.gz` | 29,822 | `b4fa660289b3ee618f6a5b398701ac5285b0bcfa8b7dacb36a5b898ef4752a07` | release below |
| `schedules/cfb_schedule_2014.csv.gz` | 30,304 | `e414f7ff0c31f6a23320fa7fb6e0fad0ee7f54fcda7e085ae32102c754dd3562` | release below |
| `schedules/cfb_schedule_2015.csv.gz` | 30,382 | `f6efc44b1dfa424ad094cb609a3f221bad90a3ce942d5e7259f79921d3efd5ab` | release below |
| `schedules/cfb_schedule_2016.csv.gz` | 30,526 | `b06b040c38aa8b1411b5bdfafb3d37fa6d237e2de667eebccac8506354d59b9b` | release below |
| `schedules/cfb_schedule_2017.csv.gz` | 30,718 | `3e295d03ab816fd1c03955e8932fe089a88ffebbcddf768bb4b617a6c0a3f7ca` | release below |
| `schedules/cfb_schedule_2018.csv.gz` | 31,227 | `2cbaa0c3b785f0d2d7d4a7614bdc2a30abfb6f5bbeee3e7ed567c4dafa7287d3` | release below |
| `schedules/cfb_schedule_2019.csv.gz` | 31,096 | `e85fa562d7d2065b1ac3d384bb83785619c8adbe6c4b586f43402ae428c6eaf1` | release below |
| `schedules/cfb_schedule_2020.csv.gz` | 22,191 | `64cc43834ee7da1e6b6e65362b45dab362c3748d9b42ce1224561f14634f14e4` | release below |
| `schedules/cfb_schedule_2021.csv.gz` | 31,113 | `0fd757f0152e93cb1e03cd0f1038a5c2a7626e48589d194d2f80d38135d2c869` | release below |
| `schedules/cfb_schedule_2022.csv.gz` | 31,466 | `1053ceb10a0d73b5e04bc234cef449262db7ade8e622d389db2756675c7cb3c5` | release below |
| `schedules/cfb_schedule_2023.csv.gz` | 31,460 | `ba9743c99636ed04dcb6177088e44c7db19cd93eb2ad7d9977d05e392b62aefd` | release below |
| `schedules/cfb_schedule_2024.csv.gz` | 33,299 | `4fb9c661e76a9ecc3748878a7e5d6a3aa9cb9b6c82140e44a1812151e6e16645` | release below |
| `schedules/cfb_schedule_2025.csv.gz` | 33,168 | `9666c50349255005ea1912aba26851eb8184602a7b79580176990807d6f1a9ff` | release below |
| `cfb_line_odds.csv.gz` | 7,047,701 | `7ae899d9035750dccf22470d7923087a2659052aeb37a44204c35fbf6bf38d4d` | commit-pinned URL below |
| `cfb_team_info_2024.parquet` | 133,323 | `503549b9b3c4b5c40accbb58d8ebf38d6555f369a883be4d42dcee27cfbda808` | commit-pinned URL below |

- Schedules: GitHub release **`espn_cfb_schedules`** (release id
  101941072) of `sportsdataverse/sportsdataverse-data`; asset URL
  pattern:
  `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_schedules/cfb_schedule_<season>.csv.gz`.
  Per the frozen config, the 2013–2020 pins were taken from the GitHub
  release API digest (`GITHUB_RELEASE_API_DIGEST`) and the 2021–2025
  pins from a data-branch manifest (`IN_REPO_DATA_BRANCH_MANIFEST`;
  recorded data-branch commit
  `40f164b454ef9a36e9b7dcfca7a6b1972732c3ce`).
- Lines archive:
  `https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/f5a05dc815951b8dbe18961a824f34cf154dfa61/betting/csv/cfb_line_odds.csv.gz`
  (git blob SHA-1 at that commit: `fe568cf1ef50794c80fdbbbff6a8e1061f76528e`).
- Team table:
  `https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/f5a05dc815951b8dbe18961a824f34cf154dfa61/team_info/parquet/cfb_team_info_2024.parquet`
  (git blob SHA-1: `c94db36d0d3835c1b6fce78cafa0e68f328124dd`).
  Role, stated plainly: this parquet is the bindings build's input for
  the team-directory snapshot. The recount scripts do **not** read
  parquet rows — the directory is verified as the frozen snapshot
  artifact below (the original recount's disclosed residual stands: the
  parquet→directory row mapping is not re-verified by the recount;
  doing so needs a parquet reader and is outside this package).
  `recount_repro.py` does hash-verify the parquet file itself before
  counting, as part of the input set.

### 1b. Frozen snapshot corpus (phase 1; also phase 2's comparison target)

These five files are artifacts of this freeze, produced by the
candidate's `scripts/build_cfb_eval_snapshots.py` from the §1a sources.
They have no third-party public origin, so their provenance entry is
this branch: they are published here in chunked form (§3), and their
hashes below are the pins the published recount itself carries
(`EXPECTED_FILE_SHA256` in `docs/recount_r3.py`, plus the manifest hash
recorded for this package).

| File | Size (B) | SHA-256 | Content id (`snapshot_id`) |
|---|---|---|---|
| `results_snapshot.json` | 4,515,975 | `830ebe5a0262b26b8ebc62b6075a7bf70eb814c99025b1ea94ab9596ae586389` | `151774e84e45d8348c9e36c87d390d720c059023b190cf022bd16375b20d1195` |
| `lines_snapshot.json` | 1,921,452 | `72c4476f78f7b1b82919df97a1c02f781260969f334ab5f7185c8b0e42e0c578` | `9cc966b57db5d8b61fc644ceab587ab90f7d6bef576540479503ab8607a7d7b5` |
| `directory_snapshot.json` | 179,129 | `503d29b60e05ff73fb0997eba83b8dcd908a510415737674bb621d2e93b9a3b6` | `764a32c87688b6e56716b889f3f943150037880fbbf36c8d9a37419894d27e31` |
| `SNAPSHOT_MANIFEST.json` | 8,335 | `3860cca7393bae68faee110a43c2753b0807a61c0025387606e58cfd11e82b99` | — |
| `DRY_RUN_MANIFEST.json` | 13,345 | `d6a1e30a1cd6c4780833ccafd35cb2ace15da73ecd4b5c913f024861f4c2bb6d` | — |

**Why the snapshots are transported, not regenerated.** The builder
derives the dry-run manifest's `engine_source_commit` from the build
checkout's `git rev-parse HEAD`, and it requires a parquet reader
(pyarrow) for the team table. A clean-checkout reproducer applying
patches (§2) cannot arrange for HEAD to equal the harness commit, so
byte-exact regeneration of `DRY_RUN_MANIFEST.json` is **not** claimed.
The frozen artifacts themselves are transported byte-exactly and are
hash-verified by the recount before use — the same trust basis the
original recount ran on.

---

## 2. Frozen identity without the local commits

The candidate (`CFB_FOUR_FAMILY_EVALUATION_V1`) is identified at
**patch + blob level**, from GitHub-resolvable artifacts only:

- **Base commit** `655715907d101052bfc7cb3357f1442db82d8d8b` — an
  ancestor of `main` (Oct 13 main head), resolvable on GitHub.
- **Harness patch** `docs/cfb_four_family_evaluation_v1_harness.patch`
  (published on this branch), SHA-256
  `841b0a80893739a9b6fa7c4b988dfe7315cc087545d40a66ceb39b059683c44e`.
- **Bindings patch** `docs/cfb_four_family_evaluation_v1_bindings.patch`
  (published on this branch), SHA-256
  `1ef56cb795c3c2334394ddbee7324142db552f20883aaead93f082b2278e60ca`.

Applying the harness patch, then the bindings patch, to the base tree
yields exactly these 7 files (verify with `git hash-object <file>`;
values are git blob SHA-1):

| File | Blob SHA-1 |
|---|---|
| `config/research/cfb_four_family_bindings_v1.json` | `08739dd982fb252294f25f58d73259d3faba8c99` |
| `config/research/cfb_four_family_evaluation_v1.json` | `01d15bb0f48cfd6de0c88051870cf14ae51c63b2` |
| `scripts/build_cfb_eval_snapshots.py` | `4b60cccf0c8297af574175cbd6d5ed8a9edea8fd` |
| `sportsedge/research/cfb_four_family_bindings_v1.py` | `ccb33da10ec3852a1b5d098f017a00212fed8f0b` |
| `sportsedge/research/cfb_four_family_evaluation_v1.py` | `140e6d1b61cc9379867679c74ce1b7f8221fc7a5` |
| `tests/test_cfb_four_family_bindings_v1.py` | `5509668cce195ee8064b1ac480ce82bb2e49db8d` |
| `tests/test_cfb_four_family_evaluation_20261013.py` | `d0aa7235676bed9626bf433d73e41eee448c09ca` |

The bindings config the recount consumes is the first of these
(9,775 B; file SHA-256
`ed10c50081bff54da7113b72a488c9a6b03444e0bb46e7e2614fc3b374c0b4fc`).

**Plain statement about the abbreviations.** `bfba59f3f`
(full `bfba59f3fa563c07ec8934025a113cfbe3d5353b`) and `b68114e0f`
(full `b68114e0f3a554ac6f02e9a15394b7631f1c5206`) are the *local commit
objects* whose trees the two patches successively produce. Those commit
objects were never pushed (the available push path composes commits
server-side and cannot mint chosen commit SHAs), so GitHub cannot
resolve them, and resolving them is **not** part of the identity claim:
the claim is that base + the two published patches yield files
blob-identical to the candidate's, which §3 step 2 verifies directly.

---

## 3. Step-by-step reproduction

Prerequisites: `git`, Python 3 (standard library only). No SportsEdge
code is imported by the recount.

```bash
# 0. Clone and take this branch's reproduction directory.
git clone https://github.com/isaacrome21-sys/SportsEdge.git
cd SportsEdge
git checkout freeze/cfb-four-family-evaluation-v1-rederivation-20261014
cp -r docs/reproduce /tmp/reproduce          # scripts, manifest, parts

# 1. Re-derive the candidate tree from the base + published patches.
git checkout 655715907d101052bfc7cb3357f1442db82d8d8b
git show freeze/cfb-four-family-evaluation-v1-rederivation-20261014:docs/cfb_four_family_evaluation_v1_harness.patch  > /tmp/harness.patch
git show freeze/cfb-four-family-evaluation-v1-rederivation-20261014:docs/cfb_four_family_evaluation_v1_bindings.patch > /tmp/bindings.patch
sha256sum /tmp/harness.patch /tmp/bindings.patch   # must equal §2 values
git apply /tmp/harness.patch
git apply /tmp/bindings.patch

# 2. Verify the candidate identity (blob level).
git hash-object config/research/cfb_four_family_bindings_v1.json
#   -> 08739dd982fb252294f25f58d73259d3faba8c99  (full table: §2)

# 3. Obtain the inputs — route B (recommended): reassemble the exact
#    pinned bytes published on this branch. (Route A: download the §1a
#    files from their public origins into the same layout and let
#    step 4's hash verification judge them; the §1b snapshots exist
#    only via route B.)
python3 /tmp/reproduce/reassemble_inputs.py --out /tmp/repro-inputs

# 4. Run the recount. It hash-verifies all 20 inputs against the
#    frozen pins before counting; any mismatch aborts, naming the file.
python3 /tmp/reproduce/recount_repro.py \
  --sources-dir   /tmp/repro-inputs/sources \
  --snapshots-dir /tmp/repro-inputs/snapshots \
  --config config/research/cfb_four_family_bindings_v1.json
```

Expected output (summary lines):

```
INPUT VERIFICATION: 20 files hash-verified against frozen pins
CHECKS: 112 total, 112 match, 0 MISMATCH
PHASE-2 CHECKS: 32 total, 32 match, 0 MISMATCH
TOTAL CHECKS: 144 total, 144 match, 0 MISMATCH
```

(exit code 0; the `CONFIG:` line preceding them reports the config
file's SHA-256, `ed10c50081bff54da7113b72a488c9a6b03444e0bb46e7e2614fc3b374c0b4fc`.)

---

## 4. Verification performed for this package

On Oct 14, 2026, the package author executed §3 end-to-end from a clean
worktree: patches extracted from this branch (SHA-256s matching §2),
applied to the base, all 7 `git hash-object` values matching the §2
table; inputs reassembled from the published parts; recount run against
the candidate tree's own config file. Result: **144/144, exit 0** —
full transcript in `REPRO_RUN_OUTPUT.txt`. The phase DETAILS blocks of
the merged script were additionally compared against the original two
scripts' outputs on the same corpus and are deep-equal (the merge
changed plumbing only, never a check).

Published-parts format: each logical file is split into 75,000-byte raw
chunks (201 parts total across 20 files); each part file holds the
chunk's base64 encoding on a single line. `PUBLISHED_INPUTS_MANIFEST.json`
records every part's SHA-256 and every reassembled file's SHA-256 and
size; `reassemble_inputs.py` verifies parts before decoding and files
after reassembly, aborting on any mismatch.

## 5. Scope

This package makes the *recount* independently reproducible from
GitHub-only artifacts plus public sources. It does not certify the
freeze, ratify any population definition, or authorize any evaluation
execution; the postseason question documented in
`docs/ERRATUM_POPULATION.md` is untouched and remains the owner's
ruling to make.
