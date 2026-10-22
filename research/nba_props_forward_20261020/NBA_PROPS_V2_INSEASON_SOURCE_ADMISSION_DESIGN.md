# NBA props in-season store V2 — source-admission design (DRAFT, NOT FROZEN)

Status: **PROPOSAL ONLY — NO OWNER GO, NO ADMITTED SOURCE, NO FORWARD CLOCK.**
Prepared 2026-10-21 for independent review. This document neither modifies nor supersedes
`research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md`.

## Problem and protected baseline

The sportsdataverse 2026-27 NBA player box-score / roster assets are not published in
the source inventory as of the investigation; its available NBA datasets stop at the
prior season. The frozen NBA props V1 input therefore stays unavailable. **Do not**
inject a newly scraped or differently sourced store into V1: its §10 requires a new
versioned construction and a new prospective freeze.

The existing `NBAPublicPlayerHistory` retrieves ESPN v3 player gamelogs, but its
default five-game / mixed-season behavior differs from the V1 empirical engine's
ten-prior-**same-season**-game requirement. It is a source lead, not an approved V1
replacement or a vetted V2 store.

## Candidate in-season source contract

**Candidate A, preferred for admission testing:** official NBA *completed-game*
player box scores, retrieved from the NBA-operated game box-score feed for an
NBA game ID (candidate URI pattern:
`https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gameId}.json`).
Availability, publication timing, shape, and access policy are **not yet
verified for this runtime**. A 403, missing game, live/pre-final document,
schema drift, or provider restriction is a refusal, never a reason to fabricate
or silently switch feeds. No unauthorized access workaround.

**Independent check:** ESPN public completed-game player gamelogs (existing
`sportsedge/sports/nba/espn_verified_source.py` and
`nba_gamelog_decode.py`) for identity/date/PTS/REB/AST spot checks. ESPN is
not NBA-operated and must be identified as such. It is **not** an automatic
fallback. If Candidate A is unavailable, the owner may evaluate ESPN as
Candidate B under a separately named, independently admitted source contract
and freeze. Do not mix sources per row without a new approved rule.

**Positions:** source an independently versioned official season roster or
game roster with player ID and role at the **historical target time**. Reject
missing/unverified positions; do not infer from name, current roster, player
minutes, or newer lineup.

## Proposed admission protocol (before any V2 freeze)

1. Pin retrieval endpoints, license/use restrictions, parser version and code
   SHA. Archive unaltered response bytes with SHA-256, source URL, fetched-at
   timestamp and NBA game ID in a staging-only evidence manifest. Never record
   secrets or account cookies.
2. Probe >=8 **final** 2026-27 regular-season games on >=3 distinct NBA game
   dates, and >=80 eligible player-game observations across those games.
   Include different teams, at least one overtime game **if one exists** (else
   record `OT_NOT_IN_SAMPLE`), DNP, inactive, and traded-player/ambiguous-name
   cases **if observed**; do not manufacture cases to satisfy coverage.
3. Verify season attribution, game start (UTC with timezone), unique official
   game ID, team IDs, official player IDs, final status, and signed completed
   box-score PTS/REB/AST/minutes. Reject negative/non-integer stats, duplicate
   player-game rows, future games, and conflicting final revisions. Exclude
   DNP/minutes-zero, with explicit counts.
4. On ≥50 separately identity-joined eligible player-game observations across
   ≥5 completed games, compare source stats to an independently fetched ESPN
   final log. Require **zero unresolved disagreements** for PTS/REB/AST and
   same game date/team/player. A missing independent record is
   `CROSSCHECK_UNAVAILABLE`, not agreement. Do not join by player name alone.
