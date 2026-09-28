# NFL research-card integrity contract

This is the publishing layer for NFL research cards built from the existing game-market and prop outputs. It is intentionally **EXPERIMENTAL / NOT OFFICIAL** and does not create Model_P, alter Truth Gate, promote a market, or grant staking authority.

## Why this layer exists

A visually polished card can still be wrong if it reuses a score forecast after a lineup change, carries an old sportsbook quote, highlights a zero/negative-EV row, maps a player to the wrong team logo, or presents research-only output as a pick. The research-card contract fails closed on those presentation errors.

## Publish requirements

The card requires all of the following before a row can appear under `research_edges`:

- the game forecast carries an `input_fingerprint` that exactly matches the current injury/role/input fingerprint;
- the forecast `generated_at` timestamp is not earlier than the current input snapshot;
- the sportsbook offer has an explicit `quote_timestamp`, `price_timestamp`, or `quote_as_of`;
- the quote age is within the configured freshness window (15 minutes by default);
- upstream EV is strictly positive;
- model probability is strictly above the offered price's break-even probability;
- player team/logo display comes only from a verified `player_id -> team` binding; a conflicting row team fails the card;
- a displayed Score comes only from an upstream `qualification_score`. The card never turns EV or edge into Score.

Rows that fail offer-level economics or freshness are omitted from the published research edges and recorded under `excluded` with explicit reasons. A stale or mismatched forecast blocks the entire card with `NFL_CARD_RECOMPUTE_OR_BLOCK` because every downstream market depends on that forecast state.

## Presentation rules

Every output carries `authority_label = "EXPERIMENTAL / NOT OFFICIAL"`, `official = false`, and `crown_allowed = false`. The builder strips `crown`, `pick`, `top_pick`, `best_bet`, and similar presentation fields from rows and replaces them with the neutral display label `RESEARCH EDGE`.

The splits box is display-only and, when supplied, must be sourced as **ScoresAndOdds**. Its normalized metadata explicitly states that it has no promotion authority and is not used in Model_P or Score.

## CLI

```bash
python scripts/build_nfl_research_card.py \
  artifacts/nfl_research_card_input.json \
  artifacts/nfl_research_card.json
```

Minimal input shape:

```json
{
  "as_of": "2026-09-28T13:05:00Z",
  "current_input_fingerprint": "sha256-or-other-stable-input-id",
  "current_input_as_of": "2026-09-28T12:59:00Z",
  "forecast_provenance": {
    "input_fingerprint": "sha256-or-other-stable-input-id",
    "generated_at": "2026-09-28T13:00:00Z"
  },
  "game_market_rows": [],
  "prop_run_payload": {
    "sport": "NFL",
    "results": []
  },
  "roster_team_by_player_id": {},
  "splits_context": {
    "source": "ScoresAndOdds"
  }
}
```

The builder does not infer missing timestamps, silently relabel an old forecast as current, invent a player-team binding, or manufacture an economics-based Score when the qualification score is absent.
