# PREREGISTRATION — NFL sides (moneyline + spread): Elo candidate vs the closing market

**Status: written and hash-locked BEFORE any score of this construction exists on any data.**
Written Sat 2026-10-17 (CT) by Claude after Isaac's ruling #2385 (NFL sides held, #2384).
Label of any output: RESEARCH_EVIDENCE. Not a promotion input by itself; lifting the
#2384 hold is a separate ruling by Isaac.

## 0. Why
The current side engine (22 pts/team prior + bounded form) compresses probabilities toward
0.5: the Oct 17 composite run surfaced 20/20 underdogs as "edges" (#2383/#2384). This tests
ONE replacement: a standard, publicly specified Elo rating. Every constant below is fixed
here from the published FiveThirtyEight NFL Elo method; none is tuned on any data.

## 1. Data
nflverse/nfldata `games.csv`, SHA-256 `a484c6ae884d03b11ab14f9fb3ed9ee8ca7168f3a22550e74f566532c4c6b284`
(the corpus already pinned for #2372). Fields used: season, game_type, gameday, gametime,
home/away team, home/away score, location, away_moneyline, home_moneyline, spread_line,
away_spread_odds, home_spread_odds. The lines are nflverse consensus CLOSING lines, not
DraftKings quotes, and carry no capture timestamps: this is a retrospective comparison to
the closing market, not point-in-time execution evidence.

## 2. Candidate (all constants fixed)
- Elo start 1505 for every team in 2015 week 1 (2015 = warm-up, never scored).
- Between seasons: regress 1/3 toward 1505.
- Home field +48 Elo, set to 0 when `location == "Neutral"`.
- Update after each game in kickoff order (games with identical kickoff are rated from the
  same pre-kickoff state, then updated together): K = 20; MOV multiplier
  ln(|margin|+1) * 2.2 / (0.001 * elo_diff_winner + 2.2); ties use multiplier 1 and result 0.5.
- Pregame: d = elo_home + HFA - elo_away. P(home win) = 1/(1+10^(-d/400)).
  Predicted home margin = d/25. P(home covers spread_line) = Phi((d/25 - spread_line)/13.5),
  where nflverse `spread_line` is the home team's expected margin (positive = home favored);
  a push-exact line (integer) uses the same continuous form (push mass is not modeled).
- Ties in the result: excluded from moneyline scoring; spread pushes excluded from cover scoring.

## 3. Arms (identical rows)
- CANDIDATE: §2.
- MARKET: de-vigged closing prices, proportional (multiplicative) normalization of the two
  implied probabilities, separately for moneyline and spread.
- NAIVE: home win 0.57, home cover 0.50 (fixed, descriptive only).

## 4. Split and metrics
- Scored seasons 2018–2025 regular + postseason with both closing prices present.
  2015–2017 are rating warm-up only.
- Metric per market: log loss of the home-side event, paired per game, CANDIDATE − MARKET.
- 95% CI: block bootstrap over (season, week) blocks, 2,000 resamples, seed 20261017.

## 5. Gate (per market; moneyline and spread verdicted separately)
- BEATS_CLOSE iff the paired ΔLogLoss CI (CANDIDATE − MARKET) is entirely < 0.
- Otherwise DOES_NOT_BEAT_CLOSE. Expected outcome stated in advance: closing NFL markets are
  efficient and a public Elo is not expected to beat them; a fail keeps #2384's hold.
- Descriptive (no gate): calibration by candidate-probability decile; flat-stake ROI at the
  closing price on rows where candidate edge vs MARKET > 3 pp, with bootstrap CI; underdog
  share of those rows (the #2384 failure signature).

## 6. Forward leg
If and only if a market passes §5, the same frozen code scores 2026 games from
2026-10-18 onward against DraftKings two-sided prices captured pregame under the 180 s rule,
after season end, before any PLAY consideration.

## 7. Verification
Determinism (two runs byte-identical), a hand check of ≥10 games' Elo and probabilities by
code that does not import the evaluator, and an independent verifier from a fresh checkout.
