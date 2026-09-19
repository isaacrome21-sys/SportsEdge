# Public repo adoption

SportsEdge does not copy other people's fitted betting models.

What those repos do better than most hobby ATS bots, and what we take:

1. nflfastR / cfbfastR
   - Own EPA/CPOE from play-by-play.
   - Hash-bound artifacts and model cards.
   - Leave-one-season-out checks.
   Take the method. Do not ingest their booster files into Model_P.

2. Statcast / pybaseball pipelines
   - Barrel, exit velocity, platoon, rolling 10/35/75 windows.
   Take as MLB feature candidates after the daily Statcast clock is live.

3. CFB talent / returning production files
   - Pregame, timestampable, not a sportsbook line.
   Feature candidates only.

What we refuse:
- Training on spreads or totals.
- Using SP+/FPI/consensus as Model_P.
- Kitchen-sink 100-feature team models with no CLV proof.
- Any public repo that reports ATS% without a closing-line beat.

Promotion still requires the frozen Truth Gate.
