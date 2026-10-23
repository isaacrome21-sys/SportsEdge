# NFL sides successor: test plan v0.1
Date: 2026-10-17 America/Chicago
Status: DRAFT_PROTOCOL; no evaluation executed; no promotion or hold removal.
Authority: #2384, #2385; production hold delivered by #2386.
Scope: full-game NFL regular-season moneyline and main spread only. Separate verdict per market. No G2, totals, props, alternate lines, CFB or receipt changes.

## Hypothesis and candidate fixed before scoring
Test a score-margin team-strength model, not the existing fixed 22-points-per-team engine. One candidate, no model bakeoff.
At each season start fit ridge least squares on the preceding three complete REG seasons (2018 is earliest input): home margin = home advantage * nonneutral + home team strength - away team strength. Team effects sum to zero; penalize team coefficients with lambda=20, leave home advantage unpenalized. Training rows have weight 0.5^(age_in_seasons), newest preceding season age=0. Neutral-site flag must be available pregame.
Refit only at season boundaries. No current-season scores enter forecasts. Franchise alias mapping is versioned; unknown identities refuse.
Predictive margin is fitted margin plus a discrete empirical residual drawn from training rows with the same recency weights; residuals are centered to weighted mean zero. Use leave-one-season-out fitted residuals within that three-season training window (each residual season predicted by a fit excluding it); no evaluation outcomes enter residuals. Round resulting margin samples to nearest integer using explicit half-away-from-zero rounding. Support is the weighted empirical support, with no renormalization to hide missing rows.
Compute home win, tie and away win mass, and spread win/push/loss at the observed threshold. Clip conditional probabilities to [1e-6,1-1e-6] only for scoring logs; record every clip. No market input in candidate training or forecast.

## Seasons, chronology, and exposure
2018-2020: initial training. 2021-2025: historical chronological screen, annual expanding availability but trailing-three-season fits. REG only; exclude preseason/postseason explicitly by game_type, not week number.
These historical seasons are NOT certified untouched project holdouts: #2372 records repeated NFL evaluations. Freeze this candidate before its first score, but label results HISTORICAL_SCREEN, never independent prospective validation.
Prospective validation: first full NFL REG week whose first kickoff occurs after immutable code/data-contract freeze and independent review, through end of 2027 REG. Register exact start week/date before acquisition; score once at end, without interim performance-based tuning/stopping. If the population is insufficient, verdict INSUFFICIENT; extension needs a new plan before outcomes. Do not reuse an existing sealed family holdout.
Historical fit and evaluation are pregame-reconstructable, not proof of contemporaneous ingestion. Prospective features and predictions must have genuine receipts before kickoff.

## Data admission and freeze
Primary proposed source: nflverse/nfldata games.csv, immutable commit and SHA-256 recorded before scoring. Source documentation: https://nflreadr.nflverse.com/reference/load_schedules.html and https://nflreadr.nflverse.com/articles/dictionary_schedules.html .
Audit source coverage for each season and each market; do not assume every game has paired odds. Verify bookmaker/aggregation identity, final pre-kickoff closing semantics, moneyline tie settlement and spread-odds/line pairing from source provenance. Missing proof => SOURCE_UNVERIFIED for that market, not a fabricated close or assumed -110.
Retain game ID, season, kickoff UTC, teams, neutral flag, scores, both ML odds, spread line and both spread prices. Separate outcome columns from forecast loader. Enforce unique fixture/market/line; reject inconsistent scores, invalid odds, missing pairs, duplicate/conflicting IDs and unsupported settlement. Publish all exclusion counts before results; no outcome-based exclusions.
Freeze input manifest, source commit, alias map, evaluator and predictor commits, dependency versions, configuration, seed and protocol hash before evaluation. No replacement of frozen bytes, retrospective receipt creation or changes to main/data.

## Benchmark, settlement and matching
For American odds a, implied q = -a/(-a+100) when a<0, otherwise 100/(a+100). For each genuine paired market p_home = q_home/(q_home+q_away); p_away = 1-p_home. Proportional de-vig is the single primary method.
Moneyline comparison is conditional on non-tie for two-way tie-void contracts; ties return stake and are reported separately. If source settlement cannot be established, refuse ML verdict.
Spread sign must be verified against documentation and hand-labeled fixtures: if spread_line denotes points home is favored, home covers when home_score-away_score > spread_line. Equal is push. Candidate comparison uses P(win)/(1-P(push)); market paired de-vig is conditional on non-push. Report unconditional candidate push/tie mass separately.
Use one home-oriented observation per fixture per market for proper scoring; never count complementary sides twice. Compare candidate and closing market on identical admitted games.
A closing-price simulation is a closing-time strategy only. It does not establish performance at 10:17 AM; earlier-card deployment needs predictions and actual executable quotes from that decision time.

## Locked screen and validation rules
Primary loss: mean paired log loss difference (candidate minus de-vigged market), on resolved observations. Secondary: paired Brier difference; per-season and market-implied probability decile calibration, dog/favorite bias, counts and exclusions.
Uncertainty: 20,000 bootstrap resamples of season-week clusters, same resample for candidate/benchmark; numpy PCG64 seed 2386. Two market hypotheses: one-sided 97.5% upper confidence limit for primary loss difference must be <0 for each passing market (Bonferroni family alpha .05). Brier difference must also be <0 in point estimate. At least 500 resolved fixtures and 90% paired-quote coverage of eligible completed fixtures per market; otherwise INSUFFICIENT. Missing source provenance yields SOURCE_UNVERIFIED regardless of scores.
Economic strategy fixed before scoring: flat one-unit stake, decimal-price EV = P(win)*(decimal-1)-P(loss); minimum EV .03, American odds >= -165. At most one selection per game across ML/spread: highest EV, tie resolved ML then home. No parlays, Kelly or optimization. Push/tie-void profit zero; report all stakes including pushes. Require >=200 independent selected games, ROI >=.02 and one-sided 95% week-cluster bootstrap lower bound >0 to pass economic screen. No minimum count => INSUFFICIENT, no threshold relaxation.
An individual market can pass probability screening while economic screen fails; report both. No claim that failure proves absence of all possible edge.
Historical pass earns eligibility for prospective verification. Promotion additionally requires the prospective criteria, independent reproduction, source/decision-time fidelity, calibrated production adapter tests, exact-head green CI, and the applicable owner ruling. Do not rewrite existing governance automatically.

## Verification before results
Meaningful tests: modify future outcomes and prove earlier forecasts unchanged; change held-out outcomes and prove frozen forecasts unchanged; known odds/de-vig examples; home/away sign swaps; neutral sites; integer spread pushes and tied ML; same-game clustering/deduplication; missing paired prices; source/hash mismatch; deterministic replay; hold remains active.
Independent verifier reproduces fixture predictions and aggregate scores from frozen bytes before any promotion request. Do not self-certify independence.

## Deliverables and next actions
1. Confirm source closing/settlement provenance and historical exposure ledger.
2. Implement isolated predictor/evaluator and synthetic chronology tests; no scoring yet.
3. Replace this draft status with exact immutable manifest/code identities after independent protocol review.
4. Run the historical screen once and publish full outcomes including failures.
5. Register prospective start before first receipt. No promises of a passing result or next-week PLAY.
No paid odds pull, workflow installation, holdout access or production switch is authorized by this document alone.
