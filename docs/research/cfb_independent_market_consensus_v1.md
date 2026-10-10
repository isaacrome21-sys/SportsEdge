# CFB independent multi-book pricing overlay (research only)

This is **not** a copied OddsJam algorithm or a proven predictive betting model.
It is an independent, equally weighted, two-or-more-book **same-contract**
no-vig comparison of externally supplied offers against a manually supplied
DraftKings price. No sharp-book weights have been trained or verified.

## Running it

```bash
python scripts/research_cfb_independent_consensus.py \
  --card artifacts/run_it/cfb_sdv_card.json \
  --reference-books /path/to/independent_books.json \
  --output artifacts/run_it/cfb_sdv_independent_consensus.json
python -m unittest tests.test_cfb_independent_consensus -v
```

`cfb-sdv-card.yml` also accepts a **separate optional**
`reference_books_json` dispatch input. It runs the comparison after making
the original CFB side/total card, without changing or relabeling that card.

Example **synthetic data (never use as live betting prices)**:
```json
{
  "books": [
    {"book":"Pinnacle","captured_at_utc":"2026-10-10T01:59:00Z",
     "quotes":[
       {"game_id":"g1","market":"SPREAD","side":"HOME","line":-3.5,"american_odds":-110},
       {"game_id":"g1","market":"SPREAD","side":"AWAY","line":3.5,"american_odds":-110}
     ]},
    {"book":"Circa","captured_at_utc":"2026-10-10T01:59:00Z",
     "quotes":[
       {"game_id":"g1","market":"SPREAD","side":"HOME","line":-3.5,"american_odds":-110},
       {"game_id":"g1","market":"SPREAD","side":"AWAY","line":3.5,"american_odds":-110}
     ]}
  ]
}
```

Important:
- IDs and sides/handicaps must match the **target CFB card exactly**.
- Supply two genuinely independent books. DraftKings (or alias) may not be
  counted as its own pricing reference.
- Each book requires two opposing prices on the **same exact contract**.
  One-sided quotes and drifting handicaps are excluded.
- Capture time must be UTC with an offset, **within 15 minutes before the
  card scored timestamp**. Later market prices cannot justify earlier edges.
- No timestamp can certify an independently verified sportsbook receipt if
  someone manually typed it. Refresh and verify offers before any wager.
- Reference probabilities are **equal weighted**, not empirically calibrated.
  Books disagreeing by more than 12 percentage points cannot pass.
- Whole-integer spread/total lines are marked `WHOLE_POINT_PUSH_PROBABILITY_UNMODELED` instead of reporting misleading per-unit ROI without separately calibrated push mass.
- Research status `SHADOW_PRICE_DISLOCATION` requires +2 percentage points
  of offered-price break-even probability, positive indicative payout EV,
  available same-contract multi-book comparison, pregame timestamp, a
  straight-wager price no worse than -165, and no Illinois college team.
- The model score/probability, original `results`, betting statuses and
  validated-market list are never changed.
- No `BET`, `OFFICIAL`, staking, promotion, positive-EV proof, historical
  backfill or automated wagers. Previously failed CFB held-out calibration
  remains a separate blocker.

For actual wagering authority, historical leakage-resistant out-of-sample
performance, executable quote receipts, unbiased forward CLV and net return
evidence are still required. A multi-book discrepancy is only a candidate.

## Saturday October 10, 2026 provisional board

`config/cfb_saturday_2026_10_10_board.json` contains 14 **pregame**
pair-matched spreads and totals manually transcribed on October 9 from the
public DraftKings Network [CFB betting-splits pages](https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/).
They are **not** independently book-receipted, nor guaranteed to match an
Illinois account at execution. Only use as a working research board.
User-supplied, freshly verified local DraftKings screenshots should supersede
these preliminary prices before treating any quoted line as actionable.

The merged `cfb-sdv-card` main-push runner chooses this new board instead of
replaying archived Friday quotes, preserving the original Friday artifact.
It still applies the ordinary pre-kickoff, model-source, calibration,
large-edge suspicion and no-authority checks. No Illinois college teams are
included. When the model is unavailable, the card is market-only without
invented model edges.
