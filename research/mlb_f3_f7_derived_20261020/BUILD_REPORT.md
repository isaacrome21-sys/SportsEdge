# Build report — MLB F3/F7 BTTS and winning-margin readouts

**Starting main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `feat/mlb-f3-f7-derived-btts-margin-20261020`  
**Status:** RESEARCH ONLY / DRAFT / NOT VERIFIED / NO GATE OR REGISTRY CHANGE.

## Scope
Four derived readout families are constructed from existing FIRST 3 or FIRST 7 inning period-score joint, **without refitting anything**:
* `F3_BOTH_TEAMS_TO_SCORE` rung 1..7 (research readout grammar, not a claim of all DK rungs offered);
* `F7_BOTH_TEAMS_TO_SCORE` rung 1..7;
* `F3_WINNING_MARGIN` exact/terminal margin bands;
* `F7_WINNING_MARGIN` same grammar.

Exact period-object/type/innings matching required; malformed/nonconserving score joints and invalid BTTS rungs refuse. Margin selection requires entire mutually exclusive exhaustive band partition, including TIE mass. Uses the same F5 Jeffreys prior and margin selection grammar from merged engine, binds readout SHA to incumbent period-distribution SHA, and changes none of the existing period engine, quote binding, RUN IT surface, canonical market set, registry or deployment. **No odds, EV, eligibility, PLAY or staking authority.**

## Source-artifact identity (Git blob SHA-1)

* `sportsedge/mlb_f3_f7_derived_readouts.py`: `0e28eded5a632c6d8d12d45c93fa603e1e73d5eb`
* `tests/test_mlb_f3_f7_derived_readouts.py`: `78231634505666cca7a71367a8a41e6122ed3ec1`
* `research/mlb_f3_f7_derived_20261020/SCREEN_SPEC_DRAFT.md`: `72556590f6cac5f2ac67a1a12b2c351fabd82d8a`

## Tests and screening
Seven synthetic pytest test functions, parameterized over both periods/rungs, written with direct numerical parity against the incumbent **F5-derived** readout on the **identical joint score state**, plus full margin-partition mass tests and adversarial rejection. **Not yet independently executed or declared green**. Rocky needs to reproduce exact numerical readout against manually enumerated PMF and check all route/governance hashes unchanged.

Historical test: **UNRUN**. `SCREEN_SPEC_DRAFT.md` predeclares 2025 chronological first screen against strictly-prior league-period score climatology, with binary/multiclass proper scoring and confidence intervals. Independent PIT/source feed admission absent; no scores, Brier, log-loss, CLV, market odds, or baseline verdict claimed. Nothing can be promoted on these outputs.

## Hand-off
Check overlapping PRs before merge; no duplicate existing period engine. Verify direct same-joint parity, rejecting wrong-period and non-partitioned margin, preserving tie as explicit band, no readout outside researched BTTS/margin. Compare head failures against current main. Leave PR DRAFT and require owner ruling on catalog rungs and pinned historical feed before any production market action. Merge only by Rocky after reviewed fresh green CI.
