# Free Advanced Metrics & Usage-Trend Plan — All Sports Models

**Date:** 2026-10-25  
**Status:** Research note / wiring plan. No production path changed.  
**Research rule (same as NFL fantasy layer):** Compare a blend of projections + matchup context + usage/opportunity trend against each standalone signal and the paired market baseline. Do not assume the blend wins before chronological out-of-sample testing. On close research calls, name the deciding factor.

This applies the same idea discussed for the NFL/fantasy management layer to the rest of the SportsEdge models (MLB, NBA, CFB, NHL, etc.). Only free or free-tier public sources. Keeps frozen-artifact / Truth Gate discipline.

## Shared Decision Logic
- Add 1–2 new columns/features per sport: a free consensus (where available) and a usage/quality trend score.
- Research conflict-resolution candidate: blend + matchup + usage trend. Explicitly name the deciding factor on close calls, but do not override a frozen model or claim superiority until tested.
- Pull in the relevant morning/pre-slate job. Do not promote into official Model_P until harness-validated.

## MLB
**Free sources**
- MLB Stats API + Baseball Savant / Statcast (xwOBA, exit velocity, barrel %, hard-hit %, launch angle, pitch-level)
- Baseball-Reference (splits, park factors) — manual reference only; automated extraction/model training requires a permitted-use review
- Existing Statcast skill sources already in use for pitcher K, etc.

**Fields to add**
- Rolling Statcast quality (xwOBA / barrel rate, 14–28 day)
- Usage proxies (PA rate, contact-quality trend)
- Matchup (park factors, platoon, recent form)

**Notes**
Statcast quality is the strongest free tiebreaker for hitter props. Already partially aligned with existing pitcher-K Statcast work.

## NBA
**Free sources**
- Basketball-Reference (BPM, USG%, AST%, REB%, TS%, limited on/off) — manual reference only pending permitted-use review
- Dunks & Threes EPM (Premium-restricted, **not** a free automated feed; exclude from free ingestion unless a suitable license is obtained)
- NBA.com Stats (pace, four factors)
- Hashtag Basketball / free FantasyPros for DvP and consensus

**Fields to add**
- Usage rate / minutes-share trend
- Efficiency vs matchup (TS% or eFG% vs position defense)
- Pace + opponent DvP by position

**Notes**
Usage/minutes trend is the cleanest free signal for player props. See existing NBA feasibility notes.

## CFB
**Free sources**
- cfbfastR / sportsdataverse (EPA, WPA, success rate, explosiveness)
- CollegeFootballData.com (CFBD) advanced metrics and ratings (SP+, FPI where available to the configured tier; verify endpoint, quota and point-in-time coverage before scheduling)
- Existing SportsEdge CFB pipelines (already pull substantial free data)

**Fields to add**
- EPA / success-rate trend
- Opportunity/usage proxies (where available)
- Matchup (SP+/FPI differential, weather, altitude — partially covered)

**Notes**
EPA/success trend is the strongest free quality+volume signal. CFB research is paused but data sources are not discarded.

## NHL
**Free sources**
- Hockey-Reference (Corsi, Fenwick, basic advanced) — manual reference only pending permitted-use review
- NHL Stats API (TOI, PP/PK share, box scores)
- Public shot-quality proxies (Natural Stat Trick style where free)

**Fields to add**
- TOI / power-play share trend
- Shot-quality proxies
- Matchup (opponent defensive metrics, recent form)

**Notes**
TOI/PP-share is the clearest free usage signal. See NHL public baseline notes.

## Source eligibility and evidence discipline
- Publicly viewable is not equivalent to permission for bulk collection, automated model training or commercial reuse. Check each provider's current terms and plan before ingestion; mark unavailable/premium-restricted features **RESEARCH_NOT_ADMITTED**.
- Store source URL/version, actual capture time, event/player identity, usage license, and the earliest time the feature was knowable. Historical box scores or retrospective projections must not masquerade as decision-time information.
- Validate any proposed blend against standalone features and a contemporaneous bookmaker baseline using chronological out-of-sample splits. Neither a higher model score nor a free-source count establishes a betting edge.

## Wiring / Next Steps
1. Add the new fields as optional research inputs in the relevant sport modules (do not alter frozen official paths).
2. Update morning/job routines to pull the free sources once per slate.
3. Evaluate the shared blend/conflict hypothesis against single-source and market baselines; log the deciding factor on close calls, research only.
4. Harness-test before any promotion to Model_P / Truth Gate.
5. Prefer existing free clients (CFBD, MLB Stats API, etc.) over new scrapers.

No Odds API. No staking authority. Research only until evidence gates are met.

---
*Generated from the multi-sport free-metrics discussion. Ready for implementation in sport-specific pipelines.*
