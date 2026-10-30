# CFB Four-Family Evaluation — FREEZE PACKAGE

**Status: PREPARED FOR THE OWNER'S FREEZE ACT. NOTHING IS FROZEN YET.**
This package proposes the freeze identity and the final preregistration
text. It executes no evaluation, scores no game, consumes no attempt, and
writes no freeze SHA into any configuration. The freeze exists only when
the owner names the candidate SHA (Owner Summary, below). Until then
every harness entry point continues to refuse pre-scoring with a named
reason, exactly as built.

**Sources (all read and cross-verified for this package):**
`PREREGISTRATION_DRAFT.md` (SHA-256
`57f1d81b1cc2cd82d09e12395d1dbbc0d8b37012fca1e93bf4774129c2f381bf`),
`HARNESS.md`, `BINDINGS.md`, the dry-run manifest
(`snapshots/DRY_RUN_MANIFEST.json`, file SHA-256
`d6a1e30a1cd6c4780833ccafd35cb2ace15da73ecd4b5c913f024861f4c2bb6d`),
and the two branch trees named in §1. Every number in this package was
recomputed from the manifests and the trees during preparation; §2 is
the reconciliation record.

---

## OWNER SUMMARY — the whole decision on one screen

**Candidate freeze SHA (the one line to name):**

```
bfba59f3fa563c07ec8934025a113cfbe3d5353b
```

That is the head of `research/cfb-four-family-eval-bindings-20261013` —
the composed tree: harness (`b68114e0f3a554ac6f02e9a15394b7631f1c5206`)
+ bindings layer + the frozen engine files + the three content-hashed
data snapshots + the ruled configuration. §1 states exactly what naming
it pins and what it does not.

**The three ratifications that ride with the freeze** (evidence in §4;
one confirmation covers all three):

- **R1 — Designated provider: Bovada.** Largest single-book coverage in
  the lines archive for all three scored families (4,325 games; spread
  and total attribution verified clean). Currently a bindings default,
  not yet owner-ruled.
- **R2 — FBS membership override table `FBS_MEMBERSHIP_OVERRIDES_V1`.**
  Thirteen reclassification programs whose season-effective FBS status
  differs from the upstream current-state directory table (Appalachian
  State, Georgia Southern, Old Dominion, Charlotte, Coastal Carolina,
  Liberty, James Madison, Sam Houston, Jacksonville State, Kennesaw
  State, Delaware, Missouri State, Idaho — seasons in §4). Currently
  bindings-declared, not yet owner-ruled.
- **R3 — The bound dataset, exactly as counted.** Population 9,536;
  pooled matched moneyline 3,335 / spread 3,773 / total 3,773 /
  team_total 0; and the exclusion disposition: the 220 designated-
  provider moneyline quarantines (**214 flipped pairs** whose moneyline
  sides contradict the spread favorite, **6 uncheckable**) stay
  quarantined — excluded, never repaired, never side-swapped — as do
  the 58 orphan and 3 post-kickoff line records.

**The exact sentence that freezes it:**

> **"Freeze CFB_FOUR_FAMILY_EVALUATION_V1 at
> bfba59f3fa563c07ec8934025a113cfbe3d5353b, ratifications R1–R3
> confirmed."**

**What the freeze does not do** (each remains a separate act, §5):
it does not authorize execution — a scored run additionally requires
family-level registry adoption to have landed **and** a separate owner
execution ruling; it changes no family's status (all stay UNVALIDATED);
it does not touch the forward leg, which remains undesigned and
unauthorized.

---

## 1. The candidate freeze identity

### 1.1 The composed tree

| Layer | Identity |
|---|---|
| Base | current main `655715907` (harness composition base, per HARNESS.md) |
| Harness commit | `b68114e0f3a554ac6f02e9a15394b7631f1c5206` — branch `research/cfb-four-family-eval-harness-20261013`; patch SHA-256 `841b0a80893739a9b6fa7c4b988dfe7315cc087545d40a66ceb39b059683c44e` |
| **Candidate freeze commit** | **`bfba59f3fa563c07ec8934025a113cfbe3d5353b`** — branch `research/cfb-four-family-eval-bindings-20261013`, stacked directly on the harness commit; patch SHA-256 `1ef56cb795c3c2334394ddbee7324142db552f20883aaead93f082b2278e60ca` (4 files, +2,463/−0 vs the harness commit) |
| Engine: `artifacts/free_models.py` | SHA-256 `70d95ed369e162760e117c46f7c2116f61b1a5756587174814347a4aa3aaf1f2` (verified from the candidate tree) |
| Engine: `sportsedge/team_half_pricing.py` | SHA-256 `3d76cf730111d75c415a682e3f733b1374e19745f61b49b83dfb68e06f430308` (verified from the candidate tree) |
| Results snapshot `SPORTSEDGE_CFB_RESULTS_SNAPSHOT_V1` | id `151774e84e45d8348c9e36c87d390d720c059023b190cf022bd16375b20d1195`; file SHA-256 `830ebe5a0262b26b8ebc62b6075a7bf70eb814c99025b1ea94ab9596ae586389` (4,515,975 bytes; 11,495 games, 2013–2025, all decided) |
| Lines snapshot `SPORTSEDGE_CFB_LINES_SNAPSHOT_V1` | id `9cc966b57db5d8b61fc644ceab587ab90f7d6bef576540479503ab8607a7d7b5`; file SHA-256 `72c4476f78f7b1b82919df97a1c02f781260969f334ab5f7185c8b0e42e0c578` (1,921,452 bytes; CFBD-era archive, designated provider Bovada) |
| Directory snapshot `SPORTSEDGE_CFB_DIRECTORY_SNAPSHOT_V1` | id `764a32c87688b6e56716b889f3f943150037880fbbf36c8d9a37419894d27e31`; file SHA-256 `503d29b60e05ff73fb0997eba83b8dcd908a510415737674bb621d2e93b9a3b6` (179,129 bytes; 1,840 team ids) |

