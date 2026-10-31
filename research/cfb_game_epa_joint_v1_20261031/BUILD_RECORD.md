# BUILD RECORD — CFB_GAME_EPA_JOINT_V1 frozen-implementation build

Checklist item 4 of the CFB EPA freeze path (see
`~/workspace/cfb-verify-audit-20261030/FREEZE_CHECKLIST.md`). This
build is the implementation only: **no freeze, no clock, no
validation claim.** The module ships with
`FREEZE_STATE = "DRAFT_NOT_IN_FORCE"` and every counted entry point
refuses `CFB_GAME_EPA_JOINT_NOT_FROZEN` until a freeze record
exists (checklist items 5–7 remain).

Governing text: `PREREG_DRAFT_V2.md` in this directory — a verbatim
copy of `~/workspace/cfb-verify-audit-20261030/PREREG_DRAFT_V2.md`,
sha256 `cf9a61bfbbbe0138ee670966ed0f8eb714a199fa133d033864b518d6554e94eb`
(byte-identical, verified at build time). CONFIRMED as the freeze
candidate by `PREREG_V2_CONFIRMATION.md` in the audit directory.

Built on main `975305ce3ae36746ff3d104aaff797ecf3e598cd`.

## Files

| Path | Role |
| --- | --- |
| `sportsedge/cfb_game_epa_joint_v1.py` | The implementation (§1 construction, PIT machinery, §2/§4 evaluator, runner) |
| `tests/test_cfb_game_epa_joint_v1.py` | 37 tests, incl. adversarial boundary coverage |
| `research/cfb_game_epa_joint_v1_20261031/PREREG_DRAFT_V2.md` | Governing prereg text (verbatim copy, hash above) |
| `research/cfb_game_epa_joint_v1_20261031/BUILD_RECORD.md` | This record |

No workflow files. No new dependencies. The records branch
(`records/cfb-game-epa-joint-v1`) is named in code as a constant
only and was **not** created.

## Section-by-section mapping to V2

- **§1 construction** — `load_sdv_pbp_rows` / `load_sdv_schedule_rows`
  (cfbfastR/SDV release form; exclusions tallied by reason, never
  silently dropped); `compute_features` builds per-team offensive/
  defensive EPA per play and per possession, success rate,
  explosiveness rate, pace, and a points-per-game family, each
  opponent-adjusted by iteration (`_adjust_family`: Jacobi updates,
  damping, weighted-mean recentering, fail-closed `NOT_CONVERGED`);
  `project_scores` blends the EPA channels with the points-only
  rating channel and splits HFA; outputs expected scores →
  margin/total + Φ-form probabilities from the construction's OWN
  SD constants (16.0/15.0 — the production priors 19.0/18.5 belong
  to the baseline and are not inherited). Preseason prior =
  prior-season final features through one shrinkage mechanism
  (`_blend_with_prior`, `PRIOR_PSEUDO_GAMES`, `PRIOR_SEASON_RETENTION`).
  No market line/price/close enters the construction anywhere.
- **§1 PIT discipline** — `build_snapshot` refuses any result not
  available at commit (`RESULT_NOT_AVAILABLE_AT_SNAPSHOT`,
  kickoff+24h proxy); `Snapshot.eligible_results/eligible_plays`
  apply the per-fixture 24h embargo; `PredictionLedger.commit`
  refuses commits at/after kickoff
  (`PREDICTION_NOT_COMMITTED_PREKICKOFF`) and duplicates; every
  record is sha256-hashed over its canonical payload and verified
  on reload and again inside the evaluator
  (`PREDICTION_HASH_MISMATCH`, `PREDICTION_NOT_COMMITTED`,
  `PREDICTION_RECORD_MISMATCH`).
- **§2.1 PM baseline** — `pm_project_season` is a faithful
  structural port of the PM branch of
  `scripts/evaluate_cfb_sdv_closes.py` (last-5 opponent-adjusted
  off/def, 3-game shrinkage toward 28, HFA 2.5, ≥3 prior games,
  prod SDs 19.0/18.5). The test suite proves exact equality against
  the real evaluator's `project_season` on synthetic seasons
  (0 mismatches, 1e-12 tolerance).
