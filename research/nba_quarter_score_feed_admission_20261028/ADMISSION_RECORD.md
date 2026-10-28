# Admission record — NBA quarter-score (period outcomes) feed: ESPN summary API

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — OUTCOMES FEED ONLY — NO
FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY — NO PRICING INPUT.**
Prepared 2026-10-28 (retrieval 2026-10-28T11:59–12:05Z) for independent
review. This record admits nothing by itself: admission takes effect only
if this PR is merged after independent (Rocky) review.

**What this closes.** The NBA period-lines preregistration draft
(`research/nba_cbb_activation_20261028/NBA_PERIOD_LINES_PREREG_DRAFT.md`,
PR #2843) records two data gates in its §4. Gate §4.1 — a lawful
`NBAPeriodObservation`-form period outcomes feed, admitted under its own
record — is the blocker this packet addresses: on the maintained
sportsdataverse path the engine refuses `NBA_PERIOD_HISTORY_UNAVAILABLE`
because the maintained team/player box-score assets carry no quarter
scores (verified 2026-10-20). This record admits the feed that satisfies
§4.1. Gate §4.2 (DraftKings period-section captures) is the lane's
separate work and is **not** addressed here.

Every factual claim below carries an evidence state: **verified-by-pull**
(bytes were downloaded from the SportsEdge runtime and hash-checked) or
**documented-only** (stated by a repo record or provider documentation;
not reproduced here).

## 1. Source and provenance

- **Admitted source:** ESPN's public summary API —
  `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={espn_event_id}`
  — the per-game document behind ESPN's own gamecast/box-score pages,
  carrying each competitor's per-period `linescores` (verified-by-pull).
- **Provenance:** ESPN is a commercial sports data publisher and is
  **not NBA-operated** (documented-only; stated identically in the
  Candidate B contract draft,
  `research/nba_props_forward_20261020/NBA_PROPS_V2_CANDIDATE_B_ESPN_ADMISSION_CONTRACT_DRAFT.md`).
  ESPN's linescores derive from the official game scoring record ESPN
  republishes; §5 records two independent corroborations of that claim.
- **Relation to ESPN's existing roles:** the NBA props V2 preregistration
  already names ESPN surfaces in *other* roles (summary-API supplement
  §2.2, scoreboard schedule authority §2.3, rosters §2.4 —
  documented-only). Those roles confer no admission here, and this
  record confers none there: this admission is for the **period-lines
  family's outcomes feed only**. The Candidate B contract (ESPN as a
  proposed *primary player-gamelog* source for NBA props) remains a
  draft for a different family and is untouched by this record.
- **Form produced:** one `NBAPeriodObservation`
  (`sportsedge/sports/nba/period_history.py`) per completed game:
  `game_id` = ESPN event id, `tipoff` = the payload's scheduled start,
  `observed_at` = the actual pull timestamp, `home_quarters` /
  `away_quarters` = the **four regulation quarters only**, `source` =
  `ESPN_SUMMARY_API`, `source_version` = `espn-summary-v1:20261028`.
  Overtime periods are carried in the manifest separately and **never**
  enter the quarter tuples — the observation form takes exactly four,
  and the four prereg families (team/game × quarter/half totals) settle
  on regulation periods; there is no fifth-quarter market in scope.
  Half splits are the exact mechanical sums H1 = Q1+Q2, H2 = Q3+Q4.

## 2. Candidate battery — all candidates actually executed

Executed 2026-10-28 from the SportsEdge runtime. Full probe log with
hashes in `sample_manifest.json` (`candidate_probes`).

- **Candidate 1 — ESPN summary API: WORKS (verified-by-pull).** HTTP 200
  for every sampled game across the full span the family needs:
  2014-15 (the frozen fit span), 2020-21, the 2026 postseason, and the
  current 2026-27 season (§4). The ESPN **scoreboard** API served full
  archived slates for discovery/identity (14 games on 2015-04-15; 4 on
  2026-10-27) but is a schedule surface, not the feed; it is cited as
  discovery evidence only. **This is the admitted route.**
- **Candidate 2 — NBA CDN (`cdn.nba.com` liveData box scores): FAILED
  (verified-by-pull).** `todaysScoreboard_00.json` → Akamai **HTTP
  403**; `boxscore/boxscore_0022600001.json` → Akamai **HTTP 403**. This
  **reproduces** the 2026-10-22 Candidate A admission battery failure
  from this runtime, and is consistent with
  `PREREG_NBA_PROPS_FORWARD_V2.md` §2.5, which already records the
  NBA.com CDN box-score feed as **not admitted**. Two probes, no
  circumvention. **NOT ADMITTED** — the availability bar fails from the
  only runtime that would consume it. (Whether the CDN's period data
  would be fit for purpose behind the block is moot and untested.)
