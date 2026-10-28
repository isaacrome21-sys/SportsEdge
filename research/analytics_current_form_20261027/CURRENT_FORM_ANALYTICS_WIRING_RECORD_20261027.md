# Current-Form Analytics — Wiring Record (2026-10-27)

Owner directive (Isaac, Oct 27, 2026, evening): sources like KenPom,
StatMuse, Basketball Monster, and Next Gen Stats "should be wired and
factoring our bets" — current-form analytics feeding TODAY's pricing
research. A follow-up owner-supplied list added NFL Savant,
Pro-Football-Reference, Sharp Football Analysis, Basketball-Reference,
NBA.com/stats, nbarapm.com, databallr.com, Dunks & Threes, and Spotrac.

Status key: **WIRED** = a fetcher in `sportsedge/current_form/` pulls it
today, fail-closed, with a stamped receipt. **ALREADY WIRED** = a
pre-existing repo module owns it. **SIBLING** = owned by a parallel
workstream's PR; referenced, not duplicated. **DOCUMENTED-ONLY** = a
real research surface for human/owner use; no fetcher, for the stated
reason. **BLOCKED** = not reachable from this environment without an
account, a payment, or evasion — never bypassed.

Hard boundary for everything below: these are **research-layer
inputs**. Nothing in this record or in `sportsedge/current_form/`
changes a model, a frozen evaluator, a threshold, a verified status,
or PLAY eligibility. Card use is governed by
`CURRENT_FORM_FACTORING_SPEC_20261027.md` in this directory. Every
sample pull cited here is pinned (URL, bytes, sha256) in
`sample_pull_manifest_20261027.json` — one manual pull per source,
2026-10-27 evening, America/Chicago.

## NFL

### Next Gen Stats — WIRED
- Path: nflverse-data GitHub release `nextgen_stats`, consolidated
  `ngs_{passing,rushing,receiving}.csv.gz` (the files
  `nflreadr::load_nextgen_stats()` reads). NFL's own NGS site is a JS
  app; nflverse is the machine-readable free path. No key/account.
- Fetcher: `sportsedge/current_form/nflverse_ngs.py`.
- Live verification: passing file sha256
  `6341543f…a96c54`, seasons through 2026, 2026 REG through week 7
  (last completed week at pull time); release assets refreshed
  2026-10-27. Fields used: CPOE, time to throw, intended air yards,
  air yards to sticks, aggressiveness, passer rating; RYOE/att, rush %
  over expected, efficiency, 8+ box %; separation, cushion, YAC above
  expectation, air-yards share, catch %.
- Point-in-time: rows are week-stamped; week 0 is a season-aggregate
  row and is always excluded; callers pass `through_week` = last
  completed week; the fetcher refuses a through_week beyond the file's
  actual max week. Latency: weekly, posted after each week's games.
- Terms: nflverse data is public; NGS itself is NFL's published stats
  product, redistributed by nflverse for analysis use.

### EPA/play, snap counts, target shares (nflverse PBP family) — WIRED
- Paths: release `pbp` (`play_by_play_<season>.csv.gz`, ~7MB gz for
  2026), release `snap_counts` (`snap_counts_<season>.csv`), release
  `stats_player` (`stats_player_week_<season>.csv`). No key/account.
- Fetcher: `sportsedge/current_form/nflverse_usage_epa.py`
  (`team_epa_form`, `snap_share_form`, `target_share_form`).
- Live verification: pbp 2026 sha256 `30f31f1f…70396` (max week 7);
  snap counts sha256 `0994bd2c…0d4098`; weekly player stats sha256
  `c5b3b92a…1174`.
- Point-in-time: same week-cutoff discipline as NGS. EPA is computed
  from plays in completed weeks only.

### NFL Savant — DOCUMENTED-ONLY (research surface)
- nflsavant.com home is a 3,832-byte JS shell (sha256 `0b471a3b…5463`).
  Per the owner's own note, its data is nflverse PBP underneath —
  already pinned and wired above — so NFL Savant adds a browsing /
  visualization surface, not a dataset. No fetcher: nothing new to
  fetch, and its tables are rendered client-side.

