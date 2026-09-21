# NFL RUN IT card — sides and totals

Send executable quotes and model probabilities. Get a short ranked card.
Empty is valid. Official labels stay in the ledger.

```text
quotes.json + models.json → python -m sportsedge.nfl_run_it → card
```

## Face

- pick at the posted line
- best available price on the quote
- estimated edge in probability points
- score /100 (supports rank; does not invent edge)
- one-sentence reason

Rank is estimated +EV at the posted price. Score is a tie-break / confidence display.

## Scope of this slice

NFL `moneyline`, `spread`, `total` only. Props stay out.

## Acceptance

- Binds the posted price and line; does not reconstruct a market line.
- 0–N rows. Zero is a pass (`Nothing looks strong enough.`).
- No Official / Lean label required to print.
- Missing model for a quote omits that quote; it does not invent a lean.
