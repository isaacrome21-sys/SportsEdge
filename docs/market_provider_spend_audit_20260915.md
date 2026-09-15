# Odds-provider spend audit — 2026-09-15

Status: PARTIALLY_PROVEN. Do not infer request counts that are not present in durable evidence.

## Proven current architecture

- NFL 2026 confirmation uses free nflverse schedule data to determine whether a frozen OPENER/FINAL capture is due before the paid capture path is allowed to run.
- Outside a due NFL confirmation window, provider preflight is cadence-throttled.
- The 2026-09-15 Week 2 OPENER attempt produced four HTTP 401 responses, but that artifact does not contain a textual quota reason or historical usage ledger.
- MLB V8 policy/work described schedule/window gating and reserve-capped paid historical recovery.
- MLB automatic acquisition still contains a broad The Odds API native path for game prices, props, team totals and additional derivatives; a separate ESPN game-market path already exists for ML/RL/totals.

## Not proven

- Which workflow/account operation consumed the monthly 2,000-credit allowance.
- How many credits were consumed by MLB V8 historical recovery versus live/automatic acquisition versus other consumers.
- That migrating current game-market consumers alone would have prevented this exhaustion.

The broad MLB acquisition path is a plausible consumer of metered credits, but that attribution remains an inference. Historical request counts or quota shares MUST NOT be estimated without durable provider accounting evidence.

## Engineering consequence

The provider abstraction is justified independently of the exhaustion attribution: free eligible observations should be preferred for book-agnostic ML/RL/totals, while unsupported markets fail closed or use a metered provider. Savings claims remain unquantified until a durable request/quota ledger establishes attribution.

Future metered acquisitions should emit redacted accounting metadata sufficient to attribute consumption by lane, provider endpoint, market set, run id and observed quota delta without storing credentials.
