# Card Status Rules

Venue support gets a price. Promotion evidence decides whether that price may be bet. TRIAL builds that evidence without pretending it already exists.

## Row status, in order

1. **NO_ENGINE**: no probability engine exists for the market (NFL/CFB props today). No data request unlocks it.
2. **BLOCKED**: Model_P missing, or a data/venue/quote/devig blocker, or not promoted and no TRIAL qualifies. Every reason is listed.
3. **OFFICIAL**: promoted, frozen edge floor exists, edge meets it. Only status with confidence.
4. **PASS**: promoted, frozen floor exists, edge below it.
5. **TRIAL**: real engine Model_P, blocked only by NOT_PROMOTED or NO_FROZEN_EDGE_FLOOR, edge at least 3.0% vs paired no-vig at the logged price, row has book, price, retrieved_at, and model artifact SHA.

## TRIAL (config/trial_policy_v1.json)

- Max 5 TRIAL plays per sport per slate, highest edge first.
- **PAPER** (0 units) by default.
- **MICRO** (0.25 units) for a market only after 200+ settled TRIAL plays across 20+ slates with mean CLV of at least +0.5pp and a cluster-robust t-stat of at least 2.0. Rechecked before every slate; failing drops it back to PAPER.
- TRIAL rows count as forward evidence only while the model artifact and this policy are unchanged. Any change restarts the clock.
- Market info, splits, and context leans never create a TRIAL play.

Retracted cards stay in the RUN IT ledger as process-correctness failures, with the time issued and retracted.

## Paste into the ChatGPT HYBRID instructions

```
CARD STATUS RULES (mandatory)
- NO_ENGINE: no engine exists. Never ask for data to unlock it.
- BLOCKED: Model_P missing, any data/venue/quote/devig blocker, or unpromoted with no qualifying TRIAL. List every reason.
- OFFICIAL: promoted + frozen floor + edge >= floor. Only status with confidence.
- PASS: promoted + frozen floor + edge < floor. Never for a market the model did not price.
- TRIAL: real engine Model_P from the pipeline, blocked only by NOT_PROMOTED or NO_FROZEN_EDGE_FLOOR, edge >= 3.0% vs paired no-vig at the logged price. Max 5 per sport per slate.
- TRIAL stake: PAPER 0u by default. MICRO 0.25u only if the market's TRIAL ledger shows 200+ settled, 20+ slates, mean CLV >= +0.5pp, cluster-robust t >= 2.0.
- I cannot create TRIAL plays from market info, splits, news, or leans. If no pipeline Model_P was provided, TRIAL count is 0.
- Log every TRIAL play at the price taken; add close price separately for CLV.
- If a card breaks these rules, retract it and log the retraction; do not delete it.
```
