# Build report — M50 full-game terminal-score readouts

**Starting main:** `7a189b001a8f3a1beb2b1dfe554d400baac3323d`  
**Branch:** `feat/mlb-m50-final-score-readouts-20261020`  
**Build status:** DRAFT, RESEARCH ONLY, **UNVERIFIED**, NO ELIGIBILITY CHANGE.

## What is implemented
One existing full-game distribution produces four *terminal score* readout families without re-fitting or inventing a score-path model:

1. BOTH_TEAMS_TO_SCORE_RUNS (the 1+..9+ YES/NO ladder).
2. CORRECT_SCORE (exact final scores plus mandatory ANY_OTHER).
3. WINNING_MARGIN (complete signed-margin partition; canonical runner routing **not** changed).
4. TEAM_TOTAL_ODD_EVEN (the selected team's final-run parity).

The F5-derived readout's grammar and Jeffreys half-cell prior are reused. Every output preserves the existing full-game distribution SHA, has a new readout SHA, `RESEARCH_ESTIMATE_UNVALIDATED`, `eligible=false`, and `NO_MARKET_TEST`. No changes to engines, data dependencies, registry, quote binding, RUN IT, card labels, or historical records.

## Independent-final-marginal tie artifact — measured disclosure

The source score joint is the **independent product of the two final-score marginals**, not a coherent terminal-score model conditioned on baseball's no-final-tie rule. In the reviewed reference joint, the sum of **tied final-score cells is 0.1933 (19.33%)**. The derived `WINNING_MARGIN` **TIE** readout is **0.1775 (17.75%)**, a posterior-stabilized expression of that same artifact, **not** an actual tie probability. An official MLB final score cannot be tied: the real final-tie event probability is **0**. The eleven-way `WINNING_MARGIN` **TIE bucket** and exact tied `CORRECT_SCORE` cells (including 0-0 and 1-1) inherit the nonphysical mass; no historical validation should treat it as signal. Both 0.1933 and 0.1775 are figures from the reviewed reference case, **not** a claim of population calibration or an executed screen.

**Frozen-screen scoring decision:** retain the unmodified eleven-way candidate probabilities, **including its TIE bucket**, for complete-partition multiclass Brier and log loss. For each verified official final, the observed `WINNING_MARGIN=TIE` indicator is **0** and the observed winning-margin class is the actual untied margin. Therefore the nonphysical predicted TIE mass is penalized under proper scoring; **do not collapse TIE, redistribute its probability, renormalize other bins, or silently ignore its loss**. For the correct-score frozen partition, exact tied-final cells also have observed indicator **0**; retain and penalize their predictions. This is a disclosure/scoring rule only: no source joint, readout, frozen selection list, engine, or eligibility changes.

## Honest exclusions
* EXTRA_INNINGS: final score does **not** disclose whether tied after nine.
* RACE_TO_RUNS, inning timing, bottom-of-ninth, first scoring play, etc.: ordered score/play path required.
* GRAND_SLAM: complete bases-state play-event history required.
* Correct score and margin **do not** accept an incomplete bookmaker partition. No DraftKings quote or settlement-cell completion is ever fabricated.
* The canonical named blockers **remain active**. This is a research building block, NOT operational pricing.

## Parity & scoring state
* **Synthetic first-screen parity**: 12 pytest functions / 27 parametrized test cases *authored* to check identical-joint BTTS/correct-score/winning-margin equality to the independently merged F5 readouts, raw probability conservation, reproducible hashes, reject invalid score mass, and preserve incumbent distribution state.
* **Execution:** NO TEST PASS CLAIM as of this build; hosted CI and Rocky must independently verify the exact head.
* **Historical calibration:** NOT RUN. `SCREEN_SPEC_DRAFT.md` predeclares 2025 regular-season PIT evaluation, scoring metrics, baselines, family partitions and honest verdict thresholds. The required independently pinned game feed and observed-at completeness packet were not available to this build. **No BEATS_BASELINE / DOES_NOT_BEAT_BASELINE claim yet**. No tuning from screen outcomes permitted.
* **Against market:** NO_MARKET_TEST (no paired historical full-game exotic odds). Even favorable calibration would not justify promotion.

## Files (Git blob SHA-1, not SHA-256)
* `sportsedge/mlb_m50_terminal_score_readouts.py`: `3f31af14280cd2b38550ac4658f04963b14082e7`
* `tests/test_mlb_m50_terminal_score_readouts.py`: `92c53d90cd6f0bc06134d1b57e2eb2813a7698db`
* `research/mlb_m50_terminal_score_20261020/SCREEN_SPEC_DRAFT.md`: `a8642d998f08e11b797bb3ee3d9a036e157a62eb`

## For independent verifier (Rocky)
Review exact PR head; run synthetic parity and negative tests; run the untouched incumbent full-game distribution test battery. Verify the M50 gate and `market_coverage` winning-margin route are byte-identical to base, no `PLAY`, `EV`, probability label or threshold drift. Confirm every supported selection is a function solely of FINAL score and every excluded selection requires inaccessible state. Require owner approval of screen spec and feed pins before consuming the first chronological 2025 screen. If any new version is needed after the screen, open a new version/clock.