### Pro-Football-Reference — WIRED (HTML tables, bot-policy discipline)
- No CSV/JSON endpoint exists; pages are server-rendered HTML tables.
  2026 season page: 534,802 bytes, 11 tables incl. `team_stats`,
  sha256 `73fe6f5c…8ef9d`.
- Fetcher: `sportsedge/current_form/sports_reference.py`
  (`pfr_team_stats`) — one page per call, named table by id.
- Sports Reference publishes a bot policy (automated requests capped
  at 10/minute; this layer's intended use is a handful of single pulls
  per day). Any 403/429 fails closed; retries/evasion are prohibited
  by the module's own rules — a block demotes the surface to
  browse-only.
- Point-in-time: season-to-date as of pull, no source as-of stamp;
  receipt stamps retrieval time + sha256; pre-game archived pulls only
  (factoring spec).

### Sharp Football Analysis — DOCUMENTED-ONLY (research surface)
- Free advanced team stats live under
  sharpfootballanalysis.com/stats-nfl/ (hub sha256 `7635d06a…5568`)
  as interactive tool pages (pass rate over expected, coverage
  schemes, personnel, defensive tendencies, etc.), updated weekly.
  sharpfootballstats.com is a parked/redirect stub (114 bytes).
- No stable machine-readable endpoint was verified tonight, and the
  headline metrics (EPA, success rate, PROE) duplicate the nflverse
  PBP wiring above. Documented as an owner/lane browsing surface for
  tendency context; no fetcher.

## NBA

### Basketball-Reference — WIRED (HTML tables, bot-policy discipline)
- 2026-27 per-game page: 1,061,985 bytes, `per_game_stats` table
  server-rendered, sha256 `4664a1d5…2de34`.
- Fetcher: `sportsedge/current_form/sports_reference.py`
  (`bbr_per_game`). Same Sports Reference bot-policy discipline as
  PFR. Rows pass through as published (per player-team stint; the
  source's own combined rows are never silently merged).
- Point-in-time: season-to-date as of pull; stamped receipts;
  pre-game archived pulls only.

### NBA.com/stats + NBA CDN — BLOCKED from this environment
- stats.nba.com league-leaders endpoint with the usual browser
  headers: connection timed out, 0 bytes received. cdn.nba.com static
  scoreboard JSON: HTTP 403 (459-byte block page, sha256
  `9b86df2f…291` recorded for the block page, not data).
- This matches repo history: the NBA CDN was Candidate A in the V2
  source-admission work and closed NOT ADMITTED after a 403
  availability failure. Recorded here as a known surface that is not
  machine-reachable from this environment; no fetcher, no evasion.
  Owner browsing of nba.com/stats is unaffected.

### Impact metrics: RAPM / DARKO / LEBRON / EPM — DOCUMENTED-ONLY
These four are season-blend, model-fitted impact estimates. They are
**current-form inputs, never as-of archives**: a value read today
already blends today's games and is re-fit as new games arrive, so it
must never be backfilled into a past date's context (that is leakage)
and never described as "the rating as of" any earlier day. The
factoring spec gives them browse-fed info-pack fields with pull-date
stamps and a 7-day staleness limit.

- **nbarapm.com (RAPM)** — home is a Next.js (turbopack) app,
  313,521 bytes, sha256 `abef3919…f5bd`; RAPM values live in the
  client payload; no stable CSV/endpoint verified tonight.
  Browse-only research surface.
- **databallr.com (DARKO)** — SPA shell (14,103 bytes, `#root`,
  sha256 `734ec951…6d51`); the DARKO app is client-side. Browse-only.
  (LEBRON, BBall-Index's metric, is likewise a web surface in this
  family — documented with databallr per the owner's grouping; no
  machine-readable free endpoint verified.)
- **Dunks & Threes (EPM)** — the leaderboard lives at
  dunksandthrees.com/epm (note: /epm-leaderboard is a 404). The page
  is publicly served (1,471,193 bytes, sha256 `8448a4cb…eb1`) with
  leaderboard content in the page payload, but no stable documented
  machine format was verified tonight; classified browse-only rather
  than scraping an app payload whose shape can change silently.

### ESPN public JSON — WIRED (BPI: DOCUMENTED-ONLY)
- site.api.espn.com v2 scoreboard/teams/standings JSON, publicly
  served, no key. Fetcher: `sportsedge/current_form/espn_public.py`;
  team form is computed from completed events with an explicit as-of
  cutoff. NBA scoreboard sample sha256 `01b55e13…5bc403`.
- BPI / power index: five candidate public endpoints probed
  (fittwo v3 `powerindex` on site.api and site.web.api for NBA and
  CBB; site v2 `/bpi`) — all 404. BPI is a public web page, not a
  verified feed; documented-only, no invented endpoint.

### StatMuse — DOCUMENTED-ONLY
- Public ask pages answer in natural language; the answer sentence is
  carried in the page's `og:description` (probe: "Luka Dončić has put
  up 36.6 points per game in his last 10 games", page sha256
  `8ebc8aa1…876a`). robots.txt does not disallow ask pages. But a
  sentence in page metadata is not a data feed: no structured fields,
  no as-of stamp, unknown rate limits. Classified as a human-checked
  cross-reference surface — the factoring spec gives it exactly one
  field (a human-verified cross-check note), and no fetcher pretends
  an API exists.

