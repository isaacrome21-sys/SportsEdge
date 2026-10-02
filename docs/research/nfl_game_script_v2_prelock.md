# NFL game-script V2 pre-lock

V1 failed before validation because its exact-tie bucket had only 18 team-games
against the predeclared minimum of 100. That failure is not repaired in place.

V2 uses a **new development window (2011–2015)** and never reuses the exposed
2016–2024 V1 fit window for fitting or model selection. The clean 2025 season
remains the one-look research validation because V1 never accessed it.

The V2 model removes sparse buckets entirely. It fits two ridge regressions,
one for relative pass workload and one for relative rush workload, on a fixed
piecewise-linear basis of final team margin with knots at -14, -7, 0, 7, and
14. Ridge alpha is selected only by leave-one-season-out CV inside 2011–2015.

No monotonic direction is imposed, no fitted values are clipped, and sportsbook
fields are forbidden. If the fitted curve leaves the frozen downstream range
[0.4, 1.8], the candidate fails closed.

The 2025 validation still compares the scripted workload forecast to the
unscripted 1.0 multiplier baseline using strictly-prior eight-game team
workloads. A pass requires at least 1% improvement in the equal-weight mean of
pass/rush MAE, neither component MAE may worsen, and mean error for pass and
rush must each remain within 1.5 plays.

This pre-lock performs no fit and does not read 2025. It changes no production
engine and creates no Model_P, Truth Gate, OFFICIAL, promotion, or staking
authority.