- **§2.2 market arm + close validity** — `classify_close` checks,
  in code order: no row → `NO_CLOSE_ROW`; a non-finite line raises
  `CLOSE_RECORD_INVALID`; a missing side → `CLOSE_SINGLE_SIDED`;
  present-but-invalid prices raise `CLOSE_PRICE_INVALID`; captured
  at or after kickoff → `CLOSE_NOT_PREKICKOFF`; captured more than
  60:00 before kickoff → `CLOSE_STALE` (exactly 60:00 is valid);
  otherwise the close is VALID. The four named missing reasons are
  `NO_CLOSE_ROW`, `CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`,
  `CLOSE_STALE`.
  Market probabilities come from `power_devig` (POWER_V1) in
  `sportsedge/devig.py` via `_devig_event_probability`, with a
  method assertion; the evaluator's ln 2 placeholder is never used
  as the market arm (a test proves the market log loss equals the
  POWER_V1 value and differs from ln 2). Missing-close games are
  excluded from the primary log-loss comparison in ALL THREE arms
  and retained in the MAE readout flagged `MARKET_REF_SDV` (SDV
  close as accuracy reference only).
- **§3 universe / exclusions** — `is_excluded_team` /
  `is_excluded_fixture`: exact-normalized-name backstop for the
  eight Illinois college programs + the owner block on Tennessee.
  Exact match only (`Northwestern State`, `Middle Tennessee` are
  NOT excluded; both covered by tests). An excluded fixture in a
  validation sample raises `EXCLUDED_FIXTURE_IN_SAMPLE` — a defect,
  not a row. Form 2 identity is enforced by the identity-mismatch
  refusal (`SAMPLE_GAME_IDENTITY_MISMATCH`).
- **§4 verdict** — `evaluate_validation_sample`: per market
  (SPREAD, TOTAL separately, never pooled); graded = non-push AND
  all three arms present after §2.2(c); primary metric mean log
  loss of the realized side on identical rows; PASS iff the
  construction is strictly below BOTH baselines AND each paired
  difference's game-cluster bootstrap CI lies entirely below 0 at
  1−α/k (10,000 resamples, seed 20261028, operation order mirrored
  from the CBB Amendment 2 machinery); k = max(k at freeze, k at
  verdict), unestablishable k refuses (`K_UNESTABLISHED`); minimum
  300 graded games per market before the single look; the look
  happens once (`VerdictLedger`; a second verdict attempt raises
  `VERDICT_ALREADY_RECORDED`); `INSUFFICIENT_MARKET_DATA`
  (>20% missing closes) and `SAMPLE_MINIMUM_UNMET` record nothing
  and do not consume the look; FAIL is recorded terminal
  (`terminal_if_fail`). CLV is computed and reported only
  (`_clv_summary`), never gates. Calibration (deciles + logistic
  slope) is reported only.
- **§5.3 constants** — every constant is a named module constant
  (table below), enumerated here in text.
- **§6 moneyline** — out of scope; no moneyline code exists in the
  module.
- **§7 hash set** — the freeze record shape (`FreezeRecord`)
  validates the freeze commit sha (40-hex), the prereg and
  implementation digests (64-hex), and k ≥ 1. Striking the actual
  pins is checklist item 5, not this build.
- **State safety** — `CfbGameEpaJointV1` without a freeze record:
  `run_verdict` and counted `commit_predictions` raise
  `CFB_GAME_EPA_JOINT_NOT_FROZEN`; `evaluate_validation_sample`
  with `freeze_record=None` raises the same. Research mode
  (`research_backtest`, research predictions) labels every output
  `RESEARCH_DESIGN_DATA_NOT_VALIDATION`, claims NONE, is
  production-ineligible, and never touches a verdict ledger or any
  records location. The research backtest's market arm is reported
  `NOT_AVAILABLE_SDV_CLOSES_CARRY_NO_PRICES`.

## Constants as built

