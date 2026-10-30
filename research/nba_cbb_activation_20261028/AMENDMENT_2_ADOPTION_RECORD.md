# AMENDMENT 2 — ADOPTION RECORD (CBB_TORVIK_EFFICIENCY_V1 and CBB TEAM TOTALS)

**Date:** 2026-10-30 · **Act:** owner-delegated adoption ·
**Status after this record:** Amendment 2 is **ADOPTED** for both
families. Both families remain **DESIGN ONLY — NOT FROZEN**;
nothing counts.

## The delegation

On Oct 30, 2026, Rocky presented Isaac with a prepared
two-decision packet — adoption of this amendment (CBB
Amendment 2, PR #2906) and of PGA Amendment 1 (PR #2896) — the
two amendment adoptions then outstanding in the owner-act
queue. Isaac answered in chat (~17:33 CT): **"Whatever you
suggest."** That answer delegates both decisions; Rocky ruled
**ADOPT BOTH**. This record is the CBB Amendment 2 act and its
reasons, executed under that delegation — the same pattern as
the Oct 29, 2026 de-vig ruling. The PGA Amendment 1 adoption
is a separate act with its own record; nothing here adopts it.
Isaac can reverse any part of this adoption with a word, and
reversal is a new record, not an edit of this one.

## What is adopted — the exact text

Amendment 2 as landed by PR #2906 (head
`04c1677d0105e59d7167ebdbbfefabaca2aa8741`, merged to main as
`5e043a26984f028acc8dc66a588a807cb7625158`, Oct 28, 2026),
adopted **as written** — no term altered, added, or removed
by this act:

- `AMENDMENT_2_DRAFT.md` — sha256
  `25be46029ca1933e1a2eb7d7aa6a858928f3879a254285e90a0b9bf1270d926a`
- `verify_amendment2_toy_slate.py` — sha256
  `b7ddeb9d04c962dbc23851fab45fa7aa431c86bb4aa8d8996c2d2e92fc054646`
- `amendment2_toy_slate_results.json` — sha256
  `f915d91576b5c979ad1a3a79b6fb5aae5d5ea0c9044973f203507b13d5af133a`

Per the amendment's §8, gaps **G-1, G-2, and G-3** in both
freeze packages' `PREREG_FINAL` §8 (efficiency: PR #2903; team
totals: PR #2904) stand supplied by the amendment. The
packages' pins are unaffected — frozen text is never edited;
the amendment supersedes by reference. The supplied machinery,
in summary (the amendment text governs, not this summary):

- **G-1 (§1):** gap and designated side per row; pick
  thresholds **SPREAD 2.2 / TOTAL 3.5 / TEAM_TOTAL 2.1**;
  CLV and ROI read on the PICKED set (see Flag 1 below).
- **G-2 (§2):** game-cluster bootstrap, **10,000 resamples,
  seed 20261028**, two-sided percentile interval at level
  **1 − α/k** (α = 0.05; k recomputed at the freeze act and
  at the verdict, the larger governs; k = 12 at package
  time); accuracy row set is close-independent.
- **G-3 (§3):** close = the lane's FINAL capture; validity
  (exists, two-sided, before tip, **≤ 60:00** pre-tip —
  exactly 60:00 valid) checked before any moved
  classification; moved-row bucket with the exact sign test
  at α/k and the >50%-moved rule; one disposition code per
  row; **>20% missing closes ⇒ INSUFFICIENT_CLOSE_DATA**.

## Flag 1 — SETTLED by this act

The adoption act was required to confirm or change one open
reading. **Settled: the efficiency family's market leg (CLV +
ROI) reads on ONE POOLED picked set across SPREAD and TOTAL**
— the amendment's own reading (§1.3: the leg's CLV figure is
the mean CLV over PICKED rows; §1.4: ROI is computed over the
same PICKED set). It is **not** read per market. For the
avoidance of doubt: the §2 **accuracy** leg remains
per-market by the amendment's own terms (one statistic for
SPREAD rows, one for TOTAL rows, each interval required to
clear) — that is a different leg and is not Flag 1.

## What this act does NOT do

- It **freezes nothing and counts nothing**: no clock starts,
  no capture is authorized by this act, and no game, row, or
  slate counts toward either family's test. `verified_play`
  remains false; PAPER / 0u throughout.
- Each family's **freeze act remains a separate prospective
  act** on its own checklist, with its prerequisites still
  owed and untouched by this adoption — including data gate
  (iii) (the Nov 1, 2026 capture-landing pre-check and
  opening-slate delivery receipts) and each family's §6
  machinery (evaluator/runner pins are fixed at its own
  freeze act). The forward runners (PR #2907) keep refusing
  NOT_FROZEN until then.
- It alters **no existing §5 criterion, threshold, or leg** of
  either family, and no term of the amendment itself
  (adoption as written, per the delegation ruling above).
- It does not adopt Amendment 3 (CBB 1H, PR #2913) or any
  other pending owner act (PGA Amendment 1, EFV2 freeze,
  NHL, NFL period, UFC prereg — all separate).

## Verification (this PR)

- Toy-slate computability re-verified at adoption: running
  `verify_amendment2_toy_slate.py` on main `8fa8d05e008c`
  reproduces `amendment2_toy_slate_results.json`
  **byte-identical** to the file pinned above.
- Freeze-coverage: the repo matcher
  (`scripts/reconcile_freeze_deltas.py::_covered_change` over
  every bundle in `config/freeze_reconciliation_registry_v1.json`)
  reports **NONE** for this record's path — the act touches no
  freeze-governed path, no code, no config, and no frozen
  text; it adds this one document.
- Dependency-surface gate: `pyproject.toml`
  `dependency-groups.dev` set equals `requirements-test.txt`
  exactly (11 = 11) on the base head; this act touches
  neither manifest.
