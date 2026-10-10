# Unsupported CFB spread tracker, research only (2026-10-10)

Opening contracts are frozen by GitHub Issue #1957 and the original ledger JSON.
All opening quotes were user-provided DraftKings screenshot values from 04:54 CT,
not independently verified executable quotes. The 0.25u stakes are tracking
stakes and do not prove any wagers were placed. This record is separate from
CFB probation and does not affect promotion or betting authority.

Add real closing observations to 2026-10-10-closes.json (observations array).
Required keys: id, pick_team_canonical, handicap, price_american, book
(DraftKings), observed_at_utc, source_ref, verified (true/false).
A valid close is captured before kickoff and within 60 minutes of start;
a stale or post-kickoff quote is rejected. Different close line means only
line CLV is displayed; same-line price-implied probability CLV is also
computed when the threshold matches. Neither is a certified sharp no-vig CLV.

Add verified results to 2026-10-10-results.json (results array). Each result
has id, status FINAL, away_points, home_points, observed_at_utc after kickoff,
and source_ref. Missing closes/scores remain PENDING. Never copy hypothetical
examples into actual observations. Original handicap and price are immutable.

Run:
python -m unittest tests.test_grade_cfb_unsupported_spreads tests.test_cfb_spread_anchor_test_harness -v
python scripts/grade_cfb_unsupported_spreads.py --ledger ledger/cfb_unsupported_spreads/2026-10-10-opening.json --closes ledger/cfb_unsupported_spreads/2026-10-10-closes.json --results ledger/cfb_unsupported_spreads/2026-10-10-results.json --output artifacts/cfb/2026-10-10-unsupported-spread-report.json

# Grok: reuse the exact #1954 anchor test
scripts/cfb_spread_anchor_test_harness.py contains exact unmodified core
functions assemble, basic_ols, ols, errors, clustered_slope_ci, evaluate
from #1954 source blob 0d9df734b0043d56c863482c9c37bb7c8b4b9681. Call evaluate(assemble(predictions,
cached_historical_lines),start=2021); then passes_feature_acceptance(report).
Required acceptance: positive held-out incremental weight with CR1 season
clustered 95% CI lower bound ABOVE zero and pooled 2021-2025 heldout anchor
RMSE STRICTLY below historical closing-spread proxy RMSE. Historical closes
are reconstructed and cannot substantiate executable wager EV.

IMPORTANT: The pure anchor calculation does NOT check whether a supplied
model_margin prediction was actually trained before the game. Grok MUST
enforce and evidence features' availability timestamps, prior-season-only
fit, point-in-time joins, missingness, and no leaked future values upstream.
Freeze prereg in config/cfb_spread_features_prereg_v1.json before first
attempt: train 2016-2020, chronological holdout 2021-2025, max 10 total
attempts. Log all attempts, hashes, missingness, 5 folds, slope, CI,
RMSE vs close. Do not merge or enable spread bets.
