# MLB market implementation queue

The market catalog is intentionally broader than the currently deployed model set. Work is prioritized by reusable model structure and available official settlement data.

1. Game markets: MONEYLINE, RUN_LINE, TOTALS
2. Existing validated props: HITS, TOTAL_BASES, PITCHER_BB
3. Pitcher count props: PITCHER_K, PITCHER_OUTS, PITCHER_HITS_ALLOWED, PITCHER_ER
4. Batter counting props: RBI, RUNS, HOME_RUNS, HITS_RUNS_RBIS
5. Batter component props: SINGLES, DOUBLES, TRIPLES, BATTER_BB, BATTER_K, STOLEN_BASES
6. NRFI/YRFI: keep frozen forward protocol
7. F5/inning-specific markets: separate period-aware models and settlement contracts
8. Binary markets: dedicated YES/NO parser/model; never coerced into OVER/UNDER

For every market, the path to OFFICIAL is: quote acquisition -> canonical identity -> independent feature/model probability -> calibration/holdout evidence -> frozen edge floor -> deployment eligibility -> Truth Gate -> immutable prediction journal -> settlement/monitoring.
