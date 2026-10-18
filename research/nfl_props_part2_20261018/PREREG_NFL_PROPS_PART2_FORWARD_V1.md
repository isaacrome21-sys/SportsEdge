# PREREGISTRATION — NFL player yardage/reception props: forward test vs captured DraftKings prices (Part 2)

**Status: FROZEN — Oct 18, 2026, by owner ruling (Isaac, ~15:25 CT).**
This document is frozen as committed. Any change to the construction, the
sample-size/verdict block (§4), the bias test (§5), or the missing-close rule
(§4.5) is a new version with its own preregistration; it does not ride on
this one.

**Boundary (owner ruling, Oct 18 ~08:46 CT):** everything priced before this
package was committed is history. The Oct 18 London rows and all of the
Oct 18 slate rows are **HISTORICAL RECORD — never prospective entries of this
test**, whatever their provenance. The prospective sample opens with the
first slate priced from this committed code, inputs, and document (first
reachable slate: TNF Thu Oct 22, 2026).

**Part 1 (provenance):** the construction below was verified Oct 17, 2026 as
CALIBRATED_CANDIDATE, 4 of 4 markets, against both historical baselines
(player history B1, league role B2), 2020–2025, under the hash-locked
calibration preregistration `PREREG_NFL_PROPS_CALIBRATION_V1.md`
(sha256 `bef8d74ee1bfd3f1a753872c3e5fe428fbd00b6b98b5b911b4f8324ac1a7a148`,
carried byte-identical in this package, with its `SPEC_HASHES.txt` and
result `REPORT.md`). That verdict is calibration only. This Part 2 forward
test is the next step Part 1 called for — **not** another historical run.

## 1. The construction (wired unchanged)

Evaluator: `eval_nfl_props_calibration_v1.py`, carried into this package
**byte-identical** to the verified Part 1 file
(sha256 `66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b`;
git blob `037be88a2f9b48c479c4ca01c00a4311cbc80e08` on branch
`research/nfl-sides-elo-v1-20261017`). The Part 2 runner imports this
module's construction functions (`MARKETS`, `mu_for`, `candidate_cdf`,
`emp_cdf`, `crps`, `boot`, `K`) — it does not reimplement them.

Per-player predictive distributions for four markets, built from the
player's own prior same-season games:

| Market | Stat | Role filter on prior same-season games |
|---|---|---|
| PASS_YDS | passing_yards | position QB, mean attempts ≥ 20 over ≥ 3 prior games |
| RUSH_YDS | rushing_yards | mean carries ≥ 8 over ≥ 3 prior games |
| REC_YDS | receiving_yards | mean targets ≥ 4 over ≥ 3 prior games |
| RECEPTIONS | receptions | mean targets ≥ 4 over ≥ 3 prior games |

- Mean: μ = (Σ prior same-season values + K·G) / (n + K), **K = 3**, where G
  is the mean of the stat over all role-qualified player-weeks of that
  market in strictly earlier weeks of the same season (previous season's
  full qualified set for the season's opening weeks), exactly as the
  evaluator's `league_pool` defines it.
- Distribution: yards ~ Gamma with mean μ and coefficient of variation
  c_m; receptions ~ negative binomial with the same mean and variance
  (Poisson where var ≤ μ), exactly as `candidate_cdf` defines.
- **c_m (per market)** is the pooled coefficient of variation of
  (outcome / μ) over role-qualified player-weeks of the **2018–2019
  training seasons only**, from the hash-pinned input files
  (`SPEC_HASHES.txt`). **CV source: POOLED for all four stats** — the
  committed code computes one pooled constant per market; no within-player
  CV exists anywhere in the construction. This is the recorded CV source
  for the §5 bias test.

## 2. Universe, captures, pricing

- **Universe:** every paired DraftKings main-line prop in the four markets,
  for every game on each NFL slate, captured BEFORE kickoff of that game —
  paired meaning both sides of the same half-line from the same capture,
  with the capture timestamp recorded. Captures come from the operative DK
  capture flow; a capture row must carry the player's **nflverse
  player_id**, resolved at capture time. A row whose identity cannot be
  resolved to exactly one nflverse player is excluded and the exclusion is
  recorded — identity is never guessed.
- **Qualification:** a row is priced only if the player satisfies the
  construction's own role filter (§1) on point-in-time priors (games
  completed before the slate's week; never the game being priced). Rows
  failing qualification are committed as `NOT_QUALIFIED` with the reason
  and are excluded from all scoring — the construction defines no
  distribution for them, and none is invented.
- **Committed per-row record** (written before kickoff, create-only):
  game, player, market, line, both DK prices + capture timestamp, μ, c_m,
  games logged n, shrink weight w = K/(n+K), pool mean G, model
  probability for both sides, fair odds for both sides, EV for both sides,
  the model-selected side (higher EV; an exact tie is recorded `TIE` and
  excluded from the §5 under-rate denominator), entry no-vig probabilities
  (multiplicative de-vig of the paired prices), and the B1/B2 reference
  material (the player's prior values; the market pool snapshot is stored
  once per run). Each run record also stamps the sha256 of this document,
  of the evaluator file, and of the current-season player-data file.
- **Closing capture:** the final pre-kickoff capture for each game
  supplies that game's closing prices. Close attachment matches on
  (game, player, market, line) and records both closing prices + the
  closing capture timestamp. A close row timestamped at/after kickoff is
  not a close (see §4.5).

## 3. Scoring

After each slate, per priced row:

- **Outcome:** the player's realized stat for that game (nflverse,
  regular season). Over wins iff value > line; under wins iff value <
  line; value == line is a push (possible only on integer lines).
