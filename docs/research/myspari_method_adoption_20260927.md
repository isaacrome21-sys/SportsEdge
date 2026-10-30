# MySpariEdge method review and first adoption

Reviewed 2026-09-27 through the user's authorized browser session. Date is the
observation date, not a model-generation or market-quote timestamp.

## Sources actually inspected

- https://www.myspariedge.com/learn/how-our-models-work
- https://www.myspariedge.com/models/nfl/anytime-touchdowns (How it works;
  goal-line threshold expanded; current board)
- https://www.myspariedge.com/models/nfl/player-props (board and Hints)
- https://www.myspariedge.com/models/game-projections
- https://www.myspariedge.com/models/top-picks

This is a paraphrased method review, not a copy of their model or an exhaustive
review of all sports, videos, or site tools. No subscription data is installed as
SportsEdge training data. No claims of independent validation were verified.

## Documented distinctions and adoption decisions

| Observed method | SportsEdge decision |
| --- | --- |
| General guide describes official performance, recent form, role, matchup, venue/weather, quality/opportunity, market prices and confirmed participation | Use as an input-coverage checklist. Each new predictive feature needs PIT provenance and a held-out comparison; no invented coefficients. |
| General guide says projections freeze after lineups/inactives settle | Preserve separate draft/final snapshots; a site saying Pending is not confirmed participation. Do not overwrite the forecast used for grading. |
| General guide describes no-vig market edge; TD help defines raw book-implied edge instead | Label the two explicitly. Never infer no-vig probability from a single side. |
| TD profile combines chance and role checks but ignores price edge | Keep profile/role context separate from price-value ranking. A high profile must not qualify a negative-EV recommendation. |
| TD probability excludes passing TDs; 2+ is a different outcome | Match exact player, event, threshold, period and settlement contract before comparison. |
| TD goal-line tag uses at least 0.8 estimated carries/game inside opponent five | Document as a third-party descriptive threshold, not a fitted SportsEdge prior or probability. |
| Props Hints distinguishes projection, grade and projection-minus-line differential | A yards differential is not a probability edge. Do not convert their letter grades into fabricated percentages. |
| Props board exposes What-If workloads and Pending lineup status | Future scenario outputs must remain separate from frozen baseline forecasts and grading. |
| TD board identifies market-informed adjusted probabilities | Do not call agreement independent confirmation or blend without measuring dependence. |
| TD parlay display assumes independent legs, including teammates | Do not adopt that assumption. Retain shared-path/joint-distribution requirement. |

## Implemented in this branch

The existing research economics already compute fair American odds, conditional
win probability, raw price edge, and expected profit. The scored board discarded
some of them. It now preserves those fields and quote/start timestamps, and shows
fair odds, raw edge in percentage points, EV per unit, and timestamps on the card.

For push-capable markets, fair odds and raw edge use P(win | no push); EV includes
push mass. No-vig edge stays null without a paired market. Stale quotes retain
an audit timestamp but produce no score, price edge or EV. Existing positive-EV
selection and exact-contract deduplication remain in force.

This is a presentation/data-contract improvement. It does not improve or prove
predictive accuracy. The board schema is RUN_IT_SCORE_V2: Score comes only from
an explicit upstream qualification score. Market price, raw edge, EV and win
probability are excluded from Score by contract and covered by an invariance test.
Price/EV may break presentation ties between equal qualification scores but never
change the Score itself. Forecast sources and qualification scores remain
caller-attested and do not create promotion or official authority.

## Next predictive work, with evidence prerequisites

1. Audit official role inputs: inside-five carries, inside-ten targets, routes,
   snaps and team opportunity shares. Missing inputs stay missing. Compare to
   existing NFL role challenger before adding duplicate machinery.
2. Fit opportunity-to-outcome distributions on PIT training data; evaluate a
   frozen baseline/challenger pair on a later holdout. Report log score, Brier,
   calibration and sample sizes, not just winning examples.
3. Capture external benchmarks prospectively with publication, quote and capture
   times, exact contract and source identity. Evaluate independent and
   market-informed sources separately. No retrospective timestamp backfill.
4. Keep lineup updates/versioned projections and settlement corrections distinct.
   Final stats do not reconstruct first-settlement snapshots.

No production forecasts, priors, official gates, stake authority, DK confirmation
policy, or protected-main requirements are changed by this branch.

NOT Model_P / NOT Truth Gate / NOT OFFICIAL
