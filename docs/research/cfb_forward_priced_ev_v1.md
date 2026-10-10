# CFB priced forward shadow: evidence before real positive-EV wagers

**No bets, no promotion, no guaranteed EV, no retroactive price reconstruction.**

## Problem fixed
CFB forward snapshots archived pregame model scores but not the two-sided
sportsbook quotes that the original card showed. Later P/L analyses without
the originally offered odds would require historical price backfill.

This change saves exact paired moneyline/spread/total card prices, model
probabilities and original card statuses within the same pregame source-hashed
forward snapshot. The existing score/source/kickoff chronology is preserved.
The original phone-board source DOES NOT independently attest a DraftKings
screenshot capture time, sportsbook origin or freshness. The quote proof
is explicitly CARD_ROWS_ONLY_NOT_INDEPENDENT_SPORTSBOOK_RECEIPT;
a hash of our card is not independent proof of a sportsbook offer.

## Research EV and settlement
- Proportional no-vig probability from the exact paired opposite odds.
- Normal score-distribution winning, losing and pushing probabilities,
  with integer-line continuity corrections for pushes. This model remains
  **uncalibrated and research-only**.
- Expected return per 1u risk = P(win)*profit_per_unit - P(loss). Pushes = 0.
- Conditional win P(win)/(P(win)+P(loss)) compared to no-vig fair price.
- Research candidates: conditional advantage >=2pp and <=12pp, payout EV >0,
  -165-or-better straight odds, never Illinois college teams.
- Deterministic one outcome market (ML or spread) and one total per game,
  selected BEFORE outcomes, based on highest theoretical unit return.
- Optional FINAL outcomes observed after kickoff, with timestamp and SHA,
  may grade hypothetical W/L/P and returns. No proof of independent odds.
- All rows remain SHADOW_RESEARCH_ONLY_NO_WAGER and output has
  bets_enabled=false, real_positive_ev_proven=false, staking_authority=false.

The prospective GitHub collector now saves the research priced shadow with
the original score snapshot before settlement, without modifying real cards.
On a market-only result it emits a safe zero-candidate artifact.

## Further required work for actual validated wagers
1. Independently timestamped sportsbook odds receipts and paired decision/
   closing quote snapshots, not merely source-card hash.
2. Frozen, calibrated score distributions tested on untouched forward games,
   with integer-point push handling in any actual production scorer.
3. Settlements on enough genuinely future priced decisions for reliable
   realized return, Brier/log loss, CLV, interval estimates, and drift tests.
4. Separate protected model/production eligibility PR only after evidence.

## Research CLI

    python -m unittest tests.test_cfb_sdv_forward_snapshot tests.test_cfb_forward_priced_ev -v
    python scripts/research_cfb_forward_priced_ev.py --snapshot forward.json --output priced_shadow.json
    python scripts/research_cfb_forward_priced_ev.py --snapshot forward.json --outcomes finals.json --output hypothetical_settlement.json

Finals input is a JSON list of {game_id, home_points, away_points,
status: FINAL, final_at: ISO-UTC, outcome_source_sha256: 64-char SHA256}.
Submitted hashes alone do not independently validate a sports result.