- **Win/loss (secondary):** the model-selected side's result. Pushes are
  graded rows but are excluded from the win/loss denominator.
- **Log loss:** the model's stated probability for the realized side,
  reported alongside the entry de-vigged DK probability's log loss on the
  same rows.
- **CRPS:** the candidate distribution's CRPS vs the B1 (player-history
  empirical) and B2 (league-role empirical) distributions, computed from
  the stored priors/pool with the evaluator's `crps` — the Part 1
  comparison, carried forward.
- **Calibration:** model probabilities by decile, including the
  extreme-decile overconfidence check Part 1 flagged (top decile stated
  vs realized), reported per market and pooled.
- **CLV (PRIMARY verdict metric):** for the model-selected side,
  CLV = closing no-vig probability − entry no-vig probability, in
  probability points. The market's mean CLV is reported with a 95% CI
  from the evaluator's block bootstrap **clustered by game** (blocks =
  game_id). CLV is computed only over rows with a readable close (§4.5).

## 4. Sample size and verdicts — FROZEN (owner ruling, Oct 18, 2026)

Ruled: option **C** (slate-based floor), **with both amendments** —
(1) games counted alongside rows, intervals clustered by game;
(2) CLV primary, win/loss secondary — **plus the missing-close rule**
(§4.5). Neither amendment changes the ruled core.

### 4.1 No verdict review before ALL of:
- **4 full slates** completed under this package (a slate counts only if
  its pricing run covered that game day's full DK board in the four
  markets — no partial-day pricing), AND
- **50 graded passing-yards rows** in the accumulated sample, AND
- **40 distinct games per market** (distinct games contributing graded
  rows to that market; rows from one game share one game script).

### 4.2 Per-market verdicts
Verdicts are issued per market, never pooled across markets.

### 4.3 Metric hierarchy
CLV (no-vig probability, clustered by game) is the **primary** verdict
metric. Win/loss is **secondary** and is reported with every readout but
decides nothing on its own.

### 4.4 INSUFFICIENT_SAMPLE
Any market with fewer than **100 graded rows** is `INSUFFICIENT_SAMPLE` —
no verdict for that market, whatever the other gates say.

### 4.5 Missing-close rule (frozen)
CLV needs both sides of the prop at the final pre-kickoff capture. When
that close cannot be read:
- The row is labeled **`CLV_MISSING`**. It **stays in the win/loss
  count**, is **left out of the CLV average**, and is **never filled in
  from another time or source**.
- The **share of CLV_MISSING rows per market is reported with every
  readout**.
- If **more than 20% of a market's rows are CLV_MISSING**, that market's
  CLV verdict is **INSUFFICIENT_CLOSE_DATA**, whatever its row count
  (its calibration results may still be reported — a calibration report,
  not a market verdict).

