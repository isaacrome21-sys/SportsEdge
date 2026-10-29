# NHL_ATTEMPT2_V1 — freeze package (2026-10-28)

**Status: FREEZE PACKAGE — DRAFT. This package authorizes nothing,
freezes nothing, pins nothing, and starts no clock.** It prepares a
future freeze act for the NHL attempt-2 sides/totals construction
(`NHL_ATTEMPT2_V1`) the way the CBB freeze packages (PRs #2903/#2904)
prepared theirs: it transcribes the forward terms the design actually
fixes, audits them for freeze completeness, names every gap and every
owner decision, and records the registry and multiple-testing state
as of the package date. **Freeze eligibility is NOT established by
this package.** Two independent gates stand in front of any freeze
act, and this package closes neither:

1. **The Stage A verdict (Nov 30, 2026).** Stage B — the forward
   market validation this freeze would arm — runs only if the locked
   home-ice v2 Stage A test passes on its own one-shot terms
   (design, Stage B protocol: "Precondition: Stage A verdict = PASS
   on Nov 30, 2026"). If Stage A fails, "Stage B below does not run
   and this construction returns to design." A freeze executed for a
   construction that returns to design is a dead record; the
   sequencing question this creates is named as item **S-1** in
   `DECISIONS_AND_READINGS.md` and is the owner's to settle.
2. **The owner's adoption and freeze acts.** The gaps in
   `PREREG_TERMS_RECORD.md` (G-1…G-4) can be cured only by a design
   amendment adopted by the owner under its own independent review;
   the decisions in `DECISIONS_AND_READINGS.md` (D-1 home-ice,
   D-2 OT/SO sourcing) are the owner's; the freeze itself is a
   separate prospective act, recorded only at its PR's merge
   (`FREEZE_ACT_CHECKLIST.md`).

## Scope

This package covers **NHL_ATTEMPT2_V1 sides/totals only** (moneyline,
puck line, totals, regulation-only outputs of the attempt-2
construction, design PR #2839,
`research/activation_designs_20261027/NHL_SIDES_TOTALS_DESIGN.md`).
**NHL_TEAM_TOTAL_DIST_V1 is a separate family** with its own Stage B
protocol inside the same window and its own named gaps
(G-TT-1…4, `research/nhl_team_totals_build_20261028/SCREEN_REPORT.md`);
it is gated on the same Stage A verdict and needs its own package.
Nothing here speaks for it. Stage A itself (the locked home-ice v2
pre-lock, `docs/research/nhl_home_ice_v2_prelock.md`) is a different,
locked construction: cited, never amended, never re-scored by
anything in this package.

## Contents

| File | What it is |
|---|---|
| `PREREG_TERMS_RECORD.md` | The Stage B terms the design fixes (transcribed), then the completeness audit: findings **G-1** (no pick rule — the design's promised ROI is undefined), **G-2** (paired-significance construction unspecified), **G-3** (no close-validity rule), **G-4** (no minimum universe / insufficient-data disposition), **F-1** (no forward runner), **G-5** (freeze-owed constants still unpinned). Draft completion proposals are given in sibling-frozen-form where a form transfers, each labeled **OWNER ADOPTION REQUIRED**; no proposal in this package is in force. |
| `DECISIONS_AND_READINGS.md` | Owner decisions **D-1** (home-ice: venue-blind as drafted vs a declared home term by amendment), **D-2** (OT/SO shares: source from NHL API design ground truth vs declare neutral constants), sequencing item **S-1** (freeze before vs after the Nov 30 verdict), and the build's readings **R-1…R-7** that the freeze act must confirm or correct. Options and consequences are stated; no option is chosen here. |
| `FREEZE_ACT_CHECKLIST.md` | The future act's contents and closing sequence, mirroring the CBB checklists; the registry result (no collision); the multiple-testing k computed for this package (k = 9, inputs listed, recomputable at the act). |
| `CONFIG_DRAFT.json` | The framework config the act would install, in the CBB packages' draft form. Ships inside this package only; registers nothing. Framework-default gate values it carries are flagged in its own note as carrying **no preregistration force** (gaps G-3/G-4). |
| `SPEC_HASHES.txt` | sha256 pins, computed on main `aed769f75`, for the design, build and screen records, the construction and constants modules, the family tests, the MoneyPuck admission record, and this package's own documents. |

## State of the sequence (Oct 28, 2026)

| Stage | Act | State |
|---|---|---|
| Design + preregistration draft | PR #2839 (`NHL_SIDES_TOTALS_DESIGN.md`) | MERGED |
| MoneyPuck admission (design blocker, since closed) | PR #2859 (`research/nhl_moneypuck_admission_20261028/ADMISSION_RECORD.md`) | MERGED — attempt-2 input only; no cross-vintage pooling |
| Construction build + dispersion build-fit | PR #2877 (`research/nhl_attempt2_build_20261028/`) | MERGED — build only; screen NOT_EXECUTABLE by design |
| NHL team totals build (separate family) | PR #2878 | MERGED — forward Stage B only, gated on Stage A |
| Stage A (locked home-ice v2) | Pre-lock Sep 29, 2026 | RUNNING on the calendar; verdict Nov 30, 2026 |
| Design amendment (gaps G-1…G-4; decisions D-1/D-2) | Owner act with independent review | **NOT EXECUTED — BLOCKING** |
| Forward runner build + NON_COUNTED landing check | Finding F-1 | **NOT BUILT — act prerequisite** |
| Freeze package | This PR | THIS PR (draft) |
| Freeze act | Separate future PR (checklist) | NOT EXECUTED — also gated on the Stage A verdict per S-1 |
| Stage B window | Dec 1, 2026 – Jan 31, 2027; one look Feb 1, 2027 | NOT OPEN |

## Standing law this package does not bend

PAPER / 0u; no wager execution; no lowered thresholds; no frozen term
of any other family touched; FAILED constructions stay retired (the
attempt-1 no-edge verdict and the retired #1249/#1253 generation stand
unchanged); verification accrues forward only, no backfill; xG is
never pooled across the 2025/2026 vintage boundary without a declared
treatment (the declared treatment stands:
`SINGLE_VINTAGE_ONLY:rebuilt_2026_27`); amendments after a freeze are
new versions with their own preregistrations, scored forward only.
