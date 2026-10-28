# NHL RESTART READINESS PACK — 2026-10-27

Status: READINESS ASSESSMENT ONLY. Research-only, PAPER / 0u. This document
starts no clock, admits no source, changes no job configuration, and grants no
pricing or staking authority. NHL has **no verified engine**; nothing in this
pack changes that.

Trigger: the owner lifted the NHL pause on Oct 27, 2026 (~23:04 CT) by explicit
recorded decision ("Nothing is paused anymore") — the form the Oct 26, 2026
delegation required. Evidence below was verified firsthand on Oct 27, 2026
against the live registry, the live GitHub issues, and current `main`
(`318377dfa`): the intake parser on main was executed against real posted NHL
bodies, and the NHL test suites were run.

---

## 1. What the pause froze

### 1.1 Lines lane — registry state

`lane_intakes/registry.json` holds 48 entries, **10 of them NHL**, all from the
Oct 24–26, 2026 slates. No NHL entry exists after Oct 26 — the pause (owner,
Oct 25 ~11:51 CT) stopped all NHL reads/writes mid-slate.

| Issue | Game (CT) | Registry status | State on the record |
|---|---|---|---|
| #2609 | Minnesota @ Seattle, Oct 24 | started | Intake rejected the body at creation (`NHL_INTAKE_UNRECOGNIZED` on the `<!-- DK event -->` comment line). Registry note: "format conflict flagged for owner." Never reconciled. |
| #2610 | Detroit @ Calgary, Oct 24 | started | Same rejection class as #2609; same open flag. |
| #2624 | Florida @ Chicago, Oct 25 14:10 | started | Body corrected to the authoritative 11:41:54 CT verification read after the fabricated interim read was caught. |
| #2625 | NY Islanders @ Dallas, Oct 25 17:10 | started | Intake rejection comment at creation (comment-line defect); body later corrected to the authoritative read. |
| #2626 | Montreal @ Winnipeg, Oct 25 18:10 | started | Same as #2625. |
| #2627 | Colorado @ Nashville, Oct 25 19:10 | started | Same as #2625. |
| #2628 | Minnesota @ Vancouver, Oct 25 21:10 | started | Same as #2625. |
| #2714 | Los Angeles @ NY Rangers, Oct 26 18:10 | **pregame (stale)** | Intake rejected the PL line at creation (16:23Z): `NHL_INTAKE_UNRECOGNIZED: PL +1.5 -230 -1.5 +190`. No T-1H write, no FINAL write, `final_posted` unset — the game was played with the entry never advancing. |
| #2716 | Toronto @ Calgary, Oct 26 19:40 | **pregame (stale)** | **The stale issue.** Body updated twice on Oct 25; the intake bot rejected the PL line both times (16:51Z `PL -1.5 +170 +1.5 -205`; 17:06Z `PL -1.5 +164 +1.5 -198`) — "Couldn't read these lines, so no card was run." Never corrected under the pause. |
| #2717 | Detroit @ Edmonton, Oct 26 20:40 | **pregame (stale)** | Intake rejected the PL line at creation (16:51Z): `PL +1.5 -155 -1.5 +130`. No FINAL write. |

The three Oct 26 games' closing lines were never captured and cannot be
backfilled; they are missed closes, permanently, under the no-backfill law.

### 1.2 The parser defect — root cause, verified tonight

There were **two** distinct intake defects in the Oct 24–26 record:

