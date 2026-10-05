# MLB backlog E: can pitcher props leave the LEAN tier? — pre-registration (v3, 2026-10-05)

Tracking: #1482 (backlog item E). Written and committed **before** any graded result was\nseen: no outcome has been joined to any archived quote, and no model price has been\ncomputed for any archived quote. **v3 was amended before the one allowed final look** after a code audit found that replaying current-game lineup/umpire context from the postgame StatsAPI would leak information. No archived outcome, model-vs-market score, or ROI was inspected. The amendment binds those optional current-game context fields to immutable `data`-branch snapshots captured at decision time. **v2 was amended before any outcome/price join** solely because PR #1542 landed the validated announced-lineup K production adjustment after v1 was written. No archived result was inspected between v1 and v2. The runner will print the SHA-256 of this file so the result comment is bound to this exact protocol.

## Question
Pitcher props (PITCHER_K, PITCHER_BB, PITCHER_ER, PITCHER_HITS_ALLOWED) are capped at LEAN
on the card. The context lanes (#1509, #1523, #1528) showed the model got *better* than
its own baseline. They did not show it is better than the *market*. A row should only be
ACTIONABLE if its EV is real, which needs evidence that the model's probability beats
the price it is compared with. This study asks, per market: does production model_p beat
the de-vigged DraftKings pregame price on real 2026 outcomes, and did the ≥2% EV rows
make money at the quoted price?

## Data (fixed now)
- **Quotes:** the `data` branch archive `runtime/mlb-prop-pit/<date>/props_*.json`
  (`archive_type = MLB_PROP_PIT_QUOTES`, provider `DRAFTKINGS_WEB_RESEARCH`,
  book `draftkings_direct`), first snapshot 2026-09-14. Only quotes with
  `pit_eligible = true`, `is_alternate = false`, and `market` in the four markets above.
- **Archive cutoff:** every snapshot whose game's `first_pitch_at` is on or before the
  last game of the 2026 postseason. The study runs **once**, after the World Series ends,
  as part of 2027 prep. There is no interim look; nothing in this file may be evaluated
  on a partial archive.
- **Outcomes:** MLB StatsAPI boxscore for the matched `gamePk` (the pitcher's strikeOuts,
  baseOnBalls, earnedRuns, hits), regular season and postseason.
- **Model inputs:** StatsAPI pitching and team game logs and schedule `officials`,
  strictly before the game date, exactly as production builds them.

## Units
One unit = (provider event, pitcher, market). Built as follows, in order:
1. Take the **last** archive snapshot captured strictly before `first_pitch_at` in which
   the unit has **both** OVER and UNDER quotes at the **same half-integer line**. Units
   with only integer lines, or never two-sided, are dropped (counted).
2. **Identity:** match the event to a StatsAPI `gamePk` by date (US/Eastern of
   `first_pitch_at`) and the two team names in the event snapshot; match the pitcher by
   normalized full name to that game's **starting** pitchers. Zero or several matches →
   dropped (counted). Doubleheaders are matched by start time within 3 hours.
3. **Void:** if the matched pitcher did not start the game, or the game was not
   completed, the unit is dropped (counted). These would be voided by the book.
4. **Production parity:** compute model_p with the production pricing path for that
   date: own last ≤10 starts in seasons Y-1 and Y strictly before the game date; k ≥ 5
   path with the shipped lanes (K: opp-K beta = 1 plus the announced-lineup K layer
   validated in #1540 when the lineup is posted, W = 200 and gamma = 0.5; if that lineup
   input is unavailable, production retains the opp-K price; BB: umpire W = 6000,
   beta = 2, using the game's actual plate umpire; ER and HITS_ALLOWED: own history).
   k = 1..4 has no validated path for these four promotion markets, so those units are
   BLOCKED and dropped (counted). The runner must use the same production feature builder
   and `pitcher_joint_engine` pricing path and must include parity tests against the frozen
   research implementations for every shipped adjustment it exercises.
   History is regular-season only (`gameType=R`), as in production today, so a
   postseason unit is priced from regular-season starts.
5. **Decision-time context proof (v3 amendment, frozen before the final look):** for
   PITCHER_K and PITCHER_BB, current-game lineup/plate-umpire state may not be fetched
   retrospectively from the finished-game StatsAPI. The runner must use the immutable
   `data:runtime/mlb-context/runs/**/game_<gamePk>.json` archive and select the latest
   snapshot with `retrieved_at <= quote observed_at` and age <= **20 minutes**. If the
   snapshot says PRESENT, use the exact archived batting order or umpire assignment. If
   it says ABSENT, use the same production fallback that was available then (K retains
   opp-K without lineup-K; BB retains own-history pricing without umpire-BB). If no fresh
   snapshot exists, or a PRESENT snapshot is structurally incomplete, drop the unit and
   count it as PIT context unproven. Prior-game boxscores/officials remain valid inputs
   because those games were completed before the target date. No future context snapshot
   may be used to infer what was known at the quote time.

## Prices
- Market fair probability: two-way multiplicative de-vig of the two quotes,
  `q_over = (1/d_over) / (1/d_over + 1/d_under)`, with `d` the decimal odds.
- Model: production `model_p` for OVER, and `1 − model_p(OVER)` for UNDER (half lines,
  no push).
- **Flagged bet:** a side with `EV = model_p · d − 1 ≥ 0.02` at its quoted price, after
  the production thin-tail guard (model_p ≤ 0.10 or ≥ 0.90 is withheld). At most one side
  per unit can be flagged; if both pass, the larger EV is taken.

## Metrics (per market)
- Primary: `ΔLL = mean log loss(model) − mean log loss(market fair)` for the OVER outcome.
- Bets: count of flagged bets, flat 1-unit ROI at the quoted price, win rate.
- Information only: Brier difference, 10-bin reliability of model vs outcome, the mean
  `model_p − q_over` gap, ROI by EV bucket (2–5%, 5–10%, ≥10%), and every drop count
  above.
- Uncertainty: pitcher-clustered bootstrap, 2,000 reps, seed 20261005. Four markets are
  tested, so intervals are **98.75%** (Bonferroni 0.05 / 4).

## Promotion rule (per market, all must hold)
1. At least 150 graded units and at least 40 flagged bets.
2. The 98.75% CI of ΔLL lies entirely below 0 (model beats the de-vigged price).
3. The 98.75% CI of flagged-bet ROI lies entirely above 0.

A market that passes may be allowed ACTIONABLE in a separate PR (same EV floor, same
thin-tail guard, same same-game guard). A market that fails stays LEAN max, and the
result is recorded on #1482 as the reason. Markets are decided independently.

**Expected outcome, stated in advance:** player-prop markets are usually close to
efficient, and the samples are small (roughly 350 regular-season units per market before
drops). Most likely no market passes, and pitcher props stay LEAN. That is an acceptable
result; this study exists so the tier is set by evidence, not by default.

## What this study does not do
- It does not change model_p and does not tune anything: every model parameter is the
  one already shipped as of the preregistration freeze, including the #1540 lineup-K
  layer now wired by #1542. If any covered production pricing code changes again before
  the one allowed final look, this protocol must be re-frozen before that look. No
  market-anchored blend is tested here (that would need its own pre-registration and a
  tune/test split).
- PITCHER_OUTS, PITCHER_HITS_WALKS_ER and EITHER_PITCHER markets are out of scope
  (the archive has almost no two-sided quotes for them).
- Batter props are out of scope.

## How it runs
After this protocol and its runner are merged, open an `[MLB LINES]` issue whose fenced
body is `RESEARCH pitcher_prop_promotion` after the World Series ends. The runner reads
the archive from the `data` branch, pulls outcomes and history from StatsAPI in Actions,
and posts the report on that issue.
