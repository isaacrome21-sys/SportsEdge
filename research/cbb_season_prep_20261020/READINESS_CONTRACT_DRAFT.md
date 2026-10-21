# CBB 2026–27 season-prep evidence contract and dependency handoff

**DRAFT / NO-GO / NO MARKET PRICING / NO MODEL PROMOTION / UNRUN.**

## Why prep is required rather than another engine

CBB model and Illinois-safe identity work already exists on **open, separate PRs**:

| Existing owner branch/PR | Actual scope | This document's treatment |
|---|---|---|
| #2152 | CBB as-of ratings model, evaluation docs and ESPN-ID binder | Already claimed. Do not reimplement |
| #2197 | CBB exact fixture IDs and duplicate slot binding | Already claimed. Do not claim receipt integrity here |
| #2350 | CBB game/halves and player stat foundations, Illinois exclusion | Already claimed and unvalidated. Do not duplicate |
| #2217 / #2224 | Shared family registry/research stopgap/runner | Existing governance; no bypass |
| #2280 | DraftKings captured-market evidence contract | Require independently admitted DK fixture+outcome IDs before market comparisons |

The repo's CBB readiness problem is currently one of **composition and evidence admission**. This prep packet does not change production models, gates or registry and does not preempt any of the above merges.

## Source contract to admit a 2026–27 CBB fixture

1. **Fixture identity:** NCAA Division I 2026–27 regular-season event with non-null ESPN event ID and exact home/away school ESPN IDs; no name-only fallback. Doubleheader, neutral court, relocated start, renamed school and duplicate ESPN slot collisions must be distinguished. The fixture's scheduled local time, UTC time, provider observed-at and source archive hash must be pinned. A later schedule revision requires new, independently linked receipts and cannot mutate an older observation silently.
2. **Illinois college exclusion:** before any research pricing, registration, synthetic candidate output, or market comparison, independently map each of the TWO school ESPN IDs to an authorized frozen exclusion registry. If either school belongs to Illinois, block. Lack of registry coverage, stale directory, ambiguous school name, or absent IDs is **UNKNOWN/BLOCKED**, never outside-Illinois by default. This is a college-team restriction; it is not an exclusion of Illinois professional teams in other sports.
3. **PIT historical score samples:** training games must have completed official scores and verified gamePk/event IDs, UTC scheduled/actual-start and result observed-at strictly before each target as-of. No replay of same-day later scores and no mismatched venue switch, invalid neutral-court field, postseason mix or stale schedule. Use the existing as-of model's own training and holdout clauses; this packet does NOT create replacement warmup/validation thresholds.
4. **Half/player outcome completeness:** scored first/second halves must come from actual half scoreboard observations with an immutable provider raw source, not half of final scores. CBB player props need per-game player IDs, team roster, minutes/participation and complete box outcomes with proper DNP and overtime treatment, plus explicit official NCAA settlement convention. No playing time from an athlete merely appearing on the roster.
5. **Bookmaker availability/identity:** ensure source fixture and DraftKings event ID match the precise event/date. Require actual paired opposite-side quotes of the same bookmaker/market/period/line, receipt span and quote freshness, final re-read and provenance. One-sided milestones are NEVER silently no-vigged. Coverage must preserve NOT_OFFERED vs NO_ENGINE vs NO_DATA. No quoting a future CBB line from an assumed NBA analogue.
6. **Forward evaluation:** predeclare chronological target dates and market families *before* outcome observation and hold the same family/time line across model and market comparator; calibrate against strictly-prior climatology and independently captured market legs, report Brier/log loss and actual paired sample N, CLV and ROI separately, and never backfill blocked fixtures.
7. **Ownership and stop conditions:** #2152, #2197, #2350, #2217 remain owner/merger-held; new source observations cannot alter their frozen or pending artifacts. Any school missing the exclusion registry is still BLOCKED. Owner must explicitly approve CBB registry state, source fixture evidence and independent reviewer finding before activation.

## First 2026–27 readiness audit template — ALL UNVERIFIED

| Check | Evidence needed | Current status |
|---|---|---|
| ESPN schedule/event directory with verified IDs | Complete raw source, manifest SHA-256 and observed-at | NO_ADMITTED_SOURCE_MANIFEST |
| Team-identity Illinois check across full slated event set | Frozen ID registry, exact team mapping, coverage count | NO_CERTIFIED_COVERAGE_REPLAY |
| Historical PIT model features and partial season cutoffs | source chronology, roster/venue and team identity | NO_NEW_PIT_SCREEN |
| Actual independent DK market capture | paired book/period/rung receipt, quote freshness, no-vig eligibility | NO_MARKET_TEST |
| CBB game/half/player families | independent #2350 and #2152 review, first screens | NOT_VALIDATED |
| CBB candidate/PLAY activation | owner ruling after source/market scoring | HELD_NO_GO |

**No games, scores, test counts, favorable results, market odds, or California/Illinois eligibility are invented here.** This is a handoff checklist meant to prevent a partly implemented CBB model from being mistaken for a verified pregame betting system.