Both branches are **held local** (no remote ref exists). The patch
hashes above are the portable identity of the same two trees; the
snapshot files live under `snapshots/` in this directory and rebuild
deterministically from the pinned sources (a rebuild reproduces
identical snapshot ids — verified by the bindings build).

### 1.2 What naming the candidate SHA pins

Naming `bfba59f3f…` as the freeze SHA pins, as one indivisible object:

- the harness code and its shipped configuration structure
  (`sportsedge/research/cfb_four_family_evaluation_v1.py`,
  `config/research/cfb_four_family_evaluation_v1.json` — thresholds,
  fold protocol, verdict functions, attempt ledger);
- the bindings layer (`sportsedge/research/cfb_four_family_bindings_v1.py`,
  `config/research/cfb_four_family_bindings_v1.json` — the 15 source
  pins, the RULED §10 record, the provider designation slot, the FBS
  override table — `scripts/build_cfb_eval_snapshots.py`, and both test
  batteries);
- the candidate engine exactly as hashed above (the evaluated object:
  the frozen CFB game engine in its declared injury-neutral evaluation
  configuration, §3.3 of the preregistration text);
- the three data snapshots exactly as hashed above — results, lines,
  directory — including their recorded limitations (no per-row
  timestamps in the lines archive; `close_time_certified: false`;
  descriptive-only market role);
- the ruled configuration: CAND_2, both-FBS population, folds
  2021–2025 with burn-in 2013–2020, CFBD DESCRIPTIVE_ONLY, and the
  three-family historical scope (moneyline, spread, total) with
  team_total forward-only;
- the preregistration text of §3 of this package, including every gate
  threshold, the attempt budget (3), and the consumption rules.

Under the freeze mechanics (§3.8, draft §3.3): any change to any pinned
file **ends the cohort** — prior results are archived, never pooled,
and counts restart under a new SHA. Baselines freeze on the same terms
as the candidate.

### 1.3 What naming it does NOT pin

- **Nothing on main after the branch point.** The freeze is on this
  composed tree, not on a merged main head; later merges do not move it,
  and merging the branches later does not amend it.
- **No `freeze_sha` value in any file.** At preparation time the
  harness config, the bindings config, and the dry-run manifest all
  carry `freeze_sha: null` (verified, §2). The owner's naming is
  recorded at freeze time in the freeze record /
  `SPORTSEDGE_EVIDENCE_UNIT_V1` manifest; this package deliberately
  writes the SHA into no consuming configuration.
- **Not the registry.** Family-level adoption of the CFB ids is a
  separate landing (§5); the freeze names an evaluation tree, not a
  registered family set.
- **Not execution.** The attempt clock does not start at freeze (§5).
- **Not the forward leg.** No CFB forward-capture design exists; the
  freeze pins only the forward leg's pre-registered gates (§3.6).
- **Not team_total history.** There are no historical team-total lines
  to pin; the family's absence from the historical leg is a data fact
  recorded by the scope ruling, not a gap the freeze papers over.
- **Not production behavior.** The historical leg evaluates a declared
  configuration of the frozen engine; the production configuration's
  injury-adjusted behavior is not evaluated by it and is not pinned as
  an evaluated object here.

---

## 2. Verification record — package numbers vs BINDINGS.md vs the trees

Every figure below was recomputed during package preparation from
`snapshots/DRY_RUN_MANIFEST.json` / `SNAPSHOT_MANIFEST.json` and the
candidate tree, and compared against BINDINGS.md. **All agree; no
discrepancy was found, so nothing was smoothed.**