5. Produce *per-cell* refusal counts for `SOURCE_UNAVAILABLE`,
   `NOT_FINAL`, `SCHEMA_INVALID`, `GAME_ID_AMBIGUOUS`,
   `PLAYER_ID_UNVERIFIED`, `POSITION_UNKNOWN`,
   `GAME_DATE_UNKNOWN`, `DUPLICATE`, `STAT_CONFLICT`,
   `MISSING_COMPARISON`, `DNP_EXCLUDED`, and
   `SOURCE_CHANGED_AFTER_SNAPSHOT`; report denominators and date spread.
6. Independent verifier reproduces sample hashes, schema fixture tests,
   refusal examples, and the comparison ledger from a **pinned revision**.
   Admission is explicit and owner-approved; sample success is not automatic
   admission, engine validation, or source freeze.

The candidate thresholds above are **proposed**, not silently in force.
They must be accepted or revised and fixed *before* looking at their outcomes.

## Proposed V2 store and model version (not implemented here)

- New namespace/version and immutable store manifest:
  `NBA_PROP_EMPIRICAL_V2_OFFICIAL_BOX` (exact identifier subject to prereg).
  Keep `NBA_PROP_EMPIRICAL_V1` and its records untouched.
- Each history row: canonical season/year, game ID/date/start, player ID,
  verified position, played-for team, PTS, REB, AST, minutes, source ID,
  response digest, snapshot time, roster digest and exclusion reason.
- Before a target game, permit only completed *same-season* games strictly
  **earlier than the target calendar date**, whose source snapshots were
  available **before the entry cutoff**. Exclude DNP/minutes-zero and require
  `n_prior >= 10`; reject missing sources, roster/identity ambiguity and
  cross-season fallback. No future target stats as model inputs, no after-tip
  repair of a prospective entry.
- Maintain the V1 engine's four separately scored families
  (PTS, REB, AST, PRA); compute PRA from joint per-game summed observations,
  not independent stat products. Any participation/minutes enhancements are
  **another challenger**, not a silent data-only V2 change.
- Separate priced/passed rows, exact paired DK side/line/fixture binding,
  complete quote timestamps, a <=180-second quote freshness rule,
  ≤150-second capture-span target, pre-tip final re-read, and distinct
  immutable V2 entry/close records. Retain missing closes rather than
  creating retrospective prices.
- Freeze a new `PREREG_NBA_PROPS_FORWARD_V2.md` and code/data hashes **before
  the first countable V2 slate**. Carry over or explicitly justify any changes
  to V1's 4-full-slate, per-market 40-distinct-games and 50-row review floor,
  100-row insufficiency threshold, game-clustered uncertainty, CLV-first
  market comparison, and owner-only promotion.
- No historical backfill to V1, V2, or any prospective clock. Work done before
  the new freeze is source admission and offline research **only**.

## Independent tests to implement only after source-design ruling

- Test NBA final vs in-progress vs postponed feed envelopes, game-ID alias,
  season boundaries, UTC/local date, duplicate team/player and OT stats.
- Test invalid/missing PTS/REB/AST/minutes and zero-minute DNP refusal.
- Test same-season prior-game strict cutoff, exactly 9 vs 10 prior games,
  position missing, cross-season leakage, late-arriving/revised box score.
- Test independent ESPN comparison detects one-point/one-assist mismatch,
  wrong player, wrong game/team, and unjoinable ESPN ID.
- Demonstrate end-to-end: pinned source manifest → PIT store → V2 research
  estimate → exact two-sided DK entry → genuine pre-tip close → graded row,
  without ever reading or rewriting a frozen V1 ledger.

## Required owner decisions (OPEN)

1. Authorize design and independent admission probes for Candidate A, with
   ESPN strictly as cross-check? **UNDECIDED.**
2. Approve objective admission thresholds before data review? **UNDECIDED.**
3. After an independent admission verdict, authorize V2 code/prereg/freeze
   and prospective pricing? **UNDECIDED — separate ruling required.**

Nothing in this proposal changes any validation score, unlocks PLAY, or
certifies that the provider currently offers accessible 2026-27 records.
