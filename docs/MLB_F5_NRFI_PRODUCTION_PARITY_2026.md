# MLB F5 + NRFI/YRFI production-parity confirmation (2026)

Tracking: follow-on to #1577 / #1578.

This protocol is frozen before viewing this run's 2026 result. It does not retune
the already-selected prior strength. The only challenger is the previously
selected **m30** league prior.

## Why this confirmation exists

The #1578 held-out study selected m30 on a research history surface using a
370-day regular-season-only team lookback. The live production F5/first-inning
feature source currently uses a 240-day team lookback and does not force
`gameType=R` on its team-history query. Around opening day and for clubs with
postseason history, those surfaces can differ.

Production wiring is therefore blocked until m30 is checked against the actual
live team-history semantics rather than assuming the two baselines are
interchangeable.

## Frozen data semantics

Target games:
- 2026 MLB regular-season final games with complete innings 1-5.
- Target outcomes are never model inputs.

Baseline team history:
- exact production-style history window: 240 calendar days strictly before the
  target date;
- no game-type filter on the history schedule query;
- last 30 eligible games per club;
- minimum 10 games.

League prior:
- 370 calendar days strictly before the target date;
- regular-season games only;
- both team halves enter the league F5-run PMF and inning-one scoreless rate;
- minimum 200 prior halves.

The candidate does **not** alter current Jeffreys settlement/readout shrinkage.
It adds only the frozen m30 league prior before the existing readout.

## Fixed comparisons

F5:
- `production_m0`: current empirical team/opponent F5 marginals.
- `candidate_m30`: same marginals after 30 league pseudo-games.
- Exact-score NLL is the distribution metric.
- W/T/L and O4.5 Brier are scored through the current production Jeffreys
  settlement readout.

NRFI/YRFI:
- `production_empirical_jeffreys`: current first-inning offense/opponent
  Jeffreys engine.
- `candidate_m30`: same engine plus 30 league pseudo-games.

There is no tuning and no alternative strength search in this run.

## Frozen pass rules

At least 1,000 eligible 2026 games are required.

F5 ships only if:
1. date-clustered 95% bootstrap CI of candidate-minus-production exact-score NLL
   is entirely below zero;
2. candidate W/T/L Brier is no worse than production + 0.002;
3. candidate O4.5 Brier is no worse than production + 0.002.

NRFI/YRFI ships only if:
1. date-clustered 95% bootstrap CI of candidate-minus-production binary log loss
   is entirely below zero;
2. candidate Brier is no worse than production;
3. candidate 10-bin ECE is no worse than production + 0.005.

Bootstrap: 2,000 date-clustered resamples, seed 20261005.

A passing lane may then be wired in a separate production PR with source,
probability-mass, complement, and research/production parity tests.
A failed lane remains unchanged.

## Run

Open an owner `[MLB LINES]` issue whose fenced body starts with:

```
RESEARCH f5_nrfi_production_parity
```

This is research only. No betting card is produced.