1. **Comment-line defect (FIXED).** At creation, the intake bot rejected the
   `<!-- DK event: … -->` line itself (#2609, #2625–#2628). Current main's
   shared parser strips HTML comments before parsing (`issue_lines` in
   `sportsedge/pipeline/intake.py`); this no longer reproduces.
2. **Puck-line format defect (LIVE on main — restart blocker).** The lane posts
   the puck line with **both** lines and both prices:
   `PL -1.5 +136 +1.5 -162` (four numerics). The shared parser's SPREAD shape
   accepts only **three** numerics — one line plus two prices (its own test
   fixture, `tests/test_nhl_lines_intake.py`, uses `PL +1.5 -180 +150`).
   Tokenization keeps at most three trailing numerics, the leftover line value
   poisons the market-label match, and the row fails as
   `NHL_INTAKE_UNRECOGNIZED`. **Verified by execution tonight:** main's
   `parse_nhl_lines` rejects the live bodies of #2609, #2624, #2714, and #2716 —
   including #2624, whose body is the corrected authoritative read. The NHL
   intake unit tests pass (11/11 with the boxscore suite) because their
   fixtures use the parser's form, not the lane's posted form. As main stands,
   **no real NHL lines body the lane has ever posted can be priced.**

### 1.3 PR #2760 — what it did and did not repair

PR #2760 (merged Oct 26, 2026, during the pause): "NHL boxscore collector —
live Gamecenter shape repair (code only; capture remains PAUSED)." It repaired
`sportsedge/sports/nhl/official_boxscore_source.py` and
`scripts/collect_nhl_official_boxscores.py` against the current Gamecenter
payload shape, with fixtures and tests. That is the **results-data** surface —
the collector the public-baseline prereg (§1.4) depends on. It did **not** touch
the lines intake grammar; the §1.2 puck-line defect is a separate, still-open
repair.

### 1.4 Construction state — "NHL second attempt" (goal_35dd8536c895)

- **Attempt 1 verdict stands, unchanged:** NO EDGE. The forward-validation
  program record (`research/forward_validation_program_20261020/PROGRAM.md`)
  states the NHL backtest returned NO EDGE and the earlier positive result was
  shown to be look-ahead leakage; NHL was reaffirmed parked on Oct 20, 2026 on
  that basis. Under the no-resurrection law, attempt 1 stays retired.
- **Rate v1 artifact** (`artifacts/nhl/nhl_rate_v1_freeze.json`):
  `NHL_RATE_V1_OFFICIAL_STANDIN`, fit 2024-25 REG, validated on 2025-26 REG —
  a research owner only. Its totals path is the version that fits on final
  scores and adds OT/SO again; the v2 pre-lock (below) explicitly forbids
  quiet-fixing that double-count while keeping the validation label.
- **Rate v2 design** (`docs/research/nhl_home_ice_v2_prelock.md`, Sep 29,
  2026): regulation-only refit with home ice free, and a **one-shot validation
  window: 2026-27 REG, Oct 8 – Nov 30, 2026** — score ML / PL −1.5 / totals 5.5
  and 6.5 once, verdict on Nov 30, no second look. The pause froze execution,
  not the calendar: the window's games are accruing now, and the official
  boxscore collector (post-#2760) is the feed that makes the Nov 30 look
  possible. October numbers may be posted as a first read only; they do not
  pass, fail, or retune anything.
- **Public baseline** (`config/research/nhl_public_baseline_validation_prereg_v1.json`):
  `NHL_PUBLIC_BOXSCORE_BASELINE_V1`, status **FROZEN_BEFORE_IMPLEMENTATION**.
  The implementation exists (`sportsedge/sports/nhl/public_baseline.py`,
  `public_baseline_validation.py`, collector per the prereg contract), but
  **no validation verdict artifact is on record** (`artifacts/nhl/` holds only
  the rate v1 freeze). State: preregistered and built, verdict not yet run or
  not yet landed.
- **Attempt-2 foundation (per the goal record):** MoneyPuck shot-level xG and
  Hockey-Reference, under the standing source-admission discipline, slotted
  after CBB in the sport order. Neither is admitted yet (§3).

---

## 2. Restart checklist

Owners: **Rocky** (code/verification), **Lane** (capture delivery), **Isaac**
(owner-only acts). Nothing below was executed by this pack.

1. **[Rocky — BLOCKER] Fix the puck-line grammar mismatch (§1.2).**
   Recommended direction: teach the shared parser to accept the explicit
   both-lines PL form with a fail-closed mirror check (home line must equal
   −away line), because every historical NHL body uses that form; the
   alternative (lane switches to the 3-numeric form) is acceptable only if
   applied uniformly and re-verified. Either way, add a regression test whose
   fixture is a **real posted body** (e.g. #2716's), not a hand-shaped one.
   Acceptance: `parse_nhl_lines` accepts the live bodies of #2609/#2624/#2714/
   #2716 verbatim, and the NHL intake suite stays green.
2. **[Lane] Re-verify the DK NHL board in the browser.** Repo evidence for the
   board's shape ends Oct 26; the pause lasted two days and DK page formats
   drift. The first capture run must confirm the detailed board read still
   renders and that the comment-block structure matches what the lane's
   grammar posts. (Browser work — cannot be discharged from repo evidence.)
3. **[Lane/Rocky] Registry hygiene for the frozen tail.** Move #2714/#2716/
   #2717 from `pregame` to started/closed with a note that their T-1H/FINAL
   writes and closes were missed under the pause — record the miss, never
   fabricate the writes. The #2609/#2610 "format conflict flagged for owner"
   notes are superseded by checklist item 1.
4. **[Rocky] Close out the stale issues.** Post one restart note on each of
   #2714, #2716, #2717 stating: the lines on file were never intake-readable,
   no card ran on them, the games are final, and the grammar repair reference.
   Historical bodies stay as written; no retroactive line edits.
5. **[Lane] First-slate shakedown (delivery acceptance, §2792 terms).**
   First NHL slate after items 1–3: one capture task per due game, dispatched
   in parallel; T-1H create inside the 75–45 min window; FINAL on the first
   run inside 20 min; bodies only from detailed verified board reads; the five
   §6B timestamps (dispatch, source capture, ingestion, durable write, card
   delivery) recorded per game. **Round-trip gate:** the first body of the
   slate must pass `parse_nhl_lines` with zero `UNRECOGNIZED` rejections
   before the rest are posted. Any failure stops the slate, not just the game.
6. **[Rocky] Restart official-data collection for the v2 window.** Run the
   post-#2760 boxscore collector across Oct 8, 2026 → present so the Nov 30
   one-shot validation look (§1.4) has its data; then run the public-baseline
   validation exactly as its frozen prereg specifies and record the verdict.
   No interim v2 verdicts before Nov 30.
7. **[Isaac] Nothing is required from the owner to restart captures.** The
   pause lift is already recorded. Owner-only items remain his alone when
   they arise (e.g. any Threads publish taps, per standing rule).

---

## 3. Data state — admitted, wired, and missing

### 3.1 NHL official API (api-web.nhle.com) — ADMITTED, research/archive only

The one NHL source with a completed admission on record
(`docs/nhl_api_research_source_20261024.md`, live probe Oct 24, 2026):
standings verified back to 2000-04-08, club stats back to season 20102011,
14/14 final scores cross-checked exactly against ESPN, no key, no rate limit
encountered. The collector (`scripts/collect_nhl_api.py`) is registered with
`pricing_input: false` / `play_eligible: false` envelopes — it feeds archives,
never pricing. Official Gamecenter surfaces are wired in-tree with fail-closed
receipt contracts and tests: boxscore, play-by-play, roster, and role sources
(`sportsedge/sports/nhl/official_*_source.py`), plus the final-scores capture
(`scripts/capture_nhl_final_scores.py`). Known semantic caveat, recorded at
admission: official standings goals-against counts the shootout-deciding goal;
shot-derived sources (MoneyPuck) do not — expect ±1 GA per shootout loss when
joining the two.

### 3.2 Owner-supplied sources (supplied Oct 27, 2026) — assessed tonight

The owner named three sources for the attempt-2 foundation. Repo state and
live-endpoint verification for each:

**MoneyPuck — NOT admitted, NOT wired. Live files verified; this is the
attempt-2 xG foundation and the admission is owed.**
- *In repo today:* mentions only. The pull inventory
  (`docs/research/five_sport_pull_inventory.md`) lists "MoneyPuck free files
  (index reachable)" as **CONTEXT**; the NHL API admission doc cites it for
  the GA definitional difference (§3.1); a social-analytics registry entry
  tracks its X handle. There is **no MoneyPuck collector, fetcher, or data
  file anywhere in the tree**, and rate v1 ran on a GF/GA/SOG stand-in
  precisely because xG was never wired.
- *Live verification (Oct 27, 2026, from this runtime):* the download surface
  is real and current. Verified endpoints: per-season summary zips for
  skaters / lines / goalies at
  `peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/{skaters|lines|goalies}/{season}.zip`
  (2008–2026), one-row-per-season archives (`…/historicalOneRowPerSeason/…`,
  through 2024), the full shot database
  (`…/downloads/shots_{season}.zip`, plus `shots_2007-2025.zip`), per-player
  career files (`moneypuck.com/moneypuck/playerData/careers/{gameByGame|perSeason}/regular/{skaters|goalies}/{playerId}.csv`),
  and the game-by-game all-teams file
  (`moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv`).
  Freshness: `all_teams.csv` carries `Last-Modified: Tue, 27 Oct 2026
  10:59:28 GMT` — regenerated today; the 2026 skater zip contains the
  in-progress 2026-27 season. MoneyPuck's xG model itself was rebuilt for
  2026-27 (their about page: gradient boosting, trained on 2023-24 → 2025-26
  shots, AUC ~0.807 vs ~0.784 for the old model) — **a model change inside
  the source**: xG values are not one consistent series across the rebuild,
  and any admission must pin which model vintage a file carries.
- *Machine-readability:* excellent — plain CSV / zip-of-CSV over static
  HTTPS, no key, no JS. The earlier in-repo guess at a `seasonSummary/`
  URL pattern 404s; the `peter-tanner.com` paths above are the live ones,
  taken from the site's own data page tonight.
- *Point-in-time safety:* **season-summary and game-by-game files are
  cumulative snapshots, rewritten in place** — a file pulled today states
  season-to-date numbers as of today, with no as-of archive. They are safe
  as construction inputs only under walk-forward discipline (a feature for
  a game on date D must come from a snapshot pulled before D, or from the
  game-by-game rows for games strictly before D — the game-by-game files
  carry `gameDate`/`gameId`, so a strictly-prior filter is mechanically
  enforceable) and every pull used for design must be hash-pinned at pull
  time, exactly like the CBB substrate pins. Retroactive PIT claims are
  forbidden, per the standing baseline contract.
- *Hash-pinned sample pulls (Oct 27, 2026):*
  - `seasonPlayersSummary/skaters/2026.zip` — 3,447,478 bytes, sha256
    `bd16f2ddef3dd62f082aef061feb49d891d3303042de959b00f4ad3ffb4a1a79`;
    contains `2026.csv`, 33,656 rows of game-by-game skater data for the
    in-progress season (playerId, gameId, gameDate, situation splits,
    on-ice xG% / Corsi% families).
  - `MoneyPuckDataDictionaryForPlayers.csv` — 15,040 bytes, sha256
    `74c5a09f5eb5e12c03838c9efea0a84d9b33024193a1a29b9c67d998f5324a91`.
  - `careers/gameByGame/all_teams.csv` — 127,505,574 bytes, sha256
    `3ac5ed95fbf072166ea59d2cf4e44a37e337e8c2122ba5f2fa55e56ec3cef1ab`
    (hash verified identical across two computations on the completed
    file); 234,090 game-by-game team rows, seasons 2008 → 2026 (1,870 rows
    for the in-progress 2026-27 season), 111 columns (`gameId`, `gameDate`,
    situation splits, xG/Corsi families). Sample files were pulled for
    verification only and are not committed; the pins above are the record.

**Natural Stat Trick — NOT in the repo at all. Not machine-admissible from
this runtime tonight.**
- *In repo today:* **zero references** — no doc, no collector, no mention.
- *Live verification:* the site is live (`naturalstattrick.com` 301 →
  `www.naturalstattrick.com`) and its report pages (e.g. `teamtable.php`
  with season/situation parameters) are the canonical possession/xG tables
  with a CSV-export feature for browser users. However, **automated fetches
  from this runtime returned HTTP 403 (bot protection) by two independent
  routes** (direct HTTP and the text-fetch service). No sample pull could be
  taken and none is claimed.
- *Assessment:* NST's value (shift-level possession, scoring chances, xG by
  situation) largely overlaps MoneyPuck's files for construction purposes.
  Until a pull path exists that respects the site's access controls (a
  browser-mediated manual export is the owner's or lane's to perform, not
  something to circumvent), NST is **documented-only context** — it cannot
  be a pinned construction input. Do not scrape around the 403.

**Hockey-Reference — NOT in the repo at all. HTML-only; the goal record names
it, nothing is wired.**
- *In repo today:* **zero references** (the attempt-2 goal document names
  Hockey-Reference as foundation; no code or doc in the tree implements it).
- *Live verification:* team season pages fetch successfully from this
  runtime (HTTP 200, full HTML tables — e.g. a 2026 team page, ~686 KB).
  There is no free CSV/API surface: the data is HTML tables, and the site's
  `robots.txt` disallows several path families for all agents
  (`/play-index/*cgi`, `*/gamelog/`, `*/splits/`, boxscore index, search).
  Sports Reference's structured product (Stathead) is paid.
- *Assessment:* usable as a **cross-check / context** source via individual
  page reads within the site's stated access rules — the same role ESPN
  pages play elsewhere in the program. As a bulk construction input it is
  the weakest of the three: no pinnable files, parsing fragility, and terms
  that do not bless bulk collection. If attempt 2 needs historical
  standings/scoring context, the NHL official API (§3.1, already admitted)
  covers most of it with a better provenance story.

### 3.3 The remaining gaps for a future construction

1. **MoneyPuck admission + collector (the named blocker).** Attempt 2's
   design foundation is MoneyPuck shot-level xG, and tonight it is a
   verified-live source with zero admission paperwork and zero wiring.
   The admission must record: the endpoint set above, the in-place-rewrite
   snapshot semantics and the strictly-prior / hash-pin discipline, the
   2026-27 xG model rebuild (vintage pinning), and the GA definitional
   difference vs the official API. Then a collector in the
   `collect_nhl_api.py` pattern (research envelopes, fail-closed).
2. **Starting-goalie confirmation** remains context-grade: official
   box/roster first, Daily Faceoff as context only (pull inventory). No
   admitted PIT goalie source exists — the same evidence class as every
   other sport's availability problem.
3. **Historical closes.** Issue #2604 (`[DATA] NHL historical closes`) is
   still OPEN with no landed archive: there is no timestamped historical
   NHL line archive in the program, the same G-class gap as the other
   sports. Forward DK capture (checklist §2) is the baseline; nothing
   backfills it.
4. **No construction exists to feed yet.** Even with §3.3.1 landed, NHL is
   NO_CONSTRUCTION for attempt-2 purposes until a design is written under
   preregistration: attempt 1 is retired (NO EDGE, leakage), rate v2's
   one-shot window (§1.4) is the only live validation design, and the
   public baseline still owes its verdict. Data work does not change any
   of those labels.

---

*End of pack. Prepared Oct 27, 2026 (America/Chicago) for the restart
decision record. Companion actions live in the §2 checklist; this document
itself performs none of them.*