### 4.6 Verdict rule at a review
At a verdict review (gates in §4.1 met), per market:
- Fewer than 100 graded rows → **INSUFFICIENT_SAMPLE** (§4.4).
- CLV_MISSING share > 20% → **INSUFFICIENT_CLOSE_DATA** (§4.5); no
  BEATS/DOES_NOT verdict issues for that market.
- **BEATS_MARKET** iff the game-clustered 95% CI for the market's mean
  CLV lies **entirely above 0**. Otherwise **DOES_NOT_BEAT_MARKET** — the
  burden of proof is on the model.
- Calibration reporting (§3) accompanies every readout regardless of
  verdict. **No verdict creates a PLAY.** PLAY stays closed until the
  owner rules on a completed verdict.

### 4.7 Every readout reports, per market
Graded rows; distinct games; CLV_MISSING count and share; mean CLV with
its game-clustered CI; win/loss (pushes shown separately); log loss
(model and de-vigged DK); CRPS vs B1/B2; calibration deciles incl. the
extreme decile; the §5 stratified under-rate table.

## 5. The under-tilt bias test (issue #2388) — folded into the setup

The first prospective run does two jobs: it opens the forward test AND
serves as the bias test. Committed before the first slate is priced:

- **Slate-wide under-rate:** across all priced rows in the four markets,
  the fraction of rows whose higher-EV side is the UNDER (exact EV ties
  excluded from the denominator, counted separately), reported slate-wide
  and stratified by:
  - **games logged** (the player's prior same-season game count: buckets
    **1–3, 4–5, 6–9, 10+**), and
  - **shrink weight** w = K / (n + K) (tiers: **w ≥ 0.43; 0.25 ≤ w <
    0.43; w < 0.25**).
- **CV source record:** for each yardage stat, the coefficient-of-variation
  source is recorded in the run record as **WITHIN-PLAYER** or **POOLED**.
  As committed (§1), the source is **POOLED** for PASS_YDS, RUSH_YDS,
  REC_YDS, and RECEPTIONS — stated from the code, not assumed.
- **Decision rule (from #2388, verbatim in effect):**
  - Under-rate **≥ 80% in the early buckets** (low games logged / high
    shrink weight), not elsewhere → the tilt is a **SMALL-N ARTIFACT**.
  - Under-rate **elevated in EVERY bucket** → the tilt is structural in
    the **ROLE POOLS**, and the corrective direction is role-conditional
    pools (WR1s against WR1s), as a **separately preregistered v2** —
    never a silent patch to this construction.
  - The rule is read off the stratified table at the first verdict
    review, not off the slate-wide number alone.

## 6. Test 1 — archival replay

The archival replay defined under #2388 runs against the COMMITTED Part 2
code (the scratch module that produced the Oct 18 morning rows is
unrecoverable by design and is not a dependency): replay the construction
over archival weeks with point-in-time priors, and report the same
stratified under-rate table (§5) for the archival sample, with the same
decision rule. Archival results are a SCREEN — labeled as such, never
prospective evidence.

## 7. Integrity bindings

- Code, inputs, fitting rules, and this document: committed before
  pricing. The evaluator file is hash-pinned (§1); the runner refuses to
  price if the evaluator on disk does not match the pin, or if the
  hash-pinned 2018–2019 training inputs are missing or mismatched.
- Captures: paired, timestamped, pre-kickoff; a capture that misses
  kickoff is excluded and the exclusion is recorded.
- No retrospective additions: a row not committed before its game is
  history, filed with the published-card evidence if it was published,
  never in the prospective sample.
- Closes are never backfilled (§4.5): a missing close is a recorded
  CLV_MISSING, not a gap to be repaired later from any source.
- Role news (inactives, depth-chart changes) is recorded alongside each
  slate's rows as context. The construction as committed does not consume
  it; flags are annotations, not adjustments.
- **The Oct 18 London rows and all Oct 18 slate rows are HISTORICAL**
  (see §header and the published-card evidence record for the London
  fixture). They are graded as history and never counted toward this
  test's sample, its gates, or its verdicts.

*Frozen Oct 18, 2026. Owner ruling: Isaac (sample-size option C with both
amendments and the missing-close rule, confirmed in the main chat
~15:25 CT). Prepared by Rocky from PREREGISTRATION_DRAFT.md (Oct 18,
~08:48 CT) and SAMPLE_SIZE_DECISION_BRIEF.md (Oct 18).*