| Check | BINDINGS.md | Recomputed | Verdict |
|---|---|---|---|
| Bindings branch head | `bfba59f3f…` | `bfba59f3fa563c07ec8934025a113cfbe3d5353b` (`git rev-parse`) | agree |
| Harness branch head | `b68114e0f…` | `b68114e0f3a554ac6f02e9a15394b7631f1c5206` | agree |
| `free_models.py` SHA-256 | `70d95ed3…` | `70d95ed369e1…` from the candidate tree (`git show` + sha256) | agree |
| `team_half_pricing.py` SHA-256 | `3d76cf73…` | `3d76cf730111…` from the candidate tree | agree |
| Snapshot ids (results / lines / directory) | `151774e8…` / `9cc966b5…` / `764a32c8…` | identical ids in the dry-run manifest and snapshot manifest | agree |
| Population | 9,536 (burn-in 5,754) | 11,495 − 511 IL − 1,446 non-FBS − 2 unresolved = 9,536; burn-in 5,754 | agree |
| Fold populations | 739 / 747 / 757 / 765 / 774 | identical in the manifest (Σ folds 3,782) | agree |
| Pooled matched | ML 3,335 / spread 3,773 / total 3,773 / team_total 0 | Σ per-fold matched from the manifest: 3,335 / 3,773 / 3,773 / 0 | agree |
| Floors | 500 per fold / 0.75 coverage / 2,500 pooled | smallest in-scope fold count 633 (ML 2022); lowest in-scope coverage 84.7% (ML 2022); pooled ≥ 3,335 — all three in-scope families clear all three floors; team_total clears none (0) | agree |
| Quarantines | 220 designated-provider ML (214 sign-inconsistent + 6 uncheckable) | snapshot `provider_coverage`: Bovada `moneyline_quarantined: 220`; manifest `quarantined_records_designated_provider: 220`; per-record reason `ML_SPREAD_SIGN_INCONSISTENT` | agree |
| Orphan / post-kickoff flags | 58 / 3 | load-flag counts in the snapshot manifest: 58 `LINE_RECORD_WITHOUT_RESULTS_GAME`, 3 `POST_KICKOFF_LINE_TIMESTAMP` | agree |
| Run state | NOT_RUN, 0 attempts, no probabilities | manifest: `run_state: NOT_RUN`, `probabilities_computed: false`, `attempts_consumed: 0` | agree |
| Freeze state | `freeze_sha: null` everywhere | harness config (candidate tree): `freeze_sha: null`, rulings UNRULED (shipped config untouched); bindings config: `freeze_sha: null`, rulings record RULED (delegation record), `execution_authorized: false`; manifest: `freeze_sha: null`, `freeze_status: NOT_ESTABLISHED — naming the freeze SHA is a reserved owner act at freeze time` | agree |

Batteries on the composed tree (from BINDINGS.md / HARNESS.md, junitxml
counts): bindings 19/19; harness 47/47; adjacent engine/team-half
suites 41/41; committed-tree fresh-worktree re-run 66/66.

---

## 3. FINAL PREREGISTRATION TEXT — CFB_FOUR_FAMILY_EVALUATION_V1

*This is the draft preregistration with the owner's rulings filled in
and the data findings applied. It becomes the filed preregistration when
the owner names the freeze SHA (§1). Filing authorizes the
specification only; §3.9 lists what it does not authorize. Where this
text differs from the draft, the difference is enumerated in §3.10 —
thresholds and gates are unchanged from the draft.*

### 3.1 Program and family set

The program evaluates the frozen CFB game engine against the frozen
baseline (BASE-1) in chronological out-of-sample folds, with a
descriptive market comparison against CFBD closing lines, and
pre-registers the gates of a future forward leg. The program's family
set, by exact surface id, is:

`moneyline`, `spread`, `total`, `team_total`.

- **Historical leg scope (RULED): three families — `moneyline`,
  `spread`, `total`.** `team_total` is **forward-only**: no historical
  team-total lines exist in any corpus available to this repo (the
  CFBD-era archive carries moneyline/spread/total only; bound coverage
  is 0.0 in every fold — §4/R3). Implied team totals derived from
  spread/total are a construction, not data, and are **not adopted**;
  adopting them, or any ruled historical team-total line source, would
  require its own preregistration or a hash-chained amendment.
- **Prerequisite:** adoption of the four ids into the CFB family-level
  registry, with engine states taken from the registry surfaces
  (`IMPLEMENTED` / `CANONICAL_GAME_ENGINE` for all four), is a named
  prerequisite filing step performed by the integration lane (§5). The
  family set above is a set of surface ids until that step lands.
- Period families, `anytime_td`, alternate lines (ladders of the
  in-scope families, scored only at the captured headline line),
  touchdown-count families, and all prop families are out of scope, for
  the draft's stated reasons (no engine, no two-sided market, or
  per-game availability) — unchanged from draft §1.2.

### 3.2 The honest bottom line (carried from the draft, still true)

No promotion-grade market baseline exists for CFB today. CFBD closing
lines carry no per-row timestamps, so they support **descriptive**
comparison only; the only promotion-capable market leg is forward
capture under the strict paired-quote contract, for which no CFB design
is filed and no capture is authorized; no Kalshi CFB series has passed
the five-check verification (M3 is excluded as a baseline). This program
can therefore produce genuine chronological out-of-sample verdicts
**against the frozen baseline only**, plus descriptive market-relative
readouts. It cannot conclude that any family beats the market, and it
cannot feed a promotion decision. **Even if every gate passed,
validated CFB families remain 0** until the market leg is satisfied
under the paired contract in a forward cohort and a separate promotion
decision is taken.

### 3.3 Candidate and baseline (RULED)

- **Candidate: CAND-2** — the identical frozen code as production
  (`artifacts/free_models.py:calculate`, sport=CFB), differing only in
  declared input configuration: injury/QB-context inputs neutralized at
  their neutral value (`injury_pts = 0.0` both sides); every
  owner-disabled factor at exactly zero contribution (rest under all
  key names, recent form, and the ERA-based pitcher adjustment stated
  whole per the Oct 13 disable rulings), with zero contribution
  demonstrated on the frozen tree by the pre-scoring verification
  battery (§3.8 kill criterion 4), not asserted; every remaining input
  PIT-reconstructible from completed-game results and schedule facts,
  computed walk-forward per §3.4. The evaluated object is named, in
  every output, **"frozen CFB game engine, injury-neutral evaluation
  configuration."** A verdict under this program is a verdict about
  that object. The production configuration (CAND-1) is disqualified
  for the historical leg — its injury inputs derive from a
  current-state feed with no PIT-verified historical archive; inventing
  them is prohibited. CAND-3 (forward-only) was the alternative and
  was not chosen. The production configuration is evaluable only in
  the forward leg, where evidence is captured live.
