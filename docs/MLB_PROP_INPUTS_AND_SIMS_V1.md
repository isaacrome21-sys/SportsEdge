# MLB Prop Inputs + 10K Sim Contract v1

## What public research supports
Public posts from DFSnDonuts/MySpariEdge show a workflow built from several distinct layers rather than one trend metric:

- pitcher attack profiles using HardHit%, Barrel%, xwOBA, FIP/xFIP, walks, K-BB and WHIP
- pitching props using K skill, recent form, workload, pitch-count stability and opponent swing/miss
- NRFI/YRFI research using pitcher first-inning history plus opponent first-inning AVG/wOBA and first-inning runs per game
- hitter prop research using recent form/heat checks, then matchup, odds and line value
- published 10,000-simulation model outputs
- separate no-vig/+EV optimizers and market comparison

The public material does not reveal proprietary formulas, training data or exact feature weights. SportsEdge therefore uses only the disclosed feature categories and implements its own contracts/math.

## Freshness contract
Inputs have source-specific TTLs. Confirmed lineups and market prices expire quickly; weather is hourly; workload/bullpen state is same-day; Statcast and first-inning aggregates tolerate longer staleness. Missing and stale are separate failures.

## Required structural inputs
Pitcher props require K/BB/xBA/xwOBA, workload/pitch-count state, opponent K/whiff vs handedness and a confirmed lineup.

Hitter props require confirmed lineup/projected PA, contact/xwOBA, opposing pitcher contact-quality metrics, bullpen quality and park/weather context.

NRFI requires both starters' first-inning evidence, both offenses' first-inning quality/run rates, confirmed lineups and environment.

## Context-only inputs
Recent hit streaks, K ladders, hits-allowed streaks, BvP and last-7 bullpen ERA are candidate/research context. They cannot satisfy the structural input contract by themselves.

## 10K simulation
Default simulation count is 10,000. Count props simulate an uncertain event mean followed by Poisson outcome variance. Hitter 1+ hits simulate plate-appearance uncertainty and per-PA hit events. NRFI simulates each half-inning run count independently from projected first-inning means.

Simulation output is pricing/research evidence only. `promotion_evidence` remains false and V6 gates are unchanged.
