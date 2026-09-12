# NFL V2D score-state research contract

Status: **RESEARCH / DIAGNOSTIC ONLY**

V2C established that additional ridge/kernel/residual-bandwidth tuning on the already-observed outer folds is not a legitimate promotion path. V2D therefore changes the conditional-mean representation rather than extending the observed hyperparameter search.

## Frozen hypothesis

Predict **home score and away score directly**, then derive margin and total from the joint score distribution. The model may use only point-in-time, market-blind football state available before kickoff.

Candidate state families:

- side-specific offensive efficiency and opponent defensive efficiency;
- pass/rush efficiency and pressure interaction;
- QB identity plus point-in-time QB adjustment;
- prior/team efficiency with frozen prior weighting;
- rest, travel, timezone, short-week and bye state;
- weather/roof state already admitted by the NFL M2 feature contract;
- optional position-matchup fields already admitted by the frozen feature contract.

No sportsbook spread, total, price, implied probability, consensus value, closing value, ticket/handle split, capper opinion, or held-out result may enter feature construction, fitting, hyperparameter selection, or distribution derivation.

## Development boundary

The historical folds already observed through V1/V2A/V2B/V2C are **development evidence**. They may be used to falsify V2D, but repeated architecture/hyperparameter edits in response to their outer results may not be used to claim promotion evidence.

Any tuning must be selected using training-only inner walk-forward data. The outer held-out season is unavailable to the selector. Deterministic tie-breaking is mandatory. Market mutation and held-out-outcome mutation invariance tests are mandatory.

## Distribution requirement

V2D must produce a coherent integer `(home_score, away_score)` distribution before any market line is applied. Margin and total probabilities are derived from those same paths. Key-number mass may emerge only from football score mechanics or train-observed residual/state structure; it may not be inserted to target ±3/±7.

The first implementation should prefer the smallest architecture that tests the hypothesis. Do not add a new hyperparameter sweep merely because V2C selected a grid boundary.

## Frozen evaluation gates

Evaluation remains unchanged:

- exact-SHA source/artifact binding and byte determinism;
- market-blind feature audit;
- season-ordered outer walk-forward;
- existing calibration contract and threshold;
- existing >= 0.65 fold-win requirement;
- existing signed ±3/±7 key-number tolerance;
- existing CLV/eligibility/Truth Gate requirements;
- no production registry or eligibility change from diagnostic evidence.

A green workflow is not a model PASS.

## Promotion rule

Even if V2D clears historical diagnostic gates, those already-observed folds are not sufficient for promotion. Promotion requires genuinely fresh forward confirmation under the frozen contract, plus the normal paired market/CLV and Truth Gate evidence. Until then all affected NFL markets remain blocked and NFL props remain `NO_ENGINE`.

## First implementation slice

1. Add a diagnostic V2D model that fits separate home-score and away-score conditional means from the existing market-blind M2 feature vectors.
2. Preserve a coherent paired residual replay in home/away score space and deterministic score reconciliation.
3. Add invariance tests proving market fields cannot affect the model and outer held-out outcomes cannot affect training-only selection.
4. Add an isolated historical diagnostic evaluator; do not modify production M2.
5. Emit V2D validation and signed key-number artifacts under the existing frozen gates.
6. Stop and record the result. Do not hand-tune against the observed outer-fold failures.