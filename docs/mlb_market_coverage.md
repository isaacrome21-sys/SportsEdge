# MLB market coverage contract

SportsEdge separates **quote acquisition coverage** from **model/deployment eligibility**.

Quote acquisition is allowed to ingest every supported pregame MLB market below, but no quote can become an OFFICIAL bet unless that canonical SportsEdge market also has an independently validated model, a frozen edge floor, deployment eligibility, fresh game/player identity, and Truth Gate approval.

## Game markets
- MONEYLINE
- RUN_LINE
- TOTALS

## Batter markets
- HOME_RUNS
- HITS
- TOTAL_BASES
- RBI
- RUNS
- HITS_RUNS_RBIS
- SINGLES
- DOUBLES
- TRIPLES
- BATTER_BB
- BATTER_K
- STOLEN_BASES

## Pitcher markets
- PITCHER_K
- PITCHER_HITS_ALLOWED
- PITCHER_BB
- PITCHER_ER
- PITCHER_OUTS

## Separate contracts
- NRFI / YRFI remain under their frozen forward-shadow protocol.
- Binary YES/NO provider markets such as pitcher-to-record-a-win or first-home-run require a dedicated binary quote parser and are not coerced into OVER/UNDER semantics.
- F5 and inning-specific game markets require separate period-aware models/validation and are not silently treated as full-game markets.

This catalog is an acquisition contract only. Missing model/deployment support must fail closed rather than dropping the quote silently or relabeling a shadow probability as production.