- **Baseline: BASE-1** — team-strength ratings (F-01) + static home
  advantage (F-04), the owner-retained frozen baseline, explicitly
  labeled unvalidated baseline assumptions, every other adjustment at
  zero. The bakeoff winner `PRIOR_CURRENT_BLEND` (BASE-2) is not the
  baseline (its score→probability construction was never frozen); it
  may be reported as a labeled descriptive comparator only, gating
  nothing. Market-only comparison (BASE-3) is rejected: the house
  standard requires beating **both** the frozen baseline and a market
  baseline per family — the baseline leg here, the market leg per
  §3.2/§3.6.

### 3.4 Fold protocol (RULED)

- **Population:** FBS regular-season games in which **both** teams are
  FBS programs under season-effective membership (§4/R2). Postseason
  games (bowls, conference championships, playoff) are a separate
  population and are **never pooled**. Games vs FCS opponents are
  excluded (`POPULATION_NON_FBS_OPPONENT`), counted. Illinois-excluded
  fixtures are removed **before** population counting
  (`BLOCKED_PREPRICING_IL_COLLEGE_EXCLUDED`) — never in the production
  population. Unbindable team identity fails closed
  (`BLOCK_TEAMS_UNRESOLVED`).
- **Burn-in:** seasons 2013–2020, training-only, never scored.
- **Validation folds:** one per season — **2021, 2022, 2023, 2024,
  2025** (five folds). Training window per fold: all seasons strictly
  before the validation season (expanding). Any parameter selection
  happens inside the training window only, by the frozen selection
  procedure; outer validation outcomes never influence selection; if a
  training window cannot support the procedure, selection fails closed
  pre-scoring (NOT_RUN) — no fallback to validation data, ever.
- **Within-fold walk-forward (load-bearing):** ratings state for a
  scored game is computed from games completed **strictly before that
  game**, including earlier games in the same validation season.
  Applying a season-end ratings snapshot to earlier games is future
  leakage and a PIT-audit kill criterion (§3.8).
- **Fold minimum:** a validation fold with < 500 scored games for a
  family is a data failure for that family (NOT_RUN). **Restated
  counts from the bound data** (the draft §4.1 restatement rule,
  discharged by the dry-run manifest; ratified as R3):

  | Fold | Population | Moneyline | Spread | Total |
  |---|---|---|---|---|
  | 2021 | 739 | 646 (87.4%) | 735 (99.5%) | 735 (99.5%) |
  | 2022 | 747 | 633 (84.7%) | 743 (99.5%) | 743 (99.5%) |
  | 2023 | 757 | 691 (91.3%) | 757 (100%) | 757 (100%) |
  | 2024 | 765 | 682 (89.2%) | 764 (99.9%) | 764 (99.9%) |
  | 2025 | 774 | 683 (88.2%) | 774 (100%) | 774 (100%) |
  | **Pooled** | **3,782** | **3,335** | **3,773** | **3,773** |

  (Full population including burn-in: 9,536. Six evaluation teams —
  the recent FBS joiners James Madison, Sam Houston, Jacksonville
  State, Kennesaw State, Delaware, Missouri State — have no burn-in
  population evidence; their ratings start at 0.0 by the harness's
  design, disclosed here per the bindings record.)
- **Settlement:** final results from the bound results snapshot (§1).
  Full-game markets include overtime; integer-line pushes are excluded
  from that family's metric and counted
  (`PUSH_AT_INTEGER_LINE_EXCLUDED`); no-contests/cancellations excluded
  and counted (`GAME_NO_CONTEST_OR_CANCELLED`).

### 3.5 Metrics and historical-leg gates (UNCHANGED from the draft)

- **Metrics (per family, paired per game, candidate vs each
  comparator):** ΔBrier and ΔLogLoss (negative is better). Moneyline:
  one row per game (candidate P(home win)). Spread / total: candidate
  cover probability computed **at the bound line**; no substituting a
  moved headline line in either direction (same-threshold rule).
  Uncertainty: 95% CIs by cluster bootstrap over week blocks, 10,000
  reps, seed predeclared in the freeze record at filing.
  Calibration is descriptive, never gated: logistic recalibration of
  outcome on candidate log-odds; the "not materially off" band is slope
  ∈ [0.8, 1.25] and intercept ∈ ±0.10; a family beating a baseline with
  calibration outside the band is reported with `CALIBRATION_DEFECT`
  attached — disclosed, never hidden, never silently gated after the
  fact.
- **Vs BASE-1 (verdict-grade):**
  - `BEATS_FROZEN_BASELINE` — pooled ΔBrier CI entirely < 0 **and**
    pooled ΔLogLoss CI entirely < 0 **and** the candidate's point
    estimate is better in **≥ 3 of 5 folds** on both metrics.
  - `WORSE_THAN_FROZEN_BASELINE` — either pooled CI entirely > 0.
  - `INCONCLUSIVE` — anything else. **No extension is offered on the
    historical leg.**
  - Sample floor for any baseline verdict: pooled n ≥ **2,500** scored
    games for the family **and** all 5 folds present **and** every fold
    ≥ 500 (§3.4). Below the floor the family is NOT_RUN (insufficient
    bound data), not failed.
  - Coverage presumption: if a family's scored fraction of its
    population falls below **75%**, its verdict is presumptively
    `INCONCLUSIVE (COVERAGE)` regardless of metrics; the
    scored/expected ratio appears in the readout's first paragraph.