## CBB

### BartTorvik — SIBLING (team ratings) + WIRED (player advanced stats)
- Team ratings (T-Rank) admission, incl. the morning-of as-of rule,
  is owned by the sibling CBB workstream: draft PR #2832 (archive
  admission record, DESIGN only) and #2835 (hoopR substrate). This
  record references them and does not duplicate the admission.
- The distinct artifact this layer needs — Torvik's public player
  advanced-stats CSV (`getadvstats.php?year=<season>&csv=1`) — is
  WIRED: `sportsedge/current_form/torvik_current.py`. Live pull:
  year=2027 label, 3,231 player rows, sha256 `53f43e89…3cc5d`.
  Headerless fixed-order CSV; parser is positional over the leading
  documented columns with a strict field-count drift guard.
- Honest season note: pulled 2026-10-27, before the 2026-27 season
  starts, the endpoint serves the player pool with prior-season
  performance rows. Consumers read GP values, not the label.
- Illinois college exclusion (standing owner rule) applies at the
  consumer layer; the fetcher never silently drops rows.

### KenPom — DOCUMENTED-ONLY (owner subscription decision)
- Exactly what the free surface gives (verified by pull, 2026-10-27):
  the kenpom.com homepage serves the FULL current Pomeroy ratings
  table without login — every D-I team (361 team links), with NetRtg,
  ORtg, DRtg, AdjT, Luck and beginning-of-season SOS columns; archive
  seasons via `index.php?y=<year>` also returned 200 with full tables.
  Homepage sample: 361,567 bytes, sha256 `67ac8270…876a`.
- What it does NOT give free: team pages, player stats, FanMatch,
  game predictions and the rest of the subscriber surfaces — the full
  dataset needs the owner's paid subscription (per the program's
  standing rule, KenPom is NOT ADMITTED without it).
- robots.txt: `Allow: /` for general agents with content signals
  `search=yes, ai-train=no, use=reference`. Our use would be human
  reference, never model training; even so, no automated fetcher is
  built against a subscription business's free homepage. Treatment:
  owner-manual reference field in the factoring spec; whether to buy
  the subscription is the owner's call, listed in the report-back.

## MLB

### Statcast (pitch-level) — ALREADY WIRED (pre-existing)
- `sportsedge/mlb_savant_features.py` owns pitch-level Statcast via
  the keyless statcast_search CSV (with its documented 25,000-row cap
  fail-close), plus `scripts/collect_statcast_research.py` and
  `scripts/refresh_statcast_daily.py`. Not duplicated here.

