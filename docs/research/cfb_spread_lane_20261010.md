# CFB spread-lane diagnosis — Saturday 2026-10-10

**Status:** Research / diagnostic only. Do not infer betting authority or unfreeze `VALIDATED_MARKETS`. No change to the totals model or to the model-probability calculation.

## Immutable input and reproduction

- Source: [GitHub Actions CFB SDV card run 38045215643](https://github.com/isaacrome21-sys/SportsEdge/actions/runs/38045215643), artifact `cfb-sdv-card` ID **11666932506**, `cfb_sdv_card.json`.
- SHA-256 of the extracted card JSON: `cef858bfef10d27a0f6600d8e2ee2b5bd17e072c7e81c5133127077591cc50cd`.
- Card scoring timestamp: **2026-10-10T10:32:06Z**. Card `model_status=MODEL_SDV_PUBLIC_LIVE_UNVALIDATED`. The fixed prior-card snapshot is not a new live price feed.
- Card has **41 scored games, 242 prices: 82 spreads, 78 moneylines, 82 totals**. The 4 probation candidates were all **TOTAL UNDER**.
- [Full 82-row CSV](./cfb_spread_lane_20261010_all82.csv) logs *both* spread quotes for *every* scored game: raw model home margin, market-implied home margin, post-anchor home margin, exact side/line/odds, edge percentage points, push-aware ROI, push probability, price/de-vig/anchor/ROI/floor pass flags and the original `reason`. No rows or odds were fabricated.

## Spread funnel (82 quoted selections, 41 games)

| Independent audit / gate | Count | Meaning |
|---|---:|---|
| Spread selections in scored card | **82** | Exactly 2 opposite sides/game |
| Valid opposite-side de-vig pair (#1896) | **82** | No unpaired spread market |
| Within straight-bet −165 cap | **82** | Cheapest/biggest spread price still within cap |
| Positive quoted model edge | **41** | One side/game has positive conditional-probability edge |
| At least 2.0pp edge, at most 12pp | **0** | **82/82 first rejected `BELOW_FLOOR`** |
| Positive push-aware expected ROI (#1901) | **0** | **Even without the floor, all 82 fail ROI** |
| Market-anchor ≥0.5-point forward-track threshold (#1947 path) | **2** | One game/two sides; 80 would not qualify for tracking |
| Same-game selection guard reached | **0** | No positive-ROI/edge-floor spread to arbitrate |
| Spread `LEAN` / spread probation | **0 / 0** | Correct consequence, not a bug in slot count |
| Moneyline rows marked anchor-threshold dropped | **29/78 ML rows** | Separately diagnosed: does **not** cause spread drop |
| Total `LEAN` / total probation | **19 / 4** | 4 probation candidates all UNDER; existing bias guard applied |

**The binding conditions are not one misconfigured guard.** The edge floor is the first emitted reason for every spread; independently, all spreads fail positive expected ROI at the target sportsbook odds. Relaxing the floor, forward-track gate or market cap would **not** create a positive-EV spread in this card. The highest spread edge was Texas @ Oklahoma, Texas −7.5 at −105, **+1.94pp model edge, −0.71% push-aware ROI**, still below floor and negative EV. The best spread ROI was Wake Forest −3.5 at +100, **−0.58%**, also not +EV.

### Why the spread estimates are so close to the market

The frozen [market-anchored fit](../../config/cfb_market_anchored_spread_fit_v1.json) from 2016–2025 development lines (`n=6498`) has **intercept = −0.0367627111 and weight = −0.0331741038**. The spread path uses:

`anchored_home_margin = market_home_margin + intercept + weight × (raw_model_home_margin − market_home_margin)`

On the 41-game October 10 snapshot, the median absolute raw-model-vs-market home-margin disagreement is **4.35 points**, but the median absolute post-anchor disagreement is **0.17 points**. With this negative near-zero fitted weight, the currently enabled anchor effectively follows the market; in turn the offered sportsbook vig dominates edge/ROI. This is a **model-signal/calibration question**, not a reason to bypass market anchoring, add market prices to the blind SDV feature model, or loosen the quote guards on this same observed slate.

**Key-number check:** integer spreads of ±3 and ±7 in the snapshot use the existing continuity-corrected Normal push distribution; the computed push probability is about **2.347%** for those rows. No evidence from this diagnostic establishes a key-number push bug. `model_push_p` and push-aware ROI are recorded for every spread in the CSV.

## Policy v2 (separate from totals-model work)

- Retain `config/cfb_probation_policy_v1.json` as immutable historical policy.
- New `config/cfb_probation_policy_v2.json`: **8 maximum per slate, 5 maximum per market type** (`SPREAD`, `TOTAL`, `MONEYLINE`).
- The existing edge, positive-ROI, two-sided de-vig, −165 cap, market-anchor forward threshold, same-game guard, and totals directional-bias guard stay intact.
- Preserve the same **0.25u**, kill rule, 100-bet promotion rule, no-backfill restrictions, and `LEAN` labels. Probation never becomes `BET`/`OFFICIAL`; `VALIDATED_MARKETS` stays empty.
- Runtime reads and SHA-256-stamps the v2 policy on every new card. It logs the per-market cap and the actual number selected per market.
- On **this frozen 41-game card**, a cap increase to eight cannot add spread selections: 0 spread leans pass the existing requirements, and only 4 Unders were on probation under v1.

**No guard has been loosened or model coefficients changed.** The user should review this PR and the independent totals-calibration PR before either merges.