| Constant | Value | Source |
| --- | --- | --- |
| `EMBARGO_HOURS` | 24 | V2 §1 (24h availability/embargo) |
| `ADJUSTMENT_TOLERANCE` | 1e-6 | V2 §1 "iteration to a stated tolerance" — value chosen here, flagged |
| `ADJUSTMENT_MAX_ITERATIONS` | 500 | build choice, fail-closed beyond |

*Amendment (Oct 31, 2026): raised to 20000 before the freeze — see FREEZE_RECORD.md §7. The value above is the as-built history.*
| `ADJUSTMENT_DAMPING` | 0.5 | build choice (Jacobi damping) |
| `PRIOR_PSEUDO_GAMES` | 3.0 | build choice (prior weight in games), flagged |
| `PRIOR_SEASON_RETENTION` | 0.65 | build choice (prior-season retention), flagged |
| `SUCCESS_TO_EPA` | 1.0 | build choice (success→EPA conversion), flagged |
| `EXPLOSIVE_TO_EPA` | 1.5 | build choice, flagged |
| `EXPLOSIVE_YARDS_THRESHOLD` | 20.0 yards | build choice (loader-level) |
| `EPA_CHANNEL_PLAY_WEIGHT` | 0.5 | build choice (per-play vs per-possession blend) |
| `POINTS_BLEND_WEIGHT` | 0.25 | build choice (points channel in the blend) |
| `HOME_FIELD_ADVANTAGE_POINTS` | 2.5 | construction's own HFA constant |
| `CONSTRUCTION_SD_MARGIN` | 16.0 | construction's own SD — a priori design constant, NOT fitted |
| `CONSTRUCTION_SD_TOTAL` | 15.0 | construction's own SD — a priori design constant, NOT fitted |
| `PM_SD_MARGIN` / `PM_SD_TOTAL` | 19.0 / 18.5 | V2 §2.1 pinned "prod" SDs |
| `PM_BASE` / `PM_HFA` / `PM_WINDOW` / `PM_SHRINK` / `PM_MIN_PRIOR_GAMES` | 28.0 / 2.5 / 5 / 3 / 3 | V2 §2.1 / evaluator identity |
| `ALPHA` | 0.05 | V2 §4 |
| `BOOTSTRAP_RESAMPLES` / `BOOTSTRAP_SEED` | 10000 / 20261028 | V2 §4 |
| `MIN_GRADED_GAMES` | 300 per market | V2 §4 |
| `MAX_MISSING_CLOSE_SHARE` | 0.20 (strictly greater trips) | V2 §2.2(d) |
| `CLOSE_MAX_AGE` | 60:00 (exactly 60:00 valid) | V2 §2.2 |
| `PROB_EPS` | 1e-15 | numerical guard only — flagged (see below) |

## Tests and gates

- New tests: **37 passed** (`tests/test_cfb_game_epa_joint_v1.py`),
  including: embargo boundary at exactly 24h and 24h−ε; close at
  exactly 60:00 valid, 60:00+1s stale, at-kickoff
  `CLOSE_NOT_PREKICKOFF`, single-sided, no-row, invalid prices;
  missing-close share at exactly 20% NOT tripping and at 30%
  tripping without consuming the look; identical-rows-across-arms
  with the market arm proven equal to POWER_V1 output and ≠ ln 2;
  bootstrap determinism at seed 20261028; single-look refusal;
  NOT_FROZEN refusals on every counted entry point; no-lookahead
  (embargoed game injected into a snapshot object provably does not
  move a prediction; the lawful build route refuses it); PM
  equivalence vs the real repo evaluator; ledger tamper detection;
  exclusion exact-match semantics.
- CFB + devig test surface (`pytest tests/ -k "cfb or devig"`):
  **1,896 passed, 2 skipped** — no regressions.
- PR gate 1 (dependency surface): pyproject `dependency-groups.dev`
  == `requirements-test.txt`, **11 == 11**; no dependencies added.
- PR gate 2 (ruff `--select E9,F821,F822,F823,F811`): **clean** on
  both touched Python files.
- Freeze coverage (`_covered_change` over all 11 registry bundles):
  **NONE** for all four touched paths.
- Environment: venv-ci freeze diffed against `requirements-test.txt`
  before any count was trusted — 11/11 exact, no drift.

