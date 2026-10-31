# FREEZE RECORD — CFB_GAME_EPA_JOINT_V1 (spread & total successor validation)

**STATE: PREPARED — NOT STRUCK. This document is the freeze record
prepared on the freeze candidate head (checklist item 5). It records
no freeze. `FREEZE_STATE` in `sportsedge/cfb_game_epa_joint_v1.py`
remains `DRAFT_NOT_IN_FORCE`, every counted entry point still refuses
`CFB_GAME_EPA_JOINT_NOT_FROZEN`, the records branch
(`records/cfb-game-epa-joint-v1`) is not created, and no game counts
under this preregistration. The freeze itself is the owner's
prospective recorded act on the reviewed exact head (checklist
items 6–7). At the act, the owner strikes the values reserved below
(freeze commit sha, freeze timestamp, k at freeze) and this record's
state line is replaced in the freeze commit itself.**

Governing text: `PREREG_DRAFT_V2.md` in this directory (CONFIRMED
freeze candidate). Governing contract: the #2961 gate-contract
reconciliation (Oct 30, 2026) under the Oct 27, 2026 VERIFIED-GATE
REPEAL — VERIFIED is the preregistered chronological out-of-sample
validation below, against BOTH baselines; receipts and forward clocks
grade, they do not gate.

## 1. The §7 hash set, struck on this head

| Member | Path | sha256 |
| --- | --- | --- |
| Preregistration document | `research/cfb_game_epa_joint_v1_20261031/PREREG_DRAFT_V2.md` | `cf9a61bfbbbe0138ee670966ed0f8eb714a199fa133d033864b518d6554e94eb` |
| §1 implementation (construction + snapshot machinery) | `sportsedge/cfb_game_epa_joint_v1.py` | `f943a3a7bbf752c76d0bbe25e057934f978e78286c5c9c9bb3e1947fddacd184` |
| §2.1 baseline evaluator | `scripts/evaluate_cfb_sdv_closes.py` | `d4ca6f537233b201a8c999c5919023cd46b50fcb61fc0382de9426c667ecb32c` |
| §2.1 baseline, CFB branch | `artifacts/free_models.py` | `a8abf4606acafd2405ec037ea3bf69f1a6a5168baa4750631cc0fbebcece1fa3` |

- The snapshot machinery (§1's `build_snapshot` / `Snapshot` /
  `PredictionLedger`) is contained in the implementation file above;
  the implementation digest is its pin. There is no separate snapshot
  file in the §7 set.
- The §2.1 "CFB branch" of `artifacts/free_models.py` is pinned by
  the whole-file digest plus the enumerated `PRIORS["CFB"]` values in
  §2 below — a branch of a file has no independent bytes to hash.
  (Underdetermination judgment, disclosed for the item-6 conformance
  review; the production evaluator's own comment at
  `scripts/evaluate_cfb_sdv_closes.py` line 47 ties its prod SDs to
  `PRIORS["CFB"]`.)
- The implementation digest is struck over the file **as amended on
  this head** (checklist item 5 / review flag 13: completing
  `FreezeRecord` with the §7 pins amended the dataclass, so this head
  re-pins; the digest appears in this document only, never inside the
  file it hashes). Any further head movement re-strikes every digest
  in this table and reopens review (checklist item 6).
- `sportsedge/devig.py` (`power_devig`, POWER_V1) is not a §7 hash-set
  member; the market arm's method is pinned by name (POWER_V1, the
  EDGE_FLOOR_DEVIG_V1 policy, Oct 29, 2026 de-vig ruling) and asserted
  in code at every de-vig.

## 2. Constants enumerated in text (§5.3 / F10)

Reviewers close on stated values, not hashes alone. All values are
the module's named constants as built; none was fitted by any run in
the build (BUILD_RECORD flag 15).

**Construction (§1):**

