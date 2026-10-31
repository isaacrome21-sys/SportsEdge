# Amendment 2 machinery — build record (Gate 1)

Built 2026-10-31 on branch `build/cbb-amendment2-machinery-20261030`
from main `325d0123f7aeaebd31fb5cf975872e1ab687e858`. This record is
builder-reported; independent clearance by Rocky follows. **Nothing
in this build freezes either family, starts a clock, or flips any
state flag** — both runners still refuse every counted entry point
with their NOT_FROZEN codes. The build changes capability, not state.

## What was undefined before

The #2907 forward runners predated the adopted Amendment 2
(adoption record `AMENDMENT_2_ADOPTION_RECORD.md`, main merge
`ea9966517`). Every priced record was stamped
`PICK_RULE_UNDEFINED` / `INTERVAL_CONSTRUCTION_UNDEFINED_GAP_G2` /
`CLOSE_RULE_UNDEFINED_GAP_G3`: no pick designation existed, no §3
close-validity rule existed, and no §2 verdict machinery existed in
production code — the pinned toy-slate verifier
(`verify_amendment2_toy_slate.py`) proved computability only. A
freeze struck on those pins would have frozen a clock that could
never be verdicted.

## What the build implements

New module `sportsedge/cbb_amendment2_machinery.py` (shared by both
families; the families' preregistrations expressly do not use the
generic forward-validation framework's CLV-only verdict):

- **§1 pick designation** — gap = model value − captured line at the
  adopted thresholds SPREAD 2.2 / TOTAL 3.5 / TEAM_TOTAL 2.1;
  PICKED / PASSED / GAP_ZERO; the designated side is the side the
  gap favors (SPREAD: the captured line is the away spread, i.e. the
  amendment's market-implied margin). Both runners now stamp `gap`,
  `designated_side`, `classification`, `pick`, `pick_threshold`,
  `pick_rule = AMENDMENT_2_S1_PICK_RULE`,
  `interval_construction = AMENDMENT_2_S2_GAME_CLUSTER_BOOTSTRAP_10000_SEED_20261028`,
  `close_rule = AMENDMENT_2_S3_CLOSE_VALIDITY`, and verify the
  adopted amendment text by sha256 at construction
  (`amendment_2_sha256` added to each runner's EXPECTED_PINS).
- **§3 close-validity** — judged in the amendment's order: close
  exists → two-sided → captured before tip and at most 60:00 before
  tip (exactly 60:00 is valid) → final among committed closes;
  moved rows classified only after validity, with direction recorded
  relative to the designated side; the >20% insufficiency share
  counts only NO_CLOSE_ROW / CLOSE_SINGLE_SIDED / CLOSE_STALE /
  CLOSE_NOT_PREKICKOFF; moved-bucket rule 1 (one-sided exact sign
  test at α/k) and rule 2 (>50% of PICKED rows moved ⇒
  INSUFFICIENT_CLOSE_DATA).
- **§2 verdict machinery** — accuracy leg per named market (paired
  absolute-error differences vs the SIMPLE baseline, game-cluster
  bootstrap 10,000 resamples, seed 20261028, nearest-rank bounds at
  level 1 − α/k); market leg per §1.3/§1.4 (ROI at flat 1 unit on
  the PICKED set at entry prices, pushes in the denominator; mean
  CLV over PICKED rows with a valid same-line close; for the
  efficiency family the picked set is pooled across SPREAD+TOTAL
  per the adopted Flag 1 settlement); verdict PASS / FAIL /
  INSUFFICIENT_CLOSE_DATA exactly per §2.
- **§4/§5 review discipline** — the gated entry
  (`evaluate_forward_test`, wired into both runners'
  `run_forward_test`) refuses once a review is recorded; before the
  first slate close with ≥ 40 distinct graded games it returns
  REVIEW_NOT_DUE with operational counts only — no accuracy, CLV,
  or ROI figure is computed or returned (no interim looks); at the
  gate it uses k = max(k at freeze, k at verdict).

## Verification

- The machinery reproduces the amendment's own §7 toy-slate
  quantities through the production module (both families: ROI,
  mean CLV, missing shares, moved-bucket sign test, and the pinned
  bootstrap confidence intervals) — `tests/test_cbb_amendment2_machinery.py`,
  23 tests, incl. threshold boundaries, close-validity boundaries
  (60:00 exact, single-sided, stale-before-moved precedence),
  moved-direction per side/market, insufficiency/rule-1/rule-2
  boundaries, gate behavior at 39/40 graded games, a constructed
  PASS and FAIL, one-review refusal, and k-governs.
- CBB test surface: **195 passed before → 219 passed after**
  (+23 machinery tests, +1 team-total designation test), 21
  subtests passed, zero regressions.
- Both landing checks re-run and PASS (12 games / 24 records each),
  including a new Amendment 2 machinery exercise (synthetic
  same-line closes, labeled as such): gate shut at 12 graded games,
  quantities deterministic across two runs, designations consistent
  on every record. Samples regenerated (record content changed).
- Adversarial pass: bool/NaN/string payloads in rows, finals, and
  closes all refuse fail-closed; two gaps found and fixed during
  the build — duplicate row ids now refuse `DUPLICATE_ROW_ID`, and
  a TEAM_TOTAL row without a HOME/AWAY venue refuses
  `ROW_RECORD_INVALID` (its subject points are unreadable without
  one).
- PR gates: ruff `--select E9,F821,F822,F823,F811` clean on all
  touched Python files; dependency surface unchanged and equal
  (pyproject `dependency-groups.dev` == `requirements-test.txt`,
  11 == 11; no new dependency). Freeze-coverage: **NONE** — none of
  the 13 touched paths is covered by any bundle in
  `config/freeze_reconciliation_registry_v1.json`
  (`_covered_change` over all 11 bundles).

## Interpretation decisions (amendment text underdetermined these)

1. **Disposition precedence** per row: VOID >
   RESULT_UNAVAILABLE > close-failure codes (in §3.1 check order) >
   LINE_MOVED > GAP_ZERO > PUSH > VALID_SAME_LINE. The §3.3 share
   is computed from the *factual* close state, not the single
   disposition field, so a GAP_ZERO row with a failed close still
   counts toward the share exactly as §3.3's row set requires.
2. **VOID and RESULT_UNAVAILABLE rows are excluded from the share's
   numerator and denominator** (basis: §1.4 "excluded from every
   leg"); GAP_ZERO rows remain in the denominator.
3. When the §3.3 share and §3.2 rule 1 both trip, the recorded
   outcome is INSUFFICIENT_CLOSE_DATA, with the market leg still
   reported failed on rule 1.
4. The ordinary settled disposition is named `VALID_SAME_LINE` (the
   amendment names no code for the valid case).
5. A structurally malformed close record (non-numeric line/price,
   unparseable timestamp) refuses the whole evaluation with
   `CLOSE_RECORD_INVALID` rather than earning a disposition
   (fail-closed, framework-style); a missing side price is the
   named CLOSE_SINGLE_SIDED.
6. No CLV interval is invented for §1.3's "interval reported
   alongside the market leg": the toy verifier — the
   adopted computability proof — computes none; the accuracy
   intervals appear in the same review record.
7. Pre-gate evaluations return operational counts only (see §4
   above); leg computation lives in `compute_review_quantities`,
   called by the gate only when due.
8. `evaluate_forward_test` recomputes each row's designation and
   refuses `ROW_CLASSIFICATION_MISMATCH` if a record's stamp
   disagrees — a pre-Amendment-2 `PICK_RULE_UNDEFINED` record
   therefore refuses rather than being silently re-designated
   (such rows were priced pre-machinery and never count).
9. k at the verdict is required; k at the freeze is optional; the
   gate uses the maximum (the larger governs).
10. Finals points are accepted as finite numbers rather than
    forced integers, so the toy slate's half-point finals flow
    through the same code path; real finals are integers.

## Files

| file | sha256 / note |
|---|---|
| `sportsedge/cbb_amendment2_machinery.py` | NEW — `57d1c1e398d580fef4167904762bc7ef5366b4c8d7917be66aef43654fbdcbe8` |
| `sportsedge/cbb_efficiency_forward.py` | `0982dc5114e996ecbb8db748e8a071d63dfc62a676c6b2a2d0ca4c728428ea0e` |
| `sportsedge/cbb_team_total_forward.py` | `31cd9e901c692dc6afdf0c5911e5f35b6b32f3a1f4b8023476c552fcde14f64d` |
| `tests/test_cbb_amendment2_machinery.py` | NEW — `e01688df79669f77e9fcbc526e76e34395929939dd4d46be1163cba4c74eea12` |
| `tests/test_cbb_efficiency_forward.py`, `tests/test_cbb_team_total_forward.py` | stamp assertions updated to the Amendment 2 designations |
| both `forward_landing_check_20261028/` packages | designation assertions + machinery exercise; `LANDING_CHECK.json` and `entry_records_sample.jsonl` regenerated |