## Bugs the adversarial pass caught in this build (fixed pre-PR)

1. **Market arm uncomputable**: `_devig_event_probability` built
   the two de-vig quotes with different `entity_id` values;
   `power_devig` requires one paired identity and refused every
   close (`CLOSE_PRICE_INVALID: paired quote identity mismatch`).
   Fixed: both quotes carry the game as entity; sides carry the
   prices. Caught by the verdict tests.
2. **Loaders accepted malformed containers**: a bare string input
   iterated character-by-character and tallied nonsense instead of
   refusing. Both loaders now refuse non-mapping containers/rows
   (`PBP_ROWS_INVALID` / `SCHEDULE_ROWS_INVALID`).

## Underdetermination flags (choices the V2 text does not pin)

1. `PROB_EPS = 1e-15` log-loss clip: V2 states no clip; the repo
   evaluator uses 1e-6. Chosen as a pure numerical guard so a
   stated probability is never logged at exactly 0/1.
2. Success-rate fallback: when the SDV release row carries no
   success column, success uses the standard down/distance
   definition (≥50% of yards-to-go on 1st, ≥70% on 2nd, 100% on
   3rd/4th). V2 names the feature, not the fallback formula.
3. League averages are computed from the snapshot's own data, not
   hard-coded constants.
4. Opponent adjustment is Jacobi iteration with damping 0.5,
   tolerance 1e-6, max 500 iterations, failing closed on
   non-convergence. V2 requires "iteration to a stated tolerance";
   the scheme is stated here.
5. Defensive adjusted values are "allowed above league average";
   projection adds offense + opponent's defensive-allowed value.
6. Pace is never opponent-adjusted (raw per-game rates).
7. Prior blending is one mechanism: the retained prior enters as
   pseudo-games; a team with a prior but no eligible games gets the
   games=0 case of the same mechanism.
8. Neutral-site games get no HFA in the construction. The PM
   reproduction keeps the evaluator's always-HFA — that is PM's
   identity and is not "fixed."
9. A row whose PM estimate is unavailable is excluded from the
   primary metric as `PM_BASELINE_UNAVAILABLE` (V2's graded
   definition requires all three arms present). It does NOT count
   in the missing-close sufficiency share, which counts only
   DK-close absence.
10. The >20% sufficiency share is computed per market over that
    market's universe games (the verdict structure is per market).
11. When both the sample minimum and the sufficiency trip apply,
    the block reports `SAMPLE_MINIMUM_UNMET` first; both facts
    (graded count, missing share) are carried in the block either
    way. Neither outcome consumes the look.
12. Close-classification precedence follows the CBB Amendment 2
    machinery precedent, in the code's check order: no-row →
    `NO_CLOSE_ROW`; a non-finite line raises
    `CLOSE_RECORD_INVALID`; single-sided → `CLOSE_SINGLE_SIDED`;
    present-but-invalid prices raise `CLOSE_PRICE_INVALID`;
    not-pre-kickoff → `CLOSE_NOT_PREKICKOFF`; stale →
    `CLOSE_STALE`. A present-but-invalid
    price raises `CLOSE_PRICE_INVALID` rather than taking one of
    the four missing reasons — the four reasons describe absent or
    unusable closes; an impossible price is a data defect.
    *(Precedence wording corrected at checklist item 5 per the
    independent review of PR #2966, note 2 — the reachable behavior
    always matched the CBB precedent; only this listing's order
    differed from the code's.)*
13. `FreezeRecord` carries the prereg + implementation digests;
    the evaluator/baseline/snapshot-machinery pins of §7 are
    enumerated by the freeze act itself (checklist item 5).
14. SDV close convention: in `sdv_closes`, `spread_line` is the
    closing **margin line** (home perspective) — i.e.
    `−home_team_spread` in the SDV collector's field naming.
    Whoever assembles closes for the evaluator must negate.
15. The construction SDs (16.0/15.0) and the blend/conversion
    constants in the table are a priori design constants chosen
    under the design-data license (AUDIT.md: all admitted
    historical seasons are design data). They were NOT fitted by
    any run in this build, and nothing in this build validates
    anything.
