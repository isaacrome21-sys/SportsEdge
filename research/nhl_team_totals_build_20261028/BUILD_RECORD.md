# BUILD RECORD — NHL_TEAM_TOTAL_DIST_V1 construction (attempt 2)

**Status: BUILT (draft) — DESIGN ONLY family, NOT FROZEN, no clock, no
validation claimed.** Built Oct 28, 2026 from the merged design in
`research/activation_designs_20261027/NHL_TEAM_TOTALS_DESIGN.md`
(PR #2839), against main `ddd92a342`. The design screen was NOT run —
it cannot be; see `SCREEN_REPORT.md` in this directory
(NOT_EXECUTABLE, four named gaps).

## What was built

- `sportsedge/nhl_team_total_v1.py` — the construction: per-team goal
  distributions from the parent attempt-2 fit's rates, propagated
  through the parent's OT layer under an incl-OT settlement basis,
  priced against offered DK team-total lines.
- `tests/test_nhl_team_total_v1.py` — 29 family tests (all passing).
- `landing_check.py` / `landing_check_result.json` — build
  verification on disclosed stand-in rates: 12 priced rows (2 teams ×
  2 bases × lines 2.5/3.0/3.5), pmf sums = 1.0 within 1e-9 on all
  four team/basis grids, all four refusal paths firing with their
  named codes. NOT a screen, NOT counted.

## Design fidelity

- **No separate fit** (design, Construction bullet 2). The module fits
  nothing. It consumes the parent's fitted rates via the
  `ParentGameRates` record: regulation goal means after the parent's
  offense/defense combination and goaltender adjustment, the parent's
  dispersion fit, and the parent's OT win probability given a tie.
  The rate fit itself is the parent build's deliverable; when no
  parent artifact exists there is nothing to price a real game with,
  and this module does not invent one.
- **Settlement basis recorded, never assumed** (design, Construction
  bullet 1). `settlement_basis` is a required argument with no
  default; the caller reads it from DK's posted market rules at
  capture time; it is echoed onto every priced row; anything else
  refuses `SETTLEMENT_BASIS_UNRECORDED`.
- **Strictly-prior inputs** (MoneyPuck admission PR #2859 §2.2): the
  parent fit's newest consumed row must predate the game (same-day
  excluded) or pricing refuses `LOOKAHEAD_RISK` (the admission's own
  refusal code, §7).
- **xG vintage** (admission §4.1): rates spanning more than one xG
  vintage refuse `CROSS_VINTAGE_UNTREATED` unless a declared
  cross-vintage treatment token from the consuming preregistration is
  supplied.

## Readings (flagged for the freeze package; none changes a term)

1. **Distribution law shape.** The parent design names "Poisson with
   a dispersion parameter fit on design data" without fixing the
   dispersed family. This module mirrors the repo's frozen precedent
   (NFL_TEAM_TOTAL_DIST_V1): negative binomial, mean μ, variance
   (c·μ)², Poisson where variance ≤ μ. The dispersion value c is the
   parent fit's, carried on the rates record — never fitted here.
2. **OT propagation.** Parent design §2 bullet 2 fixes the principle
   (OT/SO mass added once, from the regulation tie probability). The
   per-team form implemented: exactly one goal added to the winner
   exactly when regulation ends tied, using the parent's win
   probability given a tie; mass conservation is proven in the module
   docstring and tested numerically (mean shift = P(tie) × w).
3. **Support cap.** Grids truncate below 1e-13 tail mass past the
   mode, hard-capped at 40 goals — a numerical bound, not a hockey
   claim; sums verified to 1.0 within 1e-9 in tests.

## Gates

- Family tests: 29 passed.
- Ruff gate (E9,F821,F822,F823,F811): clean on all new files.
- No dependencies added; no tracked file modified (purely additive:
  1 module, 1 test file, this research directory). Dependency parity
  untouched. Stdlib only.

## What remains before this family can be screened or priced

1. The parent's fitted-rate artifact (parent build's deliverable).
2. Stage A verdict, Nov 30, 2026 (locked; untouched by this build).
3. The Stage B capture window (Dec 1, 2026 – Jan 31, 2027) with
   paired DK team-total captures; DK team-total presence/depth on
   NHL event pages still to be confirmed in the first restart slate
   (design blocker, carried open).
