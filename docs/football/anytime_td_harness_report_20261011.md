# NFL anytime-TD backtest: candidate vs naive position baseline

## Verdict: CONDITIONAL_PASS

Reasons:
- MARKET_BASELINE_MISSING: no archived market prices; the market-baseline leg of Isaac's bar could not be checked. Do not promote on this verdict alone.

| model | n | Brier | log loss | mean p | base rate |
|---|---:|---:|---:|---:|---:|
| candidate | 955 | 0.1581 | 0.4987 | 0.156 | 0.213 |
| existing | 955 | 0.1663 | 0.5141 | 0.180 | 0.213 |
| market baseline | MISSING — no archived prices; leg not checked |

Brier delta (candidate - existing): -0.0083
Log-loss delta (candidate - existing): -0.0154

## Candidate calibration (out-of-sample)

| prob bin | n | mean p | hit rate |
|---|---:|---:|---:|
| 0.0-0.1 | 329 | 0.066 | 0.112 |
| 0.1-0.2 | 379 | 0.145 | 0.208 |
| 0.2-0.3 | 152 | 0.239 | 0.289 |
| 0.3-0.4 | 68 | 0.344 | 0.353 |
| 0.4-0.5 | 20 | 0.436 | 0.600 |
| 0.5-0.6 | 7 | 0.564 | 1.000 |
| 0.6-0.7 | 0 | — | — |
| 0.7-0.8 | 0 | — | — |
| 0.8-0.9 | 0 | — | — |
| 0.9-1.0 | 0 | — | — |

_research_only: no betting authority. min_n=30._
## Coverage (playable share)

- candidate priced: 955
- baseline priced: 955
- blocked by reason: {
  "TD_HISTORY_INSUFFICIENT": 185,
  "TD_SNAP_SHARE_LOW": 119,
  "TD_SNAP_SHARE_UNVERIFIED": 7
}
- playable share (priced / (priced + blocked)): 0.754

Playable share is Isaac's health metric: fail-closed discipline must
not collapse into a machine that prices nothing.

