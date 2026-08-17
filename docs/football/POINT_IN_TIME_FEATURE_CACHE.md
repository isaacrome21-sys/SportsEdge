# NFL point-in-time feature cache contract

This lane exists to prevent the historical M2 feature cache from becoming a second market-data cache or from leaking future information.

For every game/team row, the selected feature snapshot must satisfy `feature_asof_ts < game_start_ts`. The join uses the latest snapshot meeting that condition. A snapshot exactly at kickoff is not eligible.

The cache rejects market-derived and result-derived fields, including spread/total/moneyline/odds/price/closing/consensus-line aliases and outcome/result/score fields. The cache is therefore suitable as an upstream M2 feature source, but it does not by itself prove predictive superiority.

Every materialized cache should be accompanied by a manifest containing the source name, source SHA-256, deterministic cache SHA-256, row count, and season coverage. Reordering rows must not change the cache hash.

Promotion remains separate: a point-in-time cache may be technically valid while NFL M2 still fails to beat M1 in walk-forward validation.