- **Candidate 3 — stats.nba.com (`boxscoretraditionalv3`): FAILED
  (verified-by-pull).** Read timeout, no response within 45 s. Recorded
  for completeness as the second NBA-operated surface. **NOT
  ADMITTED.**
- **Candidate 4 — Basketball-Reference box scores: PARTIAL, fails the
  coverage bar (verified-by-pull).** Historical pages serve HTTP 200
  with complete line-score tables (2015-04-15 DEN@GSW; the 2026 Finals
  game 202606050SAS), and its DEN@GSW splits agree with ESPN on all
  eight quarter values (§5). But both sampled **current-season
  (2026-27)** games returned **HTTP 404** (202610270BOS,
  202610270LAL) — BRef coverage in this environment ends with the
  2025-26 season, while the design's population *is* the 2026-27
  forward season. A feed that cannot observe the forward population
  cannot grade it or supply its in-season priors. Four polite single
  probes, no rate pressure; under Sports Reference bot policy a 403/429
  would have been fail-closed with no circumvention. **NOT ADMITTED**
  for this role.

## 3. The admitted route and its validation discipline

Retrieval is by the committed puller `pull_espn_period_scores.py`
(stdlib only): one GET per game, browser user-agent, no key, no login.
An observation is emitted only when **all** of these hold; otherwise a
named refusal and no row:

- HTTP 200 and parseable JSON, else `SOURCE_UNAVAILABLE` /
  `SCHEMA_INVALID`.
- Payload `header.id` equals the requested event id, else
  `IDENTITY_UNVERIFIED`.
- Game status is `STATUS_FINAL` / `post`, else `NOT_FINAL` — a live,
  scheduled, or postponed game can never produce an observation (the
  2021-01-15 WSH@DET postponement, scoreboard 0-0, is the standing
  example).
- Exactly two competitors, each with ≥ 4 linescore periods, every period
  a non-negative integer, else `SCHEMA_INVALID`.
- Each side's linescore sum equals its payload final, else
  `SCORE_MISMATCH`.

**Pin rule (read before relying on this route).** The summary document
is a fat document (news, article, videos, win-probability, …) whose
bytes drift at serialization level between pulls even for long-final
games — verified 2026-10-28: two pulls of every sample produced
**identical extracted content in 5 of 5**, while whole-payload bytes
differed in 4 of 5; in the one differ-case dissected, all 19 top-level
sections were individually byte-identical across pulls. The manifest
therefore pins each sample's exact bytes *as pulled at
`pulled_at_utc`*, but the **admitted data is the extracted content**
(identity, tipoff, linescores, finals), and re-pull validation is
content-level: a linescore, final, or identity differing from the
pinned sample is refused `SOURCE_CHANGED_AFTER_SNAPSHOT`. The puller's
`--expect-sha256` strict byte check exists for snapshot reproduction
but is not the admission's validation rule.

## 4. Samples — hash-pinned, splits shown

All pulls verified-by-pull; raw bytes are kept in the local staging
area (`~/workspace/nba-period-feed-20261028/samples/`), **not**
committed — this repo stores hashes, manifests, and retrieval code only
(the #2832/#2841 precedent). Full entries, including each sample's
`NBAPeriodObservation`-form record, are in `sample_manifest.json`.

| ESPN event | Date (UTC) | Season (engine) | Type | Game | Regulation quarters H / A | Halves H / A | OT | Final |
|---|---|---|---|---|---|---|---|---|
| 400579520 | 2015-04-15 23:00 | 2014-15 (2014) | RS | CHA @ TOR | 25/30/23/14 · 20/24/23/20 | 55/37 · 44/43 | — | 87–92 |
| 400579521 | 2015-04-16 02:30 | 2014-15 (2014) | RS | DEN @ GS | 35/36/29/33 · 23/44/33/26 | 71/62 · 67/59 | — | 126–133 |
| 401267340 | 2021-01-16 00:30 | 2020-21 (2020) | RS | ORL @ BOS | 34/26/28/36 · 28/20/24/25 | 60/64 · 48/49 | — | 97–124 |
| 401859964 | 2026-06-06 00:30 | 2025-26 (2025) | **Playoff** | NY @ SA | 34/18/23/29 · 25/31/28/21 | 52/52 · 56/49 | — | 105–104 |
| 401909877 | 2026-10-27 23:30 | 2026-27 (2026) | RS | BKN @ BOS | 26/30/30/31 · 31/30/21/35 | 56/61 · 61/56 | 8 / 7 | 124–125 |

Per-sample payload pins (fetcher pull): 400579520 — 294,472 B,
sha256 `9078aa34…`; 400579521 — 371,143 B, sha256 `b59f7399…`;
401267340 — 385,560 B, sha256 `616e4a2f…`; 401859964 — 426,985 B,
sha256 `ff316b57…`; 401909877 — 510,492 B, sha256 `5827cafe…`
(full 64-hex values in the manifest). Every sample passed all §3 checks
(`linescore_sums_match_finals`, `status_final`, `identity_match`).

Note the season convention, recorded to prevent an off-by-one at
consumption: ESPN's `season.year` is the **ending** year (2027 =
2026-27); the engine's `season` integer is the **starting** year (2026
= 2026-27; the frozen fit span `season ≤ 2014` = through 2014-15). The
manifest carries both (`season_year_espn`, `engine_season`).

