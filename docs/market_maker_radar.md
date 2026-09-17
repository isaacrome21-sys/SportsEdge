# MARKET_MAKER_RADAR_V1

## Purpose

`MARKET_MAKER_RADAR_V1` is a model-free Layer B HARD MARKET diagnostic. Its primary observable is price leadership: a designated market-maker book changes a price or line, a retail/soft book remains behind, and the soft book subsequently follows. It also identifies same-line stale-price candidates from native Pinnacle observations by comparing the offered soft-book break-even probability with Pinnacle's contemporaneous two-sided no-vig probability.

This lane has **no** Model_P, Truth Gate, promotion, eligibility, staking, or OFFICIAL authority. It can support or conflict with a separate SportsEdge betting decision, but it cannot create a promoted bet or inherit promotion evidence.

## Signal hierarchy

1. **MARKET_MAKER_LEAD** — a threshold-eligible market-maker move is observed before a same-direction soft-book move within the frozen follow window. Every leader/follower source family has an immutable `source_family_id`; native and aggregator families are never blended.
2. **STALE_SOFT_PRICE** — for native Pinnacle snapshots only, the soft book offers the same line/market/selection at a break-even probability at least the research threshold below Pinnacle's contemporaneous normalized no-vig probability.
3. **LINE_ADVANTAGE_CANDIDATE** — a native soft book has a materially better spread/total number than Pinnacle. It is intentionally *not* converted to EV because different lines require a genuine probability model.
4. **MULTI_BOOK_STEAM** — multiple books move in the same direction inside the frozen time window. This is secondary price-only context, not proof of sharp action.
5. Ticket/handle divergence and RLM-style labels remain annotation only. They cannot create a radar signal. Any RLM label still requires the existing news-attribution gate.

## Timing rules

The analyzer prefers a provider's `book_last_update` timestamp when one is genuinely present. It falls back to SportsEdge `captured_at` otherwise. If a market-maker and soft-book move have the same effective timestamp, no leader is assigned. If both changes arrive in the same SportsEdge poll, leadership is allowed only when both rows carry distinct valid `book_last_update` timestamps; otherwise the pair is synchronous.

For `FOURC_LINE_HISTORY_V1`, the time displayed by 4C is treated as an **aggregator observation time**, not a sportsbook-native quote timestamp. The importer therefore writes it to `captured_at`, leaves `book_last_update` null, and sets `provider_quote_timestamp_available=false`.

These rules prevent polling order or an aggregator display from fabricating native sportsbook timing authority.

## Data plane

The radar can consume three isolated observation channels from the append-only `data` branch:

1. the existing paid closing-line archive;
2. the direct-public NFL market-radar capture lane; and
3. provenance-bound 4C line-history imports under `archive/market-maker-radar/fourc`.

Native radar books are Pinnacle, DraftKings and FanDuel. Circa remains `PROVIDER_REQUIRED` rather than being synthesized.

4C observations are namespaced as `fourc_pinnacle`, `fourc_draftkings`, and `fourc_fanduel`, and their event IDs are namespaced with `fourc:`. This prevents 4C's aggregated history from silently joining a native Pinnacle/DraftKings/FanDuel source family.

A missing market-maker feed yields a blocked diagnostic rather than silently treating a soft-book-only lane as sharp-money evidence.

## 4C line-history corroboration

SportsEdge does **not** assume or scrape an undocumented 4C API. `scripts/capture_market_maker_fourc_line_history.py` accepts a deliberately small `FOURC_LINE_HISTORY_CAPSULE_V1` JSON capsule made from a retained 4C line-history source capture or supported export. The capsule must carry:

- the 4C source URL;
- a SHA-256 binding to the retained source capture;
- event identity and scheduled start time;
- one supported market (`h2h`, `spreads`, or `totals`); and
- observations containing book, side/designation, American price, line when applicable, and the displayed move time.

The importer computes a second SHA-256 over the exact capsule bytes. Every normalized row contains both bindings. Unsupported books, malformed timestamps, invalid prices/points, and duplicate observations fail closed.

Example import:

```bash
python scripts/capture_market_maker_fourc_line_history.py \
  --input /path/to/fourc-capsule.json \
  --out /path/to/archive/market-maker-radar/fourc/2026-09-16.ndjson
```

The 4C lane is **independent aggregator corroboration only**. It has no native sportsbook identity authority and cannot satisfy DraftKings OPENER/FINAL capture requirements, PIT evidence, Model_P, Truth Gate, promotion, eligibility, staking, evidence clocks, wager placement, or OFFICIAL status. Its leader/follower families are graded separately as `FOURC_PINNACLE_TO_DRAFTKINGS_LEAD_LAG_V1` and `FOURC_PINNACLE_TO_FANDUEL_LEAD_LAG_V1` and are never blended with the native source families.

## Grading

Every leader/follower family is graded separately. The policy freezes `n < 100` as `INSUFFICIENT`; even at `n >= 100`, no edge claim is allowed until the source family is graded through the existing CLV machinery. The intended report set is CLV first, then hit rate and flat-1u ROI. Win rate by itself is not validation.

## Public-repository adoption

The implementation is original SportsEdge code, but two MIT-licensed public projects supplied useful design patterns:

- `SportsGameOdds/live-odds-tracker` — previous/current quote state keyed by event/market/book, thresholded movement detection, and append-only movement history.
- `AntonioKaram/kalshi-kit` — explicit lead/lag diagnostics and the principle that lag hypotheses must be measured and aggregated rather than asserted.

The NFL project `bobby-king3/nfl-market-movement-tracker` also demonstrates a useful snapshot → line-movement → game-summary data model, but no license was present when reviewed, so its code was not copied or imported.

See `THIRD_PARTY_NOTICES.md` for the MIT notices retained for the adopted design sources.
