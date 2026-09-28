# CFB 2026 Week 4 card postmortem

Status: research evidence only. NOT Model_P. NOT Truth Gate. NOT OFFICIAL.

## Snapshot

The Sept. 26 research card finished 6-3 ATS, but confidence ordering failed at the top: Missouri +6 (94) lost 31-24, Texas A&M +8.5 (92) lost 35-6, and Iowa +5.5 (91) won 20-19. The remaining six plays finished 5-1.

This document is deliberately a postmortem, not a tuning target. Do not change weights or thresholds to fit these nine outcomes.

## Questions to answer before any score change

1. What exact inputs create the displayed 0-100 research score?
2. Does market distance, EV, price, ticket/handle data, RLM, or any other market-derived field enter that score directly or indirectly?
3. How is disagreement among Sasser, SP+, MySpariEdge, SportsEdge, and independent checks represented? Mean-only blending can hide dispersion.
4. Is projection freshness represented? A several-day-old projection and a same-day projection should not silently receive identical evidence status.
5. Is injury uncertainty represented as uncertainty rather than as an unsupported deterministic point adjustment?
6. Are key-number crossings distinguished from equal raw point differences?

## Required evaluation

Any scoring challenger must be pre-registered and evaluated out of sample on historical cards that were not used to choose its weights. Primary metrics:

- calibration/reliability of score buckets;
- monotonicity: higher score buckets should not perform worse than lower buckets over a sufficiently large sample;
- Brier/log loss where a probability interpretation exists;
- ATS/CLV only after a verified historical closing-line source is available;
- stability by season, conference, favorite/dog, spread bucket, total bucket, and projection-source availability.

The Sept. 26 card may be retained as a regression example but must not be used to fit or select challenger weights.

## Governance

- Preserve market-blind estimate_p generation.
- Ticket %, handle %, RLM, steam, and handicapper picks remain context only.
- No OFFICIAL promotion from this postmortem.
- Keep CFB paused until historical closing-line semantics and provenance are verified.
