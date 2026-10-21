# Build report — M21 first-inning deep count joint (known losing challenger)

**Branch base main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `feat/mlb-first-inning-deep-count-joint-20261020`  
**Status:** DRAFT / RESEARCH ONLY / NOT VERIFIED / KNOWN ADVERSE BINARY BASELINE RESULT.

## Construction and explicit risks

A standalone, previously missing readout from a one-inning (away/home) run-count joint, using the **existing first-inning Poisson half-run marginal recipe exactly**: own for + opponent allowed count histories (10–30 per component), Jeffreys half-count rate, symmetric 50/50 blend. The two half-inning score marginals are multiplied into a joint by **assumed conditional independence**. This is *not* a demonstrated truth, and independent halves cannot be accepted from final game totals or binary NRFI rates alone. The joint carries both `conditional_independence_assumed=True` and `documented_binary_baseline_loss=True` as machine-checkable mandatory disclosures.

**Known negative evidence is binding:** the preexisting first-inning Poisson count sibling underperformed the stronger binary NRFI/YRFI engine. This module is only an unvalidated challenger intended for a separate, preregistered count-family screen. It must never claim to displace the binary engine. All outputs have `RESEARCH_CHALLENGER_KNOWN_BINARY_BASELINE_LOSS`, `NO_MARKET_TEST`, `eligible=false`, and no PLAY/stake or quote authority.

Readouts: (1) FIRST_INNING_3_WAY HOME/TIE/AWAY with a real tie cell and no three-way push, (2) FIRST_INNING_RUN_LINE with explicit integer push probability, (3) FIRST_INNING_ODD_EVEN on **total** first-inning runs. The joint explicitly stores max truncated marginal probability (tolerance 1e-13 each), normalizes each finite PMF, and refuses unresolved tail mass instead of dropping it silently. A data-lineage SHA input is needed but by itself is **not** a verified source archive or PIT proof. Strict history fixture/team identity must be attested by a separate verifier before evaluation.

**Not touched:** frozen model history, registered canonical M21 blockers, live NRFI binary logic, first-inning PBP K/BTP, odds intake, pricing, card, registry or deployment. M21 first-inning Ks and batters-to-plate **remain NO_ENGINE** until verified play-level pools exist.

## Exact artifacts (Git blob SHA-1)

* `sportsedge/mlb_m21_deep_count_joint.py`: `1d4b216a8f922d20d0b6d43bb74760f553984e3c`
* `tests/test_mlb_m21_deep_count_joint.py`: `2eacc5a90a66122dd93b77249c098e8727036784`
* `research/mlb_m21_deep_count_20261020/SCREEN_SPEC_DRAFT.md`: `691934add2da5392f88b3b83d7557b6de6703204`

## Tests and historical screen

11 new pytest test functions, several parameterized, authored to check original rate parity, explicit independence/binary-loss disclosure, partial Poisson tail, true three-way TIE and ODD/EVEN mass conservation, symmetric run-line push, invalid/nonfinite pools, missing SHA and M21 canonical gate unchanged. **No independent test execution result is claimed here**; host CI and Rocky must inspect exact head.

Historical screen prereg **DRAFT, UNFROZEN, UNRUN**; it specifies a one-shot chronological 2025 proper-scoring comparison to strictly-prior count climatology and the already-better binary model. Source archive/manifest and independent DK exotic lines are absent; no sample N, baseline verdict, CLV/ROI, model promotion or market edge claimed. Critical: this research construction would be unacceptable as a PLAY engine without new independently scored evidence.

## Reviewer handoff

Independently enumerate PMF cells against direct Poisson formula; confirm no missing probability mass/undisclosed tail, tie count when away=home, and HOME/AWAY signed run-line opposite parity. Compare YRFI marginal to incumbent (known underperforming at backtest scale). Check freeze inventory and M21 blockers byte-for-byte against base. Confirm none of K/BTP are accidentally enabled, and refuse unknown source/pool identity in production. Compare full-suite failure set against base. Leave draft until adjudicated, never auto-promote.
