# Build report — Result After Nth Inning 3/5/7

**Starting main**: `2ed6ed711528070e8dc1ccadaeb49e086ba3620a`  
**Branch**: `feat/mlb-result-after-357-readout-20261020`  
**Status**: DRAFT / RESEARCH ONLY / NO GATE CHANGE / **NOT INDEPENDENTLY VERIFIED**.

## What was built

A single, conservative readout `read_result_after_inning` for `RESULT_AFTER_INNING_{3,5,7}`. It **does not fit a new distribution**. It uses the exact existing, unchanged F3, F5, F7 moneyline HOME and AWAY probabilities. The original period-moneyline PUSH is precisely the TIE outcome of the three-way result-after market. These three outcomes must conserve mass to 1; no tie probability may vanish or be rescaled.

`RESULT_AFTER_INNING_2`, `_4`, `_6`, `_8` remain named refusals (`NO_CUMULATIVE_DISTRIBUTION_FOR_INNING_N`) because no sanctioned joint exists. Individual `INNING_N_*` markets remain separate and blocked. No pricing, model data intake, DraftKings quote route, registry or deployment wiring, eligibility, staking, PLAY/LEAN change, or gate mutation is made. Existing M22 `sportsedge.mlb_per_inning_gates` remains authoritative and unchanged.

### Artifacts / immutable blob identities

* `research/mlb_result_after_357_20261020/SCREEN_SPEC_DRAFT.md` — Git blob `94f8767d56706adec4da831e326a210a05f20277`.
* `sportsedge/mlb_result_after_inning_readouts.py` — Git blob `667ea27b68f5683c330fdb7fc496d045f1ec8b6e`.
* `tests/test_mlb_result_after_inning_readouts.py` — Git blob `8049ec21277b1d09bef4db178a4bf4ca7500312a`.

These are Git blob SHA-1s, not the independent source-data SHA-256 pins required for historical evaluation.

## Parity / screen status

* 27 parametrized synthetic pytest cases **authored** for direct parity with both incumbent home/away moneylines, exact tie preservation, three-way mass conservation, wrong-period failures, unsupported N refusals, invalid joint rejection, stable readout hashing, no prices/EV and existing gate preservation.
* **Not yet independently executed:** no test count is claimed passed. Hosted CI and Rocky's independent exact-head probes required.
* Historical 2025 regular-season screen **not executed**: owner approval and pinned complete PIT inning history/observed-at archive needed first. The draft screen predeclares chronological three-way Brier/log loss versus strictly-prior 3-class climatology; proper verdicts include DOES_NOT_BEAT_BASELINE and INSUFFICIENT_DATA.
* Historical DK 3-way lines unestablished: `NO_MARKET_TEST`, `NOT_VALIDATED`, `eligible=false` regardless of any future calibration success. Research-only output cannot go to canonical priced candidate/PLAY surface.

## What remains unproven

Owner approval of source manifest and first-screen plan; correct settlement of shortened/suspended/partial innings; exact complete inning observation timing; independent head verification; hosted CI; prospective market validation. Unverified source history must never be silently backfilled. Model version/threshold changes after first observed screen results require a new construction and clock.

## Verification handoff to Rocky

Independently compare each new 3-way vector against F3/F5/F7 incumbent moneyline HOME/AWAY/PUSH on real constructed distributions, including tie mass not equal zero. Require stable SHA and exact gate equivalence. Check hostile period swaps, unrecognized / unsupported markets, and source PMF tampering; rerun neighboring tests and compare failure sets against base. Leave DRAFT; update branch and fresh CI if main has moved before merge. No merger action from builder.
