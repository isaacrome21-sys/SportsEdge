# PREREGISTRATION — NFL player yardage/reception props: calibration screen (Part 1)

**Status: written and hash-locked BEFORE any score of this construction exists on any data.**
Written Sat 2026-10-17 (CT) by Claude on Isaac's instruction ("back test every model and prop").
Label of any output: RESEARCH_EVIDENCE, calibration only. No historical DraftKings prop prices
exist in free data, so this CANNOT show market edge; it only decides whether a prop model is
realistic enough to be worth forward price testing (Part 2: captured DK two-sided prices,
scored prospectively). No card, PLAY or promotion follows from this file.

## 1. Data
nflverse weekly player stats, regular season only (season_type REG):
`player_stats_{2018..2024}.csv.gz` and `stats_player_week_2025.csv.gz`, release assets of
github.com/nflverse/nflverse-data, SHA-256 recorded in SPEC_HASHES.txt next to this file.
Fields: player_id, position, season, week, attempts, passing_yards, carries, rushing_yards,
targets, receptions, receiving_yards. A player-week appears only if the player recorded a stat;
inactive players are absent (props on inactive players void), so absent weeks are not scored.

## 2. Markets and role filter (point-in-time)
| Market | Stat | Role filter on prior same-season games |
|---|---|---|
| PASS_YDS | passing_yards | position QB, mean attempts ≥ 20 over ≥ 3 prior games |
| RUSH_YDS | rushing_yards | mean carries ≥ 8 over ≥ 3 prior games |
| REC_YDS | receiving_yards | mean targets ≥ 4 over ≥ 3 prior games |
| RECEPTIONS | receptions | mean targets ≥ 4 over ≥ 3 prior games |
"Prior" = strictly earlier weeks of the same season. Everything is computed from strictly earlier weeks.

## 3. Arms (identical player-weeks)
- **CANDIDATE**: mean μ = (Σ prior same-season values + K·G) / (n + K), K = 3, where G is the
  mean of the stat over all role-qualified player-weeks of that market in strictly earlier weeks
  of the same season (week 1–3 fall back to the previous season's full-season role mean).
  Distribution: Gamma with mean μ and coefficient of variation c_m, where c_m is the pooled
  coefficient of variation of (outcome / μ) over role-qualified player-weeks of **2018–2019 only**
  (training seasons, never scored). RECEPTIONS uses a Poisson–Gamma (negative binomial) with
  the same mean and variance. Zero outcomes are allowed (Gamma CDF evaluated at the outcome).
- **B1 (player history)**: empirical distribution of the player's prior same-season values.
- **B2 (league role)**: empirical distribution of all role-qualified outcomes of that market
  in strictly earlier weeks of the same season (previous season for weeks ≤ 3).

## 4. Split, metric, gate
- Scored seasons **2020–2025**, weeks 4+ (needs ≥ 3 prior games). 2018–2019 training only.
- Metric: CRPS on integer yards / receptions, paired per player-week.
- 95% CI: block bootstrap over (season, week) blocks, 2,000 resamples, seed 20261017.
- **CALIBRATED_CANDIDATE** per market iff ΔCRPS (CANDIDATE − B1) CI < 0 **and**
  ΔCRPS (CANDIDATE − B2) CI < 0. Otherwise **NOT_FORWARD_ELIGIBLE**.
- Descriptive: PIT histogram (10 bins) and P(over) calibration at each player's own prior
  median rounded to x.5 (a line proxy only, not a market price).

## 5. What a pass means
Only eligibility for Part 2 (forward test against captured DK two-sided prop prices, de-vigged,
scored after a preregistered sample). Not a PLAY, not an edge, not a promotion.

## 6. Verification
Determinism (byte-identical reruns), hand check of ≥ 10 player-weeks by code that does not
import the evaluator, independent verifier from a fresh checkout.