## 5. Identity mapping

- **Primary identity: the ESPN event id.** The engine treats `game_id`
  as an opaque join key, and the repo's maintained NBA pull keys its
  rows by the same id — **verified-by-pull**: the sportsdataverse
  `nba_schedule_2027.csv` row for the 2026-10-27 BKN@BOS game carries
  `game_id` **401909877** (the ESPN event id), finals 125/124,
  `STATUS_FINAL`, and `home_linescores` beginning 26/30/30 — identical
  to this feed's direct extraction for the same game. The feed therefore
  joins the engine's game rows and the maintained path's identity with
  **no crosswalk**. (The schedule asset itself is a rolling release and
  is **not** admitted by this record; it is cited as identity evidence
  only, pinned in the manifest's `candidate_probes`.)
- **Team identity** in the payload is ESPN tricodes (BOS, BKN, GS, …).
  One naming variant is on record from the cross-check: ESPN uses `GS`
  where Basketball-Reference uses `GSW`. Consumers join teams through
  the repo's existing tricode conventions; a tricode that does not
  resolve is `IDENTITY_UNVERIFIED`, never a guessed mapping.
- **NBA official game ids (0022…/0042…) are NOT carried** by the ESPN
  summary payload (verified-by-pull: no such id appears in the sampled
  payload). The ESPN↔NBA id crosswalk is therefore **not admitted** by
  this record. It is not needed on this family's path (grading keys on
  the ESPN-namespace `game_id`); it remains an open item for any future
  consumer keyed on NBA ids (e.g. the Candidate B contract's CDN
  cross-check role — a different family's draft, and the CDN is refused
  from this runtime in any case, §2).
- **DraftKings event ids** are a third namespace; forward rows join
  captures to outcomes through the lane registry's matchup/date mapping,
  as with every other family. Nothing in this record changes that.

## 6. Point-in-time assessment (binding on any use)

Quarter scores are **final-state outcome data**, and this section states
exactly what that means for each admitted use:

1. **What the data is.** A game's regulation quarter splits exist only
   once the game has been played; each quarter's value is final at that
   quarter's end and the full split is final at the buzzer, subject to
   later official scoring corrections. The admitted consumption is
   **post-final only** — the puller refuses anything not
   `STATUS_FINAL`. An observation's `observed_at` is the **actual pull
   timestamp**, recorded per vintage, never backdated.
2. **Design-screen / fit use (safe, with the standing caveat).**
   Retrospective splits are *labels*, not predictors: no lookahead
   arises from the label itself. Where a fit or screen consumes them,
   the repo's own PIT machinery governs — `fit_period_parameters`
   admits only rows with `observed_at < as_of`, and reproducing the
   **frozen** fit additionally requires the spec's declared
   day-granularity mapping (`engine.period_observations`: tipoff = game
   date 00:00 UTC, observed_at = next day 00:00 UTC), not raw pull
   timestamps. This feed supplies the quarter values for the fit span
   (2014-15 sampled; §7) — it does not by itself re-derive or alter the
   published fit `NBA_PERIOD_FIT_V1:310b42f5bc41`, and any refit is a
   new version under a new preregistration. The standing caveat applies
   in full: seasons a construction was designed against are design
   data, never validation.
