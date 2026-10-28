# NBA props in-season store — Candidate B (ESPN) source-admission contract (DRAFT, NOT FROZEN)

Status: **PROPOSAL ONLY — NO OWNER GO, NO ADMITTED SOURCE, NO FORWARD CLOCK.**
Prepared 2026-10-27 for owner review. This document neither modifies nor
supersedes `research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md`
(frozen, unedited) or
`research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V2.md`.

Template: this contract mirrors the closed Candidate A admission protocol —
`research/nba_props_forward_20261020/NBA_PROPS_V2_INSEASON_SOURCE_ADMISSION_DESIGN.md`
(PR #2474), as executed by
`research/nba_props_forward_20261020/nba_cdn_admission_battery.py`. Every
threshold below is carried over from that protocol unchanged; nothing here is
a new bar.

## Why Candidate B exists

The Candidate A protocol has closed. The admission battery was executed
under it; the 2026-10-22 run from the SportsEdge VM failed the availability
section with an Akamai HTTP 403 from the NBA-operated CDN, and
`PREREG_NBA_PROPS_FORWARD_V2.md` §2.5 records the NBA.com CDN box-score feed
as **not admitted**. The design's own provision governs what happens next:
*"If Candidate A is unavailable, the owner may evaluate ESPN as Candidate B
under a separately named, independently admitted source contract and
freeze."* This document is that separate contract, in draft.

The recorded NBA props V2 freeze is **quarantined** under the owner's
2026-10-27 ruling: the recorded freeze does not establish a valid clock
start, later clearance cannot cure the sequencing or exact-head gap, and
there is no retroactive counting. Nothing in this draft lifts that
quarantine or substitutes for the separate prospective authorization a
future freeze requires.

## Candidate B source contract

**Candidate B, for admission testing:** ESPN public completed-game player
gamelogs — the surface the Candidate A design named as its independent
check, retrieved through `sportsedge/sports/nba/espn_verified_source.py`
and `sportsedge/sports/nba/nba_gamelog_decode.py` — now evaluated in the
**primary** role. ESPN is not NBA-operated and must be identified as such
in every record it produces.

The existing `NBAPublicPlayerHistory` behavior (default five-game /
mixed-season retrieval) differs from the ten-prior-**same-season**-game
requirement and is a source lead, not a vetted store; the candidate surface
under this contract is completed-game finals only. ESPN's separately
admitted roles in `PREREG_NBA_PROPS_FORWARD_V2.md` (summary-API supplement
§2.2, scoreboard schedule authority §2.3, rosters §2.4) confer **no**
primary-source admission and are unchanged by this draft.

**Independent check (role mirror of the Candidate A protocol):** official
NBA completed-game box scores (the Candidate A feed,
`https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gameId}.json`),
independently fetched, used **only** to cross-check identity/date/
PTS/REB/AST. It is not a fallback source. Do not mix sources per row
without a new approved rule.

**Positions:** source an independently versioned official season roster or
game roster with player ID and role at the **historical target time**.
Reject missing/unverified positions; do not infer from name, current
roster, player minutes, or newer lineup.

## Admission protocol — bars fixed in advance

These bars are the Candidate A bars, unchanged. They must be accepted or
revised and fixed *before* looking at their outcomes; they cannot be
lowered to achieve a pass, and any revision after outcomes are seen is a
new versioned contract, not an edit to this one.

1. **Provenance.** Pin retrieval endpoints, license/use restrictions,
   parser version and code SHA. Archive unaltered response bytes with
   SHA-256, source URL, fetched-at timestamp and NBA game ID in a
   staging-only evidence manifest. Never record secrets or account
   cookies.
2. **Availability.** Probe >=8 **final** 2026-27 regular-season games on
   >=3 distinct NBA game dates, and >=80 eligible player-game observations
   across those games. Include different teams, at least one overtime game
   **if one exists** (else record `OT_NOT_IN_SAMPLE`), DNP, inactive, and
   traded-player/ambiguous-name cases **if observed**; do not manufacture
   cases to satisfy coverage.
3. **Integrity.** Verify season attribution, game start (UTC with
   timezone), unique official game ID, team IDs, official player IDs,
   final status, and completed box-score PTS/REB/AST/minutes. Reject
   negative/non-integer stats, duplicate player-game rows, future games,
   and conflicting final revisions. Exclude DNP/minutes-zero, with
   explicit counts.
4. **Cross-check.** On ≥50 separately identity-joined eligible player-game
   observations across ≥5 completed games, compare Candidate B stats to an
   independently fetched official NBA final log. Require **zero unresolved
   disagreements** for PTS/REB/AST and same game date/team/player. The
   join is **not** by player name alone: the game is matched on date plus
   both team tricodes, the team on tricode, and the player on team plus
   jersey number with normalized-name agreement required. A missing
   independent record is `CROSSCHECK_UNAVAILABLE` /
   `MISSING_COMPARISON`, not agreement.
5. **Refusal accounting.** Produce *per-cell* refusal counts for
   `SOURCE_UNAVAILABLE`, `NOT_FINAL`, `SCHEMA_INVALID`,
   `GAME_ID_AMBIGUOUS`, `PLAYER_ID_UNVERIFIED`, `POSITION_UNKNOWN`,
   `GAME_DATE_UNKNOWN`, `DUPLICATE`, `STAT_CONFLICT`,
   `MISSING_COMPARISON`, `DNP_EXCLUDED`, and
   `SOURCE_CHANGED_AFTER_SNAPSHOT`; report denominators and date spread.
6. **Independent verification.** An independent verifier reproduces sample
   hashes, schema fixture tests, refusal examples, and the comparison
   ledger from a **pinned revision**. Admission is explicit and
   owner-approved; sample success is not automatic admission, engine
   validation, or source freeze.

## Hard refusal discipline

A 403, missing game, live/pre-final document, schema drift, or provider
restriction is a refusal, never a reason to fabricate or silently switch
feeds. No unauthorized access workaround. A failed section is recorded as
failed with its refusal counts; the probe does not rerun under loosened
terms.

## What admission does NOT authorize

Passing this admission — if it passes — earns only the right to **request**
a separate V2 freeze and go-live decision from the owner. It does not
authorize a freeze, a forward-clock start, pricing, counted rows, PLAY, or
any change to validation status or eligibility. The V1 preregistration
remains frozen and unedited. No historical backfill to V1, V2, or any
prospective clock. Work done under this contract is source admission and
offline research **only**. Research-only / PAPER / 0u throughout.

## Required owner decisions (OPEN)

1. Authorize design and independent admission probes for Candidate B, with
   the official NBA feed strictly as cross-check? **UNDECIDED.**
2. Approve the admission bars above before data review? **UNDECIDED.**
3. After an independent admission verdict, authorize any V2 freeze and
   prospective pricing? **UNDECIDED — separate prospective ruling
   required, per the 2026-10-27 quarantine ruling.**
