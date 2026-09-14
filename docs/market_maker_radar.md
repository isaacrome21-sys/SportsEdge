# MARKET_MAKER_RADAR_V1

## Purpose

`MARKET_MAKER_RADAR_V1` is a model-free Layer B HARD MARKET diagnostic. Its primary observable is price leadership: a designated market-maker book changes a price or line, a retail/soft book remains behind, and the soft book subsequently follows. It also identifies same-line stale-price candidates by comparing the offered soft-book break-even probability with Pinnacle's contemporaneous two-sided no-vig probability.

This lane has **no** Model_P, Truth Gate, promotion, eligibility, staking, or OFFICIAL authority. It can support or conflict with a separate SportsEdge betting decision, but it cannot create a promoted bet or inherit promotion evidence.

## Signal hierarchy

1. **MARKET_MAKER_LEAD** — a threshold-eligible Pinnacle move is observed before a same-direction DraftKings or FanDuel move within the frozen follow window. Each leader/follower pair has its own immutable `source_family_id`; DK and FD are never blended.
2. **STALE_SOFT_PRICE** — the soft book offers the same line/market/selection at a break-even probability at least the research threshold below Pinnacle's contemporaneous normalized no-vig probability.
3. **LINE_ADVANTAGE_CANDIDATE** — a soft book has a materially better spread/total number than Pinnacle. It is intentionally *not* converted to EV because different lines require a genuine probability model.
4. **MULTI_BOOK_STEAM** — multiple books move in the same direction inside the frozen time window. This is secondary price-only context, not proof of sharp action.
5. Ticket/handle divergence and RLM-style labels remain annotation only. They cannot create a radar signal. Any RLM label still requires the existing news-attribution gate.

## Timing rules

The analyzer prefers the provider's `book_last_update` timestamp. It falls back to SportsEdge `captured_at` only when the book timestamp is absent or invalid. If a market-maker and soft-book move have the same effective timestamp, no leader is assigned. If both changes arrive in the same SportsEdge poll, leadership is allowed only when both rows carry distinct valid `book_last_update` timestamps; otherwise the pair is synchronous.

These rules prevent a five-minute polling loop from fabricating sub-poll ordering that the source data cannot support.

## Data plane

The existing `closing-line-archive` workflow is the only sportsbook data plane. It captures two-sided `h2h`, `spreads`, and `totals` observations into the append-only `data` branch. The market-radar policy currently defines:

- Market maker: Pinnacle
- Soft books: DraftKings, FanDuel
- Provider-required/not yet captured: Circa

A missing market-maker feed yields `BLOCKED_NO_MARKET_MAKER_DATA`. A DK-only fallback can never silently become a sharp-money radar.

## Grading

Every leader/follower family is graded separately. The policy freezes `n < 100` as `INSUFFICIENT`; even at `n >= 100`, no edge claim is allowed until the source family is graded through the existing CLV machinery. The intended report set is CLV first, then hit rate and flat-1u ROI. Win rate by itself is not validation.

## Public-repository adoption

The implementation is original SportsEdge code, but two MIT-licensed public projects supplied useful design patterns:

- `SportsGameOdds/live-odds-tracker` — previous/current quote state keyed by event/market/book, thresholded movement detection, and append-only movement history.
- `AntonioKaram/kalshi-kit` — explicit lead/lag diagnostics and the principle that lag hypotheses must be measured and aggregated rather than asserted.

The NFL project `bobby-king3/nfl-market-movement-tracker` also demonstrates a useful snapshot → line-movement → game-summary data model, but no license was present when reviewed, so its code was not copied or imported.

See `THIRD_PARTY_NOTICES.md` for the MIT notices retained for the adopted design sources.