3. **Forward grading use (the §4.1 purpose).** The target game's
   quarter scores are **never inputs** — they do not exist before tip.
   The feed's forward roles are exactly two: (a) **grading labels** for
   rows priced pre-tip from DK captures, pulled after the game is
   final; (b) **in-season prior baselines** — the prereg draft's §5
   accuracy leg recomputes the B1/B2 climatologies on the same forward
   games, and the engine's sufficiency gates count prior in-season
   games — where only games **dated strictly before** the target game
   are consumed (the engine's `price_game` enforces this) and only
   after those games are final and pulled.
4. **Vintage discipline for forward use (binding).** One pull per game,
   after it is final, before its splits are consumed for a later game's
   priors or for grading its own rows; the operational form is a
   next-morning batch pull, the same discipline as the Torvik
   morning-of rule. A forward game with no pull is `NO_DATA` for period
   purposes — the engine refuses `NBA_PERIOD_HISTORY_UNAVAILABLE` —
   and a late pull is **visible in the data** (its real `observed_at`),
   never silently backfilled. If a re-pull ever shows a corrected
   linescore for an already-graded game, that is
   `SOURCE_CHANGED_AFTER_SNAPSHOT`: the graded record stands on its
   pinned vintage and the correction is surfaced, never overwritten.
5. **Not an in-play source.** Quarter splits of a game *in progress*
   are outside this admission entirely (see §8): nothing here feeds
   live pricing, and the puller's `NOT_FINAL` refusal is the mechanical
   enforcement.

## 7. Coverage statement

Verified-by-pull at sample strength (full-census pulls are the
consuming build's job, with per-game fail-closed refusals):

- **Span:** the route serves completed games from the **2014-15 season
  through the current 2026-27 season**, regular season **and**
  postseason — every era this family touches: the frozen fit span
  (seasons ≤ 2014-15), the calibration screen's span, and the forward
  population (2026-27 regular-season games on/after any future freeze).
- **Spot-verified seasons:** 2014-15 (two games, incl. the season's
  final day), 2020-21, 2025-26 (postseason), 2026-27 (incl. an overtime
  game). Scoreboard discovery additionally served the complete
  2015-04-15 and 2026-10-27 slates.
- **Known shape limits:** postponed games produce no observation (by
  design, §3); the payload's linescore entries in the summary document
  carry `displayValue` strings (the puller also accepts a numeric
  `value` where present and refuses anything non-integral).

## 8. What this admission does NOT do

- It does **not** freeze the period-lines preregistration, start a
  forward clock, or count any game. The freeze is the owner's separate
  act; until then the draft counts nothing.
- It does **not** satisfy data gate §4.2 (DraftKings period-section
  captures under the lane cadence) — rows cannot price until the
  capture grammar records the four period sections. That is separate
  lane work.
- It is **not a pricing input**: no target-game data exists pre-tip,
  and `not_admitted_scope` in the manifest bars pregame-pricing and
  in-play roles explicitly. It does **not** unblock the NBA **live
  pilot** (PR #2843's pilot spec needs an in-play feed under its own
  gates; a post-final outcomes feed is definitionally not one), NBA
  **game props** (their design has its own gates), or NBA **SGP**
  (its own gates — and player-prop legs remain under the NBA props V2
  quarantine regardless).
- It does **not** lift the NBA props V2 quarantine, admit ESPN for any
  other family's primary role, admit the NBA CDN or stats.nba.com for
  any role, or change any threshold, fit, or family state anywhere.
- Backtests or screens run on this data are **design evidence only**.
  Verification for this family accrues **forward only**, from admitted
  pregame captures, under its own (future, owner-frozen)
  preregistration. PAPER / research only: 0u, no staking, no wager
  execution.

## 9. License and terms

ESPN's data is ESPN's; no machine-readable license grant accompanies
the public API, and no redistribution right is granted or assumed.
Identical to the #2832/#2841 precedent: this repository stores
**hashes, manifests, and retrieval code only — no ESPN payload files
are committed** — and any derived artifact stays internal research
material. No republication of ESPN linescore tables on cards, posts, or
public artifacts beyond the five sample rows documented in §4 for
admission evidence.

## 10. Refusals

`SOURCE_UNAVAILABLE` (route probe/fetch fails or non-200),
`SCHEMA_INVALID` (payload shape is not the validated summary shape),
`IDENTITY_UNVERIFIED` (payload id ≠ requested event, or an unresolvable
team tricode at consumption), `NOT_FINAL` (game not final — splits
incomplete), `SCORE_MISMATCH` (linescore sums ≠ payload finals),
`SOURCE_CHANGED_AFTER_SNAPSHOT` (re-pull content differs from the
pinned sample). On the engine side, a game with no admitted observation
continues to refuse `NBA_PERIOD_HISTORY_UNAVAILABLE` (and
`NBA_PERIOD_FIT_HISTORY_MISSING` where the fit span is absent) —
unchanged by this record.

## 11. Owner / reviewer decisions still required

1. **Accept this admission** (merge of this PR after Rocky review). On
   acceptance, data gate §4.1 of the period-lines prereg draft is
   satisfiable and the period-lines forward build — wiring the engine
   to this feed and extending the DK capture grammar per §4.2 —
   becomes dispatchable.
2. **Separately, the owner's acts:** freezing the period-lines
   preregistration (or a successor) and commissioning the §4.2 capture
   extension. Neither is requested or effected by this record.
3. **Not requested:** any NBA CDN re-test (the route is refused from
   this runtime; a future record could re-test only if the runtime's
   network posture changes), and any Basketball-Reference role (its
   historical agreement is recorded as evidence about ESPN (the
   manifest's `cross_checks`) — not as a source role).
