# PREREGISTRATION (FROZEN): MLB Total Hits joint-path harness

- **Schema:** `MLB_TOTAL_HITS_JOINT_PATH_HARNESS_PREREG_V1`
- **Status:** FROZEN at publication of this document together with its freeze
  record (`FREEZE_RECORD_MLB_TOTAL_HITS_JOINT_PATH_HARNESS_V1.json`, same
  directory). This freeze executes **no scoring**. Scoring (step 7 of the
  integration sequence) is a separate, later task and starts only from this
  frozen text. This document grants no activation, admission, promotion, or
  betting authority of any kind.
- **Lineage:** This is the frozen form of the draft proposal
  `docs/proposals/MLB_TOTAL_HITS_JOINT_PATH_PREREG_PROPOSAL_t184.md`
  (PR #2347, UNFROZEN). Where the proposal deferred values to the owner's
  source preregistration, this document inserts them; where the proposal
  offered an optional market comparator, this preregistration **excludes**
  it (see §6: no sportsbook prices anywhere in scoring).

## 1. Candidate under test (locked construction identity)

The candidate is the **repaired** aligned-path Total Hits construction, as
merged to `main`:

- Readout module: `sportsedge/research/mlb_joint_total_hits.py`
  (`read_joint_total_hits`), git blob
  `029829688817cfca4f1362dc2bdbe806dbaab42c` — this blob carries the
  batter–pitcher witness-conservation refusals.
- Path source: `sportsedge/dfs/mlb_joint_paths.py`
  (`simulate_mlb_joint_paths`), git blob
  `50e027bc0a5551b2de9096292cc1c460567d5b63`.
- Composed construction head: `6ec17c716409cd4ff2d3d83a62bbcc0c31128d1f`
  (candidate + conservation repair composed with then-current main).
- Repair commit composed in: `db05d02335b05f36702ef248c12cb741fc2bdc8e`
  (branch `grok/t180-total-hits-red-fix-20261015`).
- Merge commit on `main`: `1a10b7ffd37d7932de20da17a91e8b64443e0f38`
  (PR #2334, merged 2026-10-16T02:57:47Z).
- Identity re-verified byte-for-byte at `main`
  `0f96676f560fc1b65010ba48da6d221b2cd26112` during step-5 verification.

Explicitly **not** the locked candidate: the original unrepaired candidate
commit `04d2c3a1b9c729a571dd368a04ce6331e51024fb` (module blob
`5fc59956b227fb056ed7b3730b75e4407db72ac2`), which the #2336 RED
conservation battery proved never reads pitcher witness values
(11 RED / 5 GREEN against it; 16/16 GREEN against the locked blob above).

The candidate hardcodes `validation_status = UNVALIDATED_RESEARCH` and has
no production importer. This preregistration does not change that.

## 2. Markets

Scored **separately**, never pooled across markets:

- `GAME_TOTAL_HITS` — total hits by both teams in one game (unit: game).
- `TEAM_TOTAL_HITS` — total hits by one team in one game (unit: team-game;
  both teams of a game are separate rows but remain clustered under the
  game for resampling, §7).

## 3. Harness parameters

- **Path count:** 10,000 simulated paths per game.
- **Seed policy:** deterministic per `game_id`:
  `seed = int.from_bytes(SHA-256("MLB_TOTAL_HITS_JOINT_PATH_HARNESS_PREREG_V1|" + game_id)[:8], "big")`.
  The same seed drives the candidate for both markets of a game. No other
  stochastic element is permitted; reruns must reproduce bit-identical
  per-game distributions.
- **Lineups:** official pregame lineups, nine batting slots per team,
  fixed for the whole game. Pitcher substitutions and batting
  substitutions are **not modelled** and are a declared limitation of
  this harness version.
- **Game type:** regular season only (`game_type = R`).

## 4. Folds (chronological, forward only, no shuffling)

- **Fold 2024:** training window = all eligible games strictly before
  2024-01-01 (through the 2023 season); scoring window = 2024 season.
- **Fold 2025:** training window = all eligible games strictly before
  2025-01-01 (through the 2024 season); scoring window = 2025 season.

A fold is scored only if its scoring window contains **≥ 500 games**;
otherwise the fold is reported `INSUFFICIENT_GAMES` and no pass may be
claimed from it (the pooled rule in §8 then cannot pass either, since it
requires every fold).

## 5. Point-in-time (PIT) discipline

Owner clause (issue #2264, 2026-10-15), binding:

> Within each validation fold, every simulator player input (including
> per-player hit/PA/outcome rates, shrinkage features and any fitted
> role/opportunity input) must be derived exclusively from games strictly
> earlier than the prediction game's cutoff; target-game and later game
> data are prohibited, even when lineups themselves are pregame.

- Every rate, feature, and baseline input for a prediction uses **only
  games strictly before that game's cutoff**. Training-window aggregates
  are computed as of each prediction game's cutoff, not as of the fold
  boundary, whenever a rate is game-specific.
- Lineups must be confirmed with a timestamp before the cutoff. Rows
  whose lineups were retrospectively backfilled are **excluded**, never
  imputed.
- Baselines (§6) obey the identical PIT rule on identical rows.

## 6. Data

- Only data already archived; no credit-consuming collectors.
- **No sportsbook prices are used anywhere in scoring** — no market
  comparator, no de-vigging, no line-based feature.
- Before any scoring run, a dataset manifest (source, row hashes, PIT
  cutoffs, fold ids) is published and hashed; the manifest hash is
  recorded in the scoring report. Scoring against an unmanifested dataset
  is invalid under this preregistration.

## 7. Metrics and uncertainty

- **Primary metric:** `MEAN_RPS` — mean ranked probability score of the
  predicted count distribution against the realized count, over half-line
  grids:
  - `GAME_TOTAL_HITS`: lines 0.5, 1.5, …, 20.5.
  - `TEAM_TOTAL_HITS`: lines 0.5, 1.5, …, 12.5.
- **Typical line** (for the ECE and log-loss legs): per fold and market,
  the grid half-line nearest the **median realized count in that fold's
  training window**; computed from training data only and recorded in the
  run manifest before the fold is scored.
- **Typical-line ECE:** expected calibration error of the over/under
  probabilities at the typical line, on the predeclared fixed bins
  [0, .1, .2, …, 1.0] of predicted probability.
- **Typical-line log loss:** mean log loss of the over/under outcome at
  the typical line.
- **Uncertainty:** cluster bootstrap resampling unit = **GAME_ID**
  (a game's game-level row and both of its team-level rows move
  together), **2,000 replicates**, bootstrap seed **20261015**, 95%
  percentile confidence interval on the paired difference
  `candidate MEAN_RPS − baseline MEAN_RPS`, computed per market, pooled
  across folds and within each fold.

## 8. Baselines and pass rule

Baselines (all PIT, §5; scored on identical paired rows):

1. `naive_team_rate_poisson` — team-rate Poisson convolution
   (declared: this baseline family is a prior FAIL from the earlier
   harness generation).
2. `league_constant_rate` — league-wide constant-rate distribution from
   the training window.
3. `trailing_20_game_team_rate` — each team's trailing-20-game hit rate.
4. `independence_convolution` — convolution of per-batter marginal
   distributions (the independence shortcut the joint construction
   exists to replace).

**"Best baseline"** in a given evaluation cell (market × {pooled,
fold}) is the baseline with the lowest `MEAN_RPS` in that same cell; all
three pass legs compare against that same baseline.

**Pass rule** — owner clause (issue #2264, 2026-10-15), binding:

> The predeclared PASS conditions must ALL hold separately for each
> market (GAME_TOTAL_HITS and TEAM_TOTAL_HITS), both in the pooled
> evaluation across folds AND in every individual validation fold. A
> pooled PASS cannot override any fold FAIL; a market-level PASS cannot
> be inferred from the other market.

For a market to PASS, in the pooled evaluation **and** in every scored
fold, **all three** must hold against the best baseline of that cell:

1. The 95% bootstrap CI for `candidate MEAN_RPS − best-baseline
   MEAN_RPS` lies entirely below 0 (CI high < 0).
2. Candidate typical-line ECE ≤ best-baseline typical-line ECE + 0.005.
3. Candidate typical-line log loss ≤ best-baseline typical-line log
   loss.

Any other outcome is a FAIL for that market and is binding negative
evidence; the same folds are not re-tuned under this preregistration.

## 9. Outcomes

- A PASS makes the market eligible to be *considered* for
  `VALIDATED_FOR_FORWARD` (forward shadow) **only after independent
  review**. It does not make the market verified, eligible for PLAY, or
  promoted, and it changes no production blocker by itself.
- A FAIL is preserved as binding negative evidence under this schema.
- Any change to §§1–8 after this freeze requires a new schema version
  and a new freeze; silent amendment is prohibited.