- **Vs CFBD (M1, descriptive only — RULED DESCRIPTIVE_ONLY, as-is; the
  Sep 27 audit's strengthening steps are not executed and
  `cfbd_verification_steps_completed` remains false):** pooled and
  per-fold ΔBrier/ΔLogLoss with CIs, reported under the standing label
  **`DESCRIPTIVE_MARKET_COMPARISON_NOT_A_VERDICT`**, accompanied
  verbatim by: *"CFBD closing lines carry no per-row timestamps; this
  comparison is descriptive only and supports no claim of market
  outperformance, no CLV statement, and no promotion input."*
  Constructions: moneyline — proportional no-vig from the two CFBD
  moneylines; spread/total — implied parity at the CFBD line
  (`IMPLIED_PARITY_AT_CFBD_LINE_NOT_A_PRICED_PAIR`), never represented
  as a priced no-vig pair. The designated provider for the comparison
  is Bovada (§4/R1). For `team_total`, the market section of any
  readout states `NO_HISTORICAL_MARKET_COMPARATOR` and nothing else —
  and under the §3.1 scope ruling the family has no historical readout
  at all.
- **What a pass does:** `BEATS_FROZEN_BASELINE` changes **no status**.
  The family remains `UNVALIDATED` for every betting purpose
  (`family_status: UNVALIDATED`, `status_change: NONE` on every
  record). It is a necessary condition on the road to validation,
  nowhere near a sufficient one.

### 3.6 Forward-leg gates (pre-registered here; leg undesigned and unauthorized)

