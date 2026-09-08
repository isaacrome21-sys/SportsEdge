# SportsEdge HYBRID provenance and reachability contract

## Core invariant

Manual data prices today's card and is structurally incapable of becoming tomorrow's evidence.

A manually supplied market observation is a distinct provenance type, not a normal acquired quote with a `source=MANUAL` flag. It may be used only for current-card market evaluation after its user-supplied identity and threshold are validated for that card. It must be rejected by type from:

- PIT capture ledgers
- CLV decision/close pairing
- replay/calibration bundles
- training bundles
- promotion evidence
- any persisted source ledger that represents independently acquired market evidence

Negative tests must attempt each forbidden crossing and require fail-closed rejection.

## Severity hierarchy for null/default defects

1. ACQUISITION / IDENTITY
2. MODEL INPUT
3. EVIDENCE / GOVERNANCE
4. CONTROL FLOW
5. DISPLAY

Acquisition/identity is highest because a false default can create a wrong-but-valid row that propagates into both model inputs and evidence. Identity defects also inherit the severity of every downstream artifact they can contaminate.

## Minimal HYBRID asking rule

RUN IT asks the user for an input only when all of the following are true:

1. the market has a production-wired engine;
2. required non-market model inputs are independently available and fresh enough;
3. the engine/distribution is otherwise executable;
4. the only remaining blocker is a user-suppliable market observation;
5. supplying that observation can change the current card.

Missing optional context, unsupported markets, markets already blocked upstream, or inputs irrelevant to the venue/state must never generate questions. Everything else remains explicitly BLOCKED with the specific missing input.

## Manual reachability contract

Each market registry entry must declare which manual observation types can unlock current-card evaluation.

Reachability has an additional precondition: any shared distribution used by the market must already exist from independently sourced model inputs with valid provenance. A distribution whose own required inputs were manually supplied cannot be treated as independently sourced and cannot use registry reachability to unlock a family of derivative markets.

One manual quote never authorizes related markets implicitly. A supplied moneyline prices only the moneyline unless another market's registry contract explicitly requires only its own threshold/price plus an independently sourced shared distribution.

Orchestration must verify the distribution provenance before honoring manual reachability. The registry declares capability; runtime provenance determines whether that capability is usable on this run.

## Market/model separation

Manual market observations, sportsbook prices, implied probabilities, no-vig probabilities, bettor splits, market movement and capper sentiment may not become hidden predictors of Model_P unless a separately governed methodology explicitly authorizes that feature.

Current-card pricing may use the supplied threshold/price solely to evaluate the independently generated probability of the specified event and to compute market probability, edge, EV and stake eligibility.

## Required attack tests

- Manual observation -> PIT ledger: reject by type.
- Manual observation -> CLV pair: reject by type.
- Manual observation -> training/replay bundle: reject by type.
- Manual input at distribution base -> derivative-market reachability: reject.
- Manual quote for one market -> sibling market without explicit registry reachability: reject.
- Independently sourced distribution + valid manual threshold/price for an explicitly reachable market: allow current-card evaluation only.
