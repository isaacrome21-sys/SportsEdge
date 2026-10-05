# MLB F5 + NRFI/YRFI tightening pre-registration (v2, 2026-10-04)

Tracking: #1482 follow-on after the announced-lineup K production wiring. This
protocol is committed before any result is viewed. The research run changes no
production probability and grants no promotion, OFFICIAL, or staking authority.

## Problem

F5 already uses actual strictly-prior first-five scores, but its last-30 team
marginals are unsmoothed. Unseen F5 score states can receive exactly zero mass.

NRFI/YRFI now uses actual strictly-prior inning-one offense and opponent-allow
history with Jeffreys Beta(1/2, 1/2) stabilization. That current production lane
prevents 0%/100% short-sample probabilities, but it does not borrow broader
strictly-prior league information when a team's recent 30-game history is thin.

## Data and PIT rules

Use MLB StatsAPI regular-season schedule data for 2023-2025 hydrated with
linescores. Only final games with complete innings 1-5 are eligible.

For each target game, all features use official dates strictly before the target
date. Same-day games are excluded. Team histories use the last 30 games in a
370-day lookback, minimum 10. League priors use all strictly-prior team-half
outcomes in the same 370-day lookback.

2023 is history only. 2024 is tuning. 2025 is the untouched held-out test.
Sportsbook prices, closing lines, capper opinions, and target outcomes never
enter model inputs.

## F5 candidates

m0 reproduces the current F5 state: each scoring marginal is a 50/50 blend of
that team's empirical F5 runs-for PMF and the opponent's empirical F5
runs-allowed PMF, then the two team marginals form one independent joint score
state.

m5, m15, and m30 use the same construction after shrinking each team marginal
toward the strictly-prior league F5-runs PMF with 5, 15, or 30 pseudo-games.

Select on 2024 by lowest mean negative log probability of the exact F5 score;
ties favor m0 and then the smaller prior.

F5 ships only if all 2025 rules pass:
1. selected candidate is not m0;
2. date-clustered 95% bootstrap CI of delta exact-score NLL versus m0 is below 0
   (2,000 reps, seed 20261004);
3. W/T/L state Brier is no worse than m0 + 0.002;
4. F5 over-4.5 Brier is no worse than m0 + 0.002;
5. at least 1,000 held-out games are scored.

## NRFI/YRFI candidates

production_empirical_jeffreys reproduces the current #1571 path exactly: for
each offense and opponent-allow component, the scoreless probability is the
Jeffreys Beta(1/2, 1/2) posterior mean from the recent strictly-prior inning-one
binary outcomes; the two components are averaged 50/50 for each half inning,
and NRFI is the product of the two half-inning zero probabilities.

Challengers retain that Jeffreys 1.0 effective observation and add 5, 15, or 30
pseudo-games from the strictly-prior league inning-one scoreless rate. Candidates
are direct_m5, direct_m15, and direct_m30. There is no obsolete full-game/NB
baseline in this study.

Select on 2024 by lowest binary log loss; ties favor
production_empirical_jeffreys and then the smaller league prior.

NRFI/YRFI ships only if all 2025 rules pass:
1. selected candidate is not production_empirical_jeffreys;
2. date-clustered 95% bootstrap CI of delta log loss is below 0;
3. Brier is no worse than production;
4. 10-bin ECE is no worse than production + 0.005;
5. at least 1,000 held-out games are scored.

Any passing lane requires a separate production PR with PIT, complement,
probability-mass, and research/production parity tests. A failed lane remains
unchanged and is not retuned on 2025.

## Run

Open an owner [MLB LINES] issue whose fenced body starts with:

RESEARCH f5_nrfi_tightening

The issue workflow runs scripts/research_mlb_f5_nrfi_tightening.py and posts the
report. No betting card is produced.