Adopted unchanged from the draft (M2 contract constants and §5.5):
same book (DraftKings), same event/market/line; per-side own
timestamps; pair skew ≤ 120 s; each side ≤ 180 s old at assembly; both
sides strictly pregame; a price of exactly −100 refuses the pair;
closing classification = the later side within the final 30 minutes
before kickoff; decision window T−120 → T−45 min, closing target
T−20 → T−2 min; no-vig POWER_V1 primary, proportional sensitivity
(a sign flip under the sensitivity is reported method-sensitive;
per §5.5's wording the forward verdict is then INCONCLUSIVE).

Per family, on the paired closing evidence — verdict target
**n ≥ 300 games AND ≥ 20 distinct week blocks** (team_total:
n ≥ 300 team-games):

- `DEMONSTRATED_EDGE_RESEARCH_ONLY` — ΔBrier CI entirely < 0 **and**
  ΔLogLoss CI entirely < 0 vs the DK no-vig close. **This label is the
  ceiling of the entire program** — not a verified betting edge, not
  deployment eligibility, not a card tier.
- `REFUTED` — either primary CI entirely > 0.
- `INCONCLUSIVE` — anything else, including method-sensitive sign.
- **One predeclared extension:** INCONCLUSIVE at target with point
  estimates favorable on both metrics extends the cohort once, to
  n = 600, under the same freeze. No second extension. A freeze change
  ends the cohort and restarts the count.
- **No interim verdicts.** Accrual reports are labeled
  `ACCRUAL_ONLY_NOT_A_VERDICT`. Historical-fold results and
  forward-cohort results are different evidence classes and are **never
  pooled**. The forward leg has **no attempt budget** (§3.8).

`team_total` participates in the program **only** under this leg,
when a capture design exists and is separately approved.

### 3.7 Availability and participation binding (UNCHANGED from the draft)

- **Forward source of truth:** the inspected DraftKings event page
  (`sportsedge/dk_event_availability.py`, PR #2136; UNKNOWN is the
  default state): `OFFERED_TWO_SIDED` / `OFFERED_OTHER_STRUCTURE` /
  `NOT_OFFERED` / `UNKNOWN`. Uninspected means UNKNOWN — never inferred
  from another game, week, registry default, or historical archive.
  Where the registry's availability prior and the inspected page
  disagree, the page wins and the disagreement is reported.
- **Historical leg:** no per-game inspected record exists for past
  seasons and none may be fabricated retroactively; every historical
  readout carries the standing caveat that per-game availability for
  historical games is UNVERIFIED.
- **Exclusion vocabulary (exact strings, shared with the cards and the
  coverage accounting):** `MARKET_NOT_OFFERED_FOR_GAME`,
  `MARKET_STRUCTURE_NOT_TWO_SIDED`, `AVAILABILITY_UNKNOWN_NOT_INSPECTED`,
  `BLOCKED_PREPRICING_IL_COLLEGE_EXCLUDED`, `BLOCK_TEAMS_UNRESOLVED`,
  `POPULATION_NON_FBS_OPPONENT`,
  `PUSH_AT_INTEGER_LINE_EXCLUDED`, `GAME_NO_CONTEST_OR_CANCELLED`,
  `QUOTE_PAIR_INVALID:<subreason>` (forward only). Exclusions are
  counted and reported per family with reasons; an excluded game is
  never scored as a miss, a zero, or a silent drop.
- **QB-identity caveat:** every historical readout reports, per family,
  the intake-blockable fraction labeled
  `WOULD_BLOCK_AT_INTAKE_QB_IDENTITY` under the §6.3 discipline of the
  draft (reported as a count where knowable; where the historical
  intake state is unknowable, the readout says so and reports the
  current blockable fraction for the same teams as dated context).
  Form 2's governing sentence binds this program: a verified QB
  identity is **not** verified availability. Nothing in this evaluation,
  in either leg, at any verdict level, asserts player availability.

### 3.8 Attempt budget and consumption (UNCHANGED from the draft, one scope restatement noted)

- **Budget: 3 attempts** for the historical evaluation program. One
  attempt = one completed scored run of the program **as scoped by
  §3.1** (historical leg: moneyline, spread, total, all five folds)
  under one filed freeze. There are no family-level re-runs.
  **The first completed scored run under this freeze, if executed, is
  attempt 1.**
  *(Scope restatement, the only §7 change: the draft defined the
  attempt unit over "all four families" because the draft's leg
  included team_total. The §3.1 scope ruling removes team_total from
  the historical leg; the unit is restated to the ruled scope. The
  budget, and every consumption rule below, are the draft's,
  unchanged.)*
- **Consumption:** a completed scored run consumes the attempt
  regardless of outcome, at the moment the run finishes and its result
  record is written. A violation or contamination discovered **after**
  scoring records the result **VOID**; the attempt **counts as
  consumed**; voiding never refunds the budget. Discovery **before**
  scoring is a pre-scoring abort, recorded **NOT_RUN** with a named
  reason; the attempt is **not consumed**. An implementation bug in
  code whose frozen math and spec are demonstrably unchanged does not
  consume the attempt, but requires a written ledger note meeting G2's
  evidentiary bar.
- **Kill criteria (pre-scoring aborts → NOT_RUN, attempt not
  consumed):** (1) any source or frozen object's SHA-256 differs from
  the freeze manifest — abort before parse; (2) any validation fold
  below the §3.4 minimum for an in-scope family (that family NOT_RUN —
  data failure; **if two or more in-scope families** fail the floor,
  the program aborts NOT_RUN); (3) PIT audit failure — any feature,
  rating, share, rate, or selection input demonstrably using
  target-game or later information; (4) the pre-scoring verification
  battery fails on the frozen tree (frozen-math fixture checks;
  disabled-factor zero-contribution checks; seed determinism —
  identical inputs → byte-identical result hashes).
- **NOT_RUN vs FAIL stays distinct forever.** A required comparison
  that cannot be produced for a reason outside the kill criteria
  cannot be passed: that family's gate fails with the reason recorded.
- **Thresholds never change retroactively.** A threshold change is a
  new preregistration or a ruled, hash-chained amendment (pre-edit
  copy retained and hash-verified; supersession recorded — the G2
  Amendment 1/2 pattern).

### 3.9 Data integrity and NOT AUTHORIZED (carried from draft §8/§9)

Data integrity, unchanged: forward capture records (when a design
exists) are append-only, receipted, hash-bound, written before
kickoff, never backdated or repaired from postgame sources; no
backfill ever; no archival collector reruns and no API-credit spends
to repair failures; historical snapshots are consumed as immutable
content-hashed snapshots (§1) — no row edited in place, a corrected
snapshot is a new version whose mid-program adoption is a
cohort-ending freeze change; actual `quote_captured_at` is preserved
in every record and nothing is ever retimestamped (git commit dates
are author-controlled and are not evidence of arrival time; the
standard is commit SHA + a GitHub-generated receipt); market-anchored
output never enters any metric and never contaminates the candidate's
`estimate_p`.

**Approval of this preregistration authorizes the specification only.**
Each of the following remains a separate owner decision, none of
which is granted by the freeze:

1. **Real-data evaluation.** No scored run of any kind; the attempt
   clock starts only under the §5 execution ruling.
2. **Holdout access or consumption.** None, at any stage; the
   historical folds use development-window seasons (2013–2025) only.
3. **Forward-capture activation.** No capture, no dry-run slate, no
   workflow, no scheduling — the future CFB forward-capture design
   plus its own approval sequence are required first.
4. **Registry adoption.** Named as a prerequisite (§3.1/§5); the
   freeze does not perform it, and no evaluation may begin before it
   lands.
5. **Status, label, or tier changes.** All families remain
   UNVALIDATED; no card vocabulary, eligibility score, deployment
   state, or RESEARCH_ONLY label changes under this program at any
   outcome. Promotion, if ever proposed, is a post-verdict owner
   decision requiring the M2 market leg.
6. **New data acquisition.** No Kalshi use, no Odds API credit spend,
   no new source signup, no paid data.
7. **Any ruling on other programs.** G2 attempt 2, Lane A, the
   bakeoff's disposition, and the Form 2 / loader / archive questions
   are untouched by this program.

### 3.10 Differences from the draft (complete list)

1. §10 rulings filled in: CAND_2 (+ BASE-1), CFBD DESCRIPTIVE_ONLY
   as-is, both-FBS population, folds 2021–2025 / burn-in 2013–2020 —
   each recorded RULED in the bindings config (`decided_by: Isaac
   (owner), delegated to Rocky's judgment 2026-10-13 ~21:57 CT`).
2. Historical-leg scope: three families; team_total forward-only
   (data finding: zero historical team-total lines; implied
   construction not adopted). Draft §§1/2.4/5.1 team_total historical
   provisions are superseded by §3.1/§3.5 accordingly; §5.5's forward
   team_total gates stand unchanged.
3. Attempt unit restated to the ruled scope (§3.8) — budget and all
   consumption rules unchanged.
4. Per-fold scored counts restated from the bound data (§3.4 table),
   discharging the draft's §4.1 restatement rule.
5. Designated provider named (Bovada) as a freeze-time ratification
   (§4/R1) rather than an open designation question; FBS override
   table named (§4/R2); quarantine disposition named (§4/R3).
6. Nothing else. Every threshold in draft §5 — the pooled-CI +
   ≥3-of-5 gate, the 2,500 pooled floor, the 500 fold floor, the 75%
   coverage presumption, the calibration band, the forward targets
   (300 games / 20 blocks, single extension to 600) — is carried
   verbatim.

---

## 4. Freeze-time ratifications — evidence for R1–R3

One owner confirmation at freeze time covers all three. Each item is
currently a bindings-layer declaration whose status string says, in
so many words, *not owner-ruled*; the freeze is the act that rules
them.

### R1 — Designated provider for the lines snapshot: **Bovada**

*Status in the bindings config:* `designated_provider: "Bovada"`,
`designated_provider_status: "BINDINGS_DEFAULT_NOT_OWNER_RULED"`.

*Evidence (measured by the bindings from the pinned archive,
`sportsdataverse/cfbfastR-data` @ `f5a05dc815951b8dbe18961a824f34cf154dfa61`,
contract `CFB_HISTORICAL_MARKET_SOURCE_V1`, triple-verified: SHA-256
`7ae899d903…`, size 7,047,701, git blob SHA-1 `fe568cf1ef…`):*

| Provider | Games with any market | ML ok | ML quarantined | Spread ok | Total ok |
|---|---|---|---|---|---|
| **Bovada** | **4,325** | 3,588 | 220 | 4,324 | 4,323 |
| ESPN Bet | 3,541 | 1,524 | 68 | 3,529 | 3,532 |
| William Hill (NJ) | 3,105 | 0 (no ML in archive) | 0 | 3,105 | 3,103 |
| DraftKings | 2,379 | 2,128 | 122 | 2,370 | 2,259 |

- Bovada is the largest single-book coverage for **every scored
  family**; its spread and total attribution verified **clean** (zero
  quarantines, structural mirror/agreement checks passed archive-wide).
- Under Bovada the matched counts clear every floor with margin
  (pooled ML 3,335 vs the 2,500 floor; lowest fold 633 vs 500) — the
  designation is not load-bearing for feasibility, only for identity:
  the preregistration must name *which* book's stored close the
  descriptive comparison describes (draft §2.1 defect 3).
- The designation governs the **descriptive** comparison only (CFBD is
  DESCRIPTIVE_ONLY by ruling). It confers no verdict role.
- *What ratifying does:* converts the bindings default into the frozen
  designation recorded in the snapshot contract. *Alternative the
  owner may substitute at freeze:* another single provider, or a
  multi-provider consensus rule — either changes the snapshot build
  and therefore the candidate identity in §1, so it must happen
  **instead of**, not after, naming the SHA.

### R2 — FBS membership override table: **`FBS_MEMBERSHIP_OVERRIDES_V1`**

*Status in the bindings config:* `status:
"BINDINGS_DECLARED_NOT_OWNER_RULED"`, basis: *"NCAA FBS reclassification
public record; each entry lists the seasons in which the program's
FBS status differs from the current-state directory table. The freeze
ratifies or replaces this table."*

*Why it exists (bindings finding):* the upstream CFBD per-season
team-info files are a **single current-state table stamped per year** —
the nominal-2013 and nominal-2021 files agree on
conference+classification for all 1,840 shared teams, and James Madison
is listed Sun Belt/FBS in the "2021" file although it was CAA/FCS that
season. The directory snapshot is therefore bound as identity +
current-state classification only, and season-effective FBS membership
— which the both-FBS population rule (§3.4) is made of — comes from
this table. No 2025 file exists upstream; the bound table is the
2024-named file of the same series.

*The table (team id; table classification; deviating seasons):*

| Program | Id | Table says | Deviating seasons |
|---|---|---|---|
| Appalachian State | 2026 | FBS | FCS in 2013 |
| Georgia Southern | 290 | FBS | FCS in 2013 |
| Old Dominion | 295 | FBS | FCS in 2013 |
| Charlotte | 2429 | FBS | FCS in 2013–2014 |
| Coastal Carolina | 324 | FBS | FCS in 2013–2016 |
| Liberty | 2335 | FBS | FCS in 2013–2017 |
| James Madison | 256 | FBS | FCS in 2013–2021 |
| Sam Houston | 2534 | FBS | FCS in 2013–2022 |
| Jacksonville State | 55 | FBS | FCS in 2013–2022 |
| Kennesaw State | 338 | FBS | FCS in 2013–2023 |
| Delaware | 48 | FCS | **FBS in 2025** |
| Missouri State | 2623 | FCS | **FBS in 2025** |
| Idaho | 70 | FCS | **FBS in 2013–2017** (FCS thereafter) |

*Evidence of care, and the risk being ratified:* the snapshot builder
refuses to build if an override's id or base classification disagrees
with the table — a guard that caught a wrong id during construction
(Georgia Southern is 290, not the 2047 first written) — and every
Illinois-registry id resolves in the bound directory. The residual
risk the owner accepts by ratifying: if a deviating-season entry were
wrong, the population would misclassify that program's games in those
seasons (wrongly included as FBS-population or wrongly excluded as
`POPULATION_NON_FBS_OPPONENT`). The entries above are the complete
surface of that risk — thirteen programs, named.

### R3 — The bound dataset and its exclusion disposition, exactly as counted

*What is ratified:* that the freeze pins the dataset **as built and
counted by the dry run** — population 9,536 (results snapshot 11,495
games; exclusions: 511 Illinois fixtures, 1,446 non-FBS-opponent
games, 2 unresolved-team games) and pooled matched 3,335 / 3,773 /
3,773 / 0 (§2 table; per-fold counts in §3.4) — **including the
disposition of every flagged record class**:

- **220 designated-provider (Bovada) moneyline quarantines stay
  quarantined:** **214** records whose moneyline pair contradicts the
  spread favorite's sign (`ML_SPREAD_SIGN_INCONSISTENT` — the archive's
  side-attribution defect: a coherent pair attached to the wrong
  schools) and **6** uncheckable pairs. Disposition: excluded from the
  matched set; **never repaired, never silently side-swapped, never
  counted as scored games or as misses.** Moneyline sides are admitted
  only when assigned by school identity **and** passing the
  spread-sign cross-check; that structural rule, not anyone's
  after-the-fact judgment, produced the quarantine. (Context: the
  defect is archive-wide — DraftKings 122 and ESPN Bet 68 quarantined
  under the same check — but only the designated provider's records
  bind this evaluation. Spread and total attribution verified clean:
  zero quarantines for those markets across **all** providers.)