| Constant | Value |
| --- | --- |
| `CONSTRUCTION_SD_MARGIN` / `CONSTRUCTION_SD_TOTAL` | 16.0 / 15.0 (the construction's own, a priori; NOT the production 19.0/18.5) |
| `HOME_FIELD_ADVANTAGE_POINTS` | 2.5 |
| `EMBARGO_HOURS` | 24 (a feature game is available 24h after its kickoff) |

**Opponent adjustment (§1, "iteration to a stated tolerance"):**

| Constant | Value |
| --- | --- |
| `ADJUSTMENT_TOLERANCE` | 1e-6 |
| `ADJUSTMENT_MAX_ITERATIONS` | 20000 (fail-closed `OPPONENT_ADJUSTMENT_NOT_CONVERGED` beyond; raised from 500 — see §7) |
| `ADJUSTMENT_DAMPING` | 0.5 (damped Jacobi) |

**Shrinkage / prior (§1):**

| Constant | Value |
| --- | --- |
| `PRIOR_PSEUDO_GAMES` | 3.0 (retained prior's weight, in games) |
| `PRIOR_SEASON_RETENTION` | 0.65 (prior-season rating retained fraction) |

**Feature constants (§1):**

| Constant | Value |
| --- | --- |
| `SUCCESS_TO_EPA` | 1.0 |
| `EXPLOSIVE_TO_EPA` | 1.5 |
| `EXPLOSIVE_YARDS_THRESHOLD` | 20.0 yards (loader-level: yards_gained ≥ 20) |
| `EPA_CHANNEL_PLAY_WEIGHT` | 0.5 (per-play vs per-possession EPA channels) |
| `POINTS_BLEND_WEIGHT` | 0.25 (points-only rating channel in the blend) |

**PM baseline (§2.1, reproduced exactly; "prod" SD set pinned by F3):**

| Constant | Value |
| --- | --- |
| `PM_SD_MARGIN` / `PM_SD_TOTAL` | 19.0 / 18.5 (= `SD_MARGIN_PROD` / `SD_TOTAL_PROD` = `PRIORS["CFB"]` sd_margin / sd_total) |
| `PRIORS["CFB"]` in `artifacts/free_models.py` | (base 28.0, sd_total 18.5, sd_margin 19.0, hfa 2.5) |
| `PM_BASE` / `PM_HFA` / `PM_WINDOW` / `PM_SHRINK` / `PM_MIN_PRIOR_GAMES` | 28.0 / 2.5 / 5 / 3 / 3 |

**Evaluator (§2.2 / §4):**

| Constant | Value |
| --- | --- |
| `ALPHA` | 0.05 |
| `BOOTSTRAP_RESAMPLES` / `BOOTSTRAP_SEED` | 10000 / 20261028 (game-cluster, two-sided percentile at 1 − α/k, nearest-rank bounds) |
| `MIN_GRADED_GAMES` | 300 per market (SPREAD and TOTAL separately, never pooled) |
| `MAX_MISSING_CLOSE_SHARE` | 0.20 — strictly greater trips `INSUFFICIENT_MARKET_DATA` (§2.2(d)) |
| `CLOSE_MAX_AGE` | 60:00 — exactly 60:00 before kickoff is valid (§2.2(b)) |
| `PROB_EPS` | 1e-15 (log-loss numerical guard only; never a stated probability — review flag 1: Φ underflows to exactly 0.0 without it) |

## 3. Multiplicity — k (§4)

Confidence level per comparison is `1 − α/k`, α = 0.05, where k is
the number of families (across all sports) with an active forward
clock or an already-validated construction. **The numeric
`k_at_freeze` is struck by the freeze act** (checklist item 5: "k
recorded at the freeze act"), because it is a fact about the
program's state on the freeze date; it is recorded in the struck
`FreezeRecord` and recomputed at the verdict, **the larger figure
governing**. If k cannot be established at the verdict, no verdict
issues (`K_UNESTABLISHED`). The two market verdicts under this
prereg are two of the families counted in program-wide k at any
later verdict; both comparisons within a market are inside that
market's α share.

## 4. Statements the freeze act adopts by striking this record

1. **Pace enters unadjusted (review flag 6).** Under §1, the
   opponent-adjustment iteration applies to the two-way offensive/
   defensive families (EPA per play and per possession, success rate,
   explosiveness rate, and the points family). Pace (plays/possessions
   per game) is a raw per-game rate with no offensive/defensive pair
   to iterate and enters the construction **unadjusted**. This
   statement resolves the §1 textual ambiguity expressly, on the
   record, before the freeze: it is a statement of what the frozen
   implementation does, not a change to it.
2. **Market-leg sufficiency is per market (BUILD_RECORD flag 10).**
   The §2.2(d) share is computed per market over that market's
   universe games: missing-close games (any §2.2(b) reason) in that
   market ÷ that market's universe games; strictly greater than 0.20
   returns `INSUFFICIENT_MARKET_DATA` for that market only, records
   no verdict, and does not consume the look.
3. **PM-unavailable rows (BUILD_RECORD flag 9).** A row whose PM
   estimate is unavailable is excluded from the primary metric with
   reason `PM_BASELINE_UNAVAILABLE` (the §4 graded definition
   requires all three arms present). It counts in **neither** the
   primary rows **nor** the §2.2(d) missing-close share, which counts
   DK-close absence only.
4. **Block precedence (BUILD_RECORD flag 11).** When both the
   sample minimum and the sufficiency trip apply, the block reports
   `SAMPLE_MINIMUM_UNMET` first; both facts (graded count,
   missing-close share) are carried in the block either way. Neither
   outcome consumes the look.
5. **SDV close sign convention (BUILD_RECORD flag 14).** In
   `sdv_closes`, `spread_line` is the closing margin line (home
   perspective) — i.e. `−home_team_spread` in the SDV collector's
   field naming. Whoever assembles closes for the evaluator must
   negate.

## 5. Disposition code set, declared (§2.2 as built)

Close classification (`classify_close`; check order mirrors the CBB
Amendment 2 machinery precedent): a close is `VALID`, or `MISSING`
with exactly one of the four §2.2(b) reasons — `NO_CLOSE_ROW`,
`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE` — checked
in that order after the no-row case (a present-but-impossible price
raises `CLOSE_PRICE_INVALID` and a malformed record raises
`CLOSE_RECORD_INVALID`: defects, not dispositions; the four reasons
describe absent or unusable closes only). Row dispositions in the
evaluator: missing-close rows are excluded from the primary log-loss
comparison in all three arms and retained in the MAE readout flagged
`MARKET_REF_SDV` (SDV close as accuracy reference only — no prices,
no market probability, no CLV claim); PM-unavailable rows are
excluded as `PM_BASELINE_UNAVAILABLE` (§4.3 above); pushes are
excluded from graded and reported. Verdict-level outcomes:
`SAMPLE_MINIMUM_UNMET` and `INSUFFICIENT_MARKET_DATA` record nothing
and consume no look; PASS/FAIL are recorded once, FAIL terminal.

The code `VALID_SAME_LINE` (CBB Amendment 2 §3 machinery) has **no
counterpart in this family and is not declared**: this prereg's
§2.2 states close validity in its own terms — two-sided, pre-kickoff,
≤60:00 — under which the lane's FINAL capture is the close; there is
no same-line/moved-line distinction for a CFB close to carry. The
disposition set above is complete as built.

## 6. What the freeze act still does (checklist items 6–7)

1. Item 6 conformance run on this exact head, independent review
   closed on it (any head movement reopens review and re-strikes §1).
2. Item 3's evidence in hand: one full Saturday of five-stage §6B
   receipt discipline under the landed Capture Spec V1 CFB section.
3. The owner's act: create the records branch
   `records/cfb-game-epa-joint-v1`, strike the `FreezeRecord`
   (freeze commit sha, freeze timestamp, numeric `k_at_freeze`, and
   the §1 digests), flip `FREEZE_STATE` to its in-force value in the
   freeze commit, and replace this record's state line — naming the
   first counted slate by the prereg's own rule (§3: the first full
   Saturday after the freeze through that season's bowl + CFP games,
   extending season-by-season until 300 graded games per market).
   No game counts before the act; no retroactive counting after it.

## 7. Iteration-cap amendment (owner ruling "Fix", Oct 31, 2026) — this head re-pins

`ADJUSTMENT_MAX_ITERATIONS` raised **500 → 20000**. One constant; no other line of the implementation changes. The implementation digest in §1 is re-struck over the amended file (`f943a3a7…`, was `87f585c8…`); the other three §7 pins are unchanged. Head movement reopens item 6 on the new head.

**Why it cannot change a validated number:** the cap is a refusal threshold. A fit that converges exits on the 1e-6 tolerance test at the same iteration and the same values under any cap at or above that iteration count; the cap only decides whether a slow fit refuses or finishes.

**Why it was needed:** at 500 the construction refused whole slates on sparse early-season opponent graphs. Measured on 2025 design data (Claude lane run, PR #2976): weeks 3 and 4 refused at 500; week 4 clears by 1,500; week 3 needs between 3,500 and 4,500. Rocky's probes: realistic clustered 130-team schedules needed 717 / 520 iterations through weeks 2 / 3; worst adversarial case (60-team chain) needs 14,067. Cost 0.35 ms per iteration on a 130-team fit — a snapshot grinding the full cap on all five stats is ~35 s, once.

**Why 20000:** about 4x the worst observed real case and above the worst adversarial case; a 5000 cap would sit within ~10–30% of the real week-3 demand.

*Prepared Oct 31, 2026 (Rocky), checklist item 5, from
PREREG_DRAFT_V2 §§5.3/7, the landed implementation, and the
independent review of PR #2966 (flags 6/12/13 carried here).*