### Baseball Savant leaderboards — WIRED
- Leaderboard pages serve CSV twins via `?csv=true`. Wired surface:
  Expected Statistics (batter + pitcher) — expected-minus-actual
  gaps (est_woba − woba etc.) as the current-form signal.
  Fetcher: `sportsedge/current_form/savant_leaderboards.py`.
- Live verification: batters sha256 `6e261fb9…32803`; pitchers
  sha256 `cf503494…6232`; custom-leaderboard base pattern also
  verified (sha256 `29bd051e…66b5`).
- Point-in-time: season-to-date as of pull, no source as-of stamp;
  receipt stamps retrieval; post-first-pitch pulls may not be used
  for that game (factoring spec).

## Cross-sport

### Spotrac — BLOCKED for automation (browse-only for owner)
- spotrac.com/nba/ returned HTTP 403 (bot protection) from this
  environment; sample is the block page (sha256 `ea46fe68…596a`).
  No evasion. Contract context (e.g., contract-year status) is an
  owner-browsed research surface only, entered manually with
  attribution if used at all.

### Basketball Monster — BLOCKED for machine use
- playerrankings.aspx returns a 530,491-byte HTML shell with no
  server-rendered data table (exactly 1 `<tr>` element) and a login
  surface; per-game stats are an interactive/account product.
  Sample sha256 `5b587a5a…f5bd`. No fetcher; owner's own browsing is
  unaffected. (Its fantasy per-game value rankings are also the wrong
  shape for this layer: category-value ranks, not current-form
  performance lines — BBR per-game above covers the need.)

## Point-in-time safety — the layer's standing rules

1. Every wired pull is stamped (URL, retrieval UTC, sha256, bytes);
   the stamp travels with the data into the card block.
2. Week/window-stamped sources (nflverse family) are cut at the last
   completed week before the game — enforced in code, with a
   beyond-file refusal.
3. Season-to-date surfaces (Sports Reference, Savant, Torvik, ESPN)
   carry no source as-of: they may only be pulled and archived
   pre-game; a pull after first pitch/tip cannot serve that game.
4. Season-blend impact metrics (RAPM/DARKO/LEBRON/EPM) are never
   as-of values and never backfilled; pull-date stamped, 7-day
   staleness limit at tip.
5. A failed or blocked pull yields status MISSING with a reason
   code. It never yields a stale value dressed as fresh, and it
   never raises into a pricing path.

## Addendum — real-data parser validation (2026-10-27, same evening)

Every fetcher was run against the actual pinned sample pulls above
(not only unit fixtures). Results:

- NGS passing: OK — 45 QBs, file max week 7 enforced.
- Snap counts: OK — 1,908 players.
- Weekly player stats: OK — 1,688 players. **Schema lesson:** the
  current nflverse weekly file names its team column `team` (not the
  older `recent_team`); the fetcher pins `team`.
- PBP EPA: OK — 32 teams, pass/rush splits and success rates.
- Savant expected statistics: OK — 246 qualified batters.
- Torvik player CSV: OK — 3,231 players parsed positionally.
- Basketball-Reference: OK — 412 player rows. **Schema lesson:**
  current data-stat keys are `name_display` and `team_name_abbr`
  (older `player`/`team_id` kept as fallbacks).
- Pro-Football-Reference: OK — exactly 32 teams. **Schema lessons:**
  the `team_stats` table is served wrapped in an HTML comment (the
  fetcher slices the table's own markup from the served bytes; no
  extra requests) and carries a grouping over-header above the real
  column header (the extractor selects the modal-length,
  data-stat-carrying header row); the `Avg Tm/G` footer row is
  excluded by name.
- ESPN scoreboard form: OK — the Oct 27, 2026 finals resolve to the
  correct winners/margins.

Unit suite: `tests/test_current_form_fetchers.py` (11 tests, offline
fixtures) passes; ruff gate E9,F821,F822,F823,F811 clean; no new
dependencies (stdlib only), so dependency parity is untouched.