- **58 orphan line records** (`LINE_RECORD_WITHOUT_RESULTS_GAME` —
  game ids absent from the results snapshot, an ESPN/CFBD id
  divergence on a small set) stay excluded; they were not joined by
  name.
- **3 post-kickoff line records** (`POST_KICKOFF_LINE_TIMESTAMP` —
  the PIT canary firing on real data: CFBD `date_time` 62 min–2 h
  after the schedule's kickoff, consistent with kickoff-time changes)
  stay excluded and flagged.
- **8 unresolved directory ids** (all all-star/exhibition entities —
  "Team Gaither", "Team Robinson", "SOUTH All-Stars", "American", …;
  no real program is unresolved) stay unresolved; their 2 affected
  games stay excluded as `BLOCK_TEAMS_UNRESOLVED`.

*What ratifying does:* fixes the dataset's identity so that §3.8 kill
criterion 1 (any frozen object's hash differs → abort before parse)
has an unambiguous referent, and so no excluded record can re-enter
the cohort by a later judgment call. A corrected snapshot would be a
new version and a cohort-ending freeze change (§3.9).

---

## 5. Remaining gates after the freeze

The freeze completes the *specification*. Three gates remain between a
frozen preregistration and any scored run, in order:

1. **Family-level registry adoption lands** (integration lane).
   Adoption of the four CFB surface ids (`moneyline`, `spread`,
   `total`, `team_total`) into the family-level registry, with engine
   states from the registry surfaces. **Candidate vehicle: PR #2217
   (family registry) — 11/11 hosted CI green, still DRAFT.** Adoption
   counts **when merged**, not while draft and not on CI green alone.
   Per the draft (§1.1/§9 item 5) and the harness pre-flight, **no
   evaluation may begin before this lands.**
2. **Separate owner EXECUTION ruling.** The freeze does not start the
   attempt clock (§3.8) and does not authorize a scored run (§3.9 item
   1). The execution ruling is the owner's separate act, issued after
   the freeze and after gate 1.
3. **Then the run.** Under the execution ruling: the ruled switches
   and the named freeze SHA are applied to the harness configuration
   on the frozen tree, the `SPORTSEDGE_EVIDENCE_UNIT_V1` freeze
   manifest is populated, the pre-scoring verification battery runs on
   the frozen tree (§3.8 kill criterion 4 — frozen-math fixture checks
   and disabled-factor zero-contribution checks against the actual
   frozen code), and only then does scoring begin. That run, if
   completed, is **attempt 1 of 3**.

Nothing else is outstanding: the bindings exist and are verified
(§2), the counts are restated (§3.4), and the three freeze-time
ratifications (§4) are discharged by the freeze act itself.

---

## 6. Package integrity

- **No freeze SHA has been written into any consuming file.**
  Verified at preparation: harness config on the candidate tree —
  `freeze_sha: null`, all ruling switches `UNRULED` (the shipped
  config is untouched; applying the rulings is a freeze-step act);
  bindings config — `freeze_sha: null`, `execution_authorized: false`;
  dry-run manifest — `freeze_sha: null`, `freeze_status:
  NOT_ESTABLISHED`. The candidate SHA appears **only** in this
  package, as a proposal.
- **No evaluation was executed for this package.** No probability was
  computed for any real game (manifest: `probabilities_computed:
  false`); the attempt ledger stands at 0 of 3 consumed.
- **Files in this package's evidence base:** `PREREGISTRATION_DRAFT.md`
  (SHA-256 `57f1d81b1c…`), `HARNESS.md`, `BINDINGS.md`,
  `snapshots/DRY_RUN_MANIFEST.json` (SHA-256 `d6a1e30a1c…`),
  `snapshots/SNAPSHOT_MANIFEST.json`, the three snapshot files
  (§1.1), and this `FREEZE_PACKAGE.md`.

*Prepared by the Muse lane (CFB), October 13, 2026. This package
proposes the freeze; it does not perform it.*
