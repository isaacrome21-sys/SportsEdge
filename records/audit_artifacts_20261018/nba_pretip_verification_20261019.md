# NBA opening-night pre-tip verification — Mon Oct 19, 2026 (~17:00 CT run)

One-off check for Tue Oct 20, 2026 opening night. Research only; no card issued, no RUN IT run.
Code state tested: **origin/main 07b46d38334453bac76ceecd017c593452384b5b** (fresh detached worktree `/tmp/nba_pretip_wt`).

## Verdict (one line)

The NBA game-market path **works end to end and terminates in correctly labeled states** for all three
opening-night games. No intake/binding/pricing code defect was found. The published-card layer is
**BLOCKED — FAMILY_REGISTRY_NOT_VALIDATED (NO_VALIDATION)** by design, team totals and player props are
**NO_ENGINE / unregistered**. The DraftKings route is **intermittent**: this morning's browser attempts
and a direct API probe from the shell both hit 403, but the live browser board **rendered successfully
at 5:02 PM CT** with all three games priced (see §5, corrected on the browser agent's return) — the
smoke test ran on both the verified manual capture (fallback) and the live browser-observed lines.

## 1. Fixtures (ESPN, live) + DK native boards

ESPN scoreboard `dates=20261020` (HTTP 200, fetched Oct 19 ~17:00 CT; raw file `espn_scoreboard_20261020.json`):
exactly 3 events, all `STATUS_SCHEDULED`:

| ESPN event | Matchup | Tip (UTC) | Tip (ET / CT) |
|---|---|---|---|
| 401909088 | Boston Celtics at Detroit Pistons | 2026-10-20T19:00Z | 3:00 PM / 2:00 PM |
| 401909089 | Philadelphia 76ers at New York Knicks | 2026-10-20T23:00Z | 7:00 PM / 6:00 PM |
| 401909090 | Oklahoma City Thunder at San Antonio Spurs | 2026-10-21T01:30Z | 9:30 PM / 8:30 PM |

All three match the task slate exactly — **CONFIRMED**. ESPN scoreboard for Oct 19 returns 0 events (no games today).
`NBASource.resolve_fixture` (registry-verified source on current main) resolved each fixture uniquely by
full team name + tipoff — PASS ×3.

DraftKings native boards for all three: **CONFIRMED POSTED** via the verified manual capture
(`~/workspace/sportsedge/dk_line_archive/nba/2026-10-19/1154_ct.json`, MANUAL_CAPTURE_OWNER_DIRECTED,
window 11:54:30 AM–12:13:46 PM CT, signed-out Illinois view) — every game carries moneyline, spread and
total (lines in §2). The failed scheduled capture (`1053_ct.json`, CAPTURE_FAILED, 0 rows) stands as a
separate record and is not backfilled by the manual file.

## 2. Smoke test — DK capture → intake binding → pricing (fallback intake: manual capture)

Live-route attempt first: see §5 (ROUTE defect). Fallback intake = manual capture, converted losslessly
to the canonical lines format; `parse_lines` output was asserted field-for-field against the capture
(both prices, both lines, all three markets) — **exact match ×3 games**.

| Game | DK ML (away/home) | DK spread | DK total | Intake | lines_card pricing (internal) | Registry-gate end state |
|---|---|---|---|---|---|---|
| BOS @ DET | −112 / −108 | BOS −1.5 (+100) / DET +1.5 (−120) | 222.5 (−105/−115) | PASS | 6 rows, LEAN/PASS only, prob pairs sum to 1 | BLOCKED · NO_VALIDATION |
| PHI @ NYK | +154 / −185 | PHI +4.5 (−105) / NYK −4.5 (−115) | 231.5 (−112/−108) | PASS | 6 rows, PASS only, prob pairs sum to 1 | BLOCKED · NO_VALIDATION |
| OKC @ SAS | +114 / −135 | OKC +2.5 (−112) / SAS −2.5 (−108) | 231.5 (−112/−108) | PASS | 6 rows, LEAN/PASS only, prob pairs sum to 1 | BLOCKED · NO_VALIDATION |

Pricing layers exercised (all on origin/main 07b46d383):

- **`lines_card.price_game`** — `VALIDATED_MARKETS = ()`, so no row can be labeled BET; positive-EV rows
  are LEAN, rest PASS. Internal-only: the canonical runner stamps the registry gate over this (below).
  (Mechanics run used league-average prior ratings; production ratings come from the runner, next bullet.)
- **Canonical runner end to end** — `scripts/run_nba_lines_issue.py` with the three games as body,
  observed 2026-10-19T12:13:46-05:00: fetched **1,322 completed ESPN games (2025-10-21 → 2026-06-14,
  all 30 teams, 0 fetch errors)**, replayed ratings, priced, and emitted exactly:
  `NBA REGISTRY BLOCKED … FAMILY_REGISTRY_NOT_VALIDATED. Research-only; no prices, probabilities or EV
  are published…` — exit 0, no intake error. **This is the correct honest end state for a published card.**
- **Verified pricing path** — `nba_game_market_pricing.fit_verified_games` on 54 real ESPN completed
  games (Apr 5–10, 2026 scoreboards, registry-verified team IDs): σ_margin 18.23, σ_total 22.74;
  `price_game_markets` + `spread_probability` / `total_probability` produced finite, non-degenerate
  probabilities for all three fixtures at their DK lines (e.g. BOS@DET pred margin DET +2.76, pred total
  218.6, ML home p 0.560). Small fit sample = smoke test of the path, not a production rating.
- **Binding** — `binding.bind_quote`: a quote bound 120 s after capture binds (EV/score computed);
  the same quote bound at Oct 19 17:00 CT is refused `ValueError: stale sportsbook quote` (300 s max age).
  Fail-closed as designed — see Must-fix #1 for the operational consequence.
- **Fail-closed intake (negative tests)** — one-sided ML → `NBA_ONE_SIDED_OR_MALFORMED`; team-total line →
  `NBA_UNRECOGNIZED` (no intake format exists); unknown team → `NBA_UNKNOWN_TEAM`; game without markets →
  `NBA_GAME_WITHOUT_MARKETS`; malformed total → `NBA_LINE_INVALID`. All refused with named reasons.
- **Test suites on exact head** — `test_nba_lines_card`, `test_nba_game_market_pricing`,
  `test_nba_espn_verified_source`, `test_nba_market_capabilities`, `test_nba_binding`, `test_nba_run_it`,
  `test_nba_ratings_model`: **50 passed**. Registry-gate suites (`family_registry_stopgap`,
  `t134_family_gate_wiring`, `runtime_registry_enforcement`, `t132_family_registry_bypass_probes`):
  **132 passed**.

Named blockers per family (current main, both layers agree nothing is validated):

- Game ML / spread / total — registry: `BLOCKED / NO_VALIDATION / FAMILY_REGISTRY_NOT_VALIDATED`;
  capability contract: `REQUIRES_ENGINE`. Engine exists and prices internally; **no validated family**.
- Team totals — registry: `BLOCKED / NO_ENGINE / FAMILY_MARKET_UNREGISTERED`; also **no DK team-total
  rows on the league board** in the manual capture (`team_totals: null` ×14 games).
- Player props — registry: `NO_ENGINE / FAMILY_MARKET_UNREGISTERED`; capability: `REQUIRES_ENGINE`
  (FIRST_BASKET / DOUBLE_DOUBLE / TRIPLE_DOUBLE: `NO_ENGINE`). **Props stay NOT_WIRED** (§4).

Abbreviation trap (recorded, NOT a wired defect): DK/lines_card abbreviations (SAS, NYK, GSW, NOP, UTA,
WAS) differ from the ESPN registry abbreviations (SA, NY, GS, NO, UTAH, WSH). Binding the verified path
by raw DK abbreviation fails closed (`NBA_TEAM_ABBR_NOT_IN_VERIFIED_REGISTRY:SAS`, etc.); the correct
keys are ESPN team IDs / display names, and the results-fetch path translates via `lines_card.team_abbr`
aliases. `team_by_abbreviation` has no production caller on main, so nothing mis-binds today — but any
future DK-capture binder must map through IDs/names, never raw abbreviation strings.

## 3. Official NBA injury report (PIT-honest availability source)

Route **VERIFIED WORKING**: historical control `Injury-Report_2025-10-21_07PM.pdf` → HTTP 200,
`application/pdf`, 74,295 bytes, 5 pages (saved here as `injury_2025-10-21_07PM.pdf`); the 2025-10-21
11AM/12PM/01PM/02PM/05PM/07PM/08PM slots all return 200.

Opening night: **NOT YET AVAILABLE at check time.** Every probed slot for 2026-10-19 (11AM–08PM) and
2026-10-20 (11AM, 12PM, 01PM, 02PM, 05PM, 07PM, 08PM) returned HTTP 403 (Akamai XML error body, 243–263
bytes) on both HEAD and GET — the same signature the Oct 12 probe saw for unpublished/preseason dates.
This does **not** prove the reports will not exist; it proves none was retrievable at Oct 19 ~17:00 CT.
Recheck on Oct 20 (see Must-fix #2).

Secondary signal only — ESPN injuries feed (HTTP 200, feed timestamp 2026-10-19T22:00:56Z, 27 teams with
entries; raw file `espn_injuries_20261019.json`): BOS — Devin Carter Out; DET — no entry in feed;
PHI — Wade / Bona / Simons Day-To-Day (questionable per comments, Oct 19 21:1xZ updates), Fall / Barlow /
Hukporti Out; NYK — Josh Hart Day-To-Day; OKC — 6 entries (Wallace / Sorber / J. Williams / Topic /
Holmgren Day-To-Day, mostly preseason-game notes dated Oct 15–16; Oweh Out for season); SAS — Tobias
Harris Out, Quaintance Out. Editorial vocabulary (Day-To-Day ≠ official Questionable) — **not** used as
pregame availability truth, per the probe rules. Summary-payload injuries/starters were not used.

## 4. DraftKings player-prop boards for opening night (recorded, not built)

**YES — DK posts full prop boards for all three opening-night games** (manual capture, points / rebounds /
assists / PRA; threes, steals, blocks, turnovers, double-double were out of the capture's scope):

- BOS @ DET: **47 prop rows** (13 PTS / 13 REB / 10 AST / 11 PRA) — top lines: Tatum PTS 26.5, PRA 41.5.
- PHI @ NYK: **44 prop rows** (13 / 11 / 10 / 10) — Brunson PTS 27.5, PRA 38.5.
- OKC @ SAS: **52 prop rows** (14 / 14 / 12 / 12) — Gilgeous-Alexander PTS 29.5; Wembanyama REB 11.5, PRA 41.5.

Total **143 opening-night prop rows** — recorded as input to the separate prop-feasibility assessment.
Props remain **NOT_WIRED**: no participation collector, no validated engine (registry NO_ENGINE /
unregistered; see §2). The manual capture's own recorded gaps stand (no assists rows for Wiggins,
K. Thompson, Murray, or Jackson — those are Oct 21-slate names).

## 5. Live DraftKings route — INTERMITTENT (kept separate from the pricing path)

[CORRECTED — the first draft of this section was written before the browser agent's result returned;
its "route still blocked" conclusion is superseded by the live observation below.]

- Morning (record on file, `1053_ct.json`): two signed-out browser attempts — board never rendered,
  API 403, CAPTURE_FAILED, 0 rows.
- This run, direct HTTP probe from the shell (Oct 19 ~5:05 PM CT): DK sportsbook API endpoint
  `…/sites/US-SB/api/v5/eventgroups/42648/categories/487/subcategories/4518` → **HTTP 403 "Access Denied"**
  (Akamai edgesuite reference page, 489 bytes; saved as `dk_api_probe_20261019_1700ct.txt`).
- This run, live browser agent (Oct 19 5:02:50–5:03:06 PM, signed out, read-only, no sign-in, no bet):
  **board RENDERED** — title "NBA Odds, Spreads & Lines | DraftKings Sportsbook", no 403/error/geo
  block, all three opening-night games visible under "Tomorrow" with spread/total/ML:
  - BOS @ DET (2:00 PM): BOS −1.5 −105 / ML −115; DET +1.5 −115 / ML −105; total 222.5 (−105/−115).
  - PHI @ NYK (6:00 PM): PHI +4.5 −108 / ML +150; NYK −4.5 −112 / ML −180; total **232.5** (−105/−115).
  - OKC @ SAS (8:30 PM): OKC +2.5 −112 / ML +114; SAS −2.5 −108 / ML −135; total 231.5 (−112/−108).
  vs the midday manual capture: BOS@DET prices shaded toward DET (BOS ML −112→−115), PHI@NYK total
  moved 231.5 → 232.5, OKC@SAS unchanged. These live lines were also run through `parse_lines` +
  `price_game`: **intake PASS ×3, LEAN/PASS labels only, probability pairs sum to 1** — so the primary
  (live) path, not only the fallback, is verified.

Conclusion: the DK route from this environment is **intermittent and route-dependent** — the browser
page render works (now), the shell-side API endpoint 403s, and this morning the browser route failed
twice. It is not evidence the board is empty and not a pricing-path failure. No lines were fabricated
from any failed attempt; every line above was actually observed on a named route at a named time.

## 6. Must fix / must do before first tip — Tue Oct 20, 2:00 PM CT (BOS @ DET)

No code fix is required: no genuine intake/binding/pricing defect was found, so the standing blocker
workflow (fix → test → verify) has nothing to repair, and no gate was lowered.

Operational items, in order:

1. **Fresh DK capture on Oct 20 (route is intermittent — plan for it).** The Oct 19 lines (midday manual
   + 5:02 PM live browser) are proof of board + intake only; by tip they are ~21–26 h old, and the
   binding layer refuses quotes older than 300 s. Any opening-night card decision needs a fresh capture
   near tip. Routes that worked Oct 19: owner-directed manual (midday) and the live browser render
   (5:02 PM). Route that failed: shell-side DK API (403) and this morning's browser attempts — so
   capture early enough to retry if the first attempt 403s (defect: `DK_ROUTE_INTERMITTENT_403`,
   environmental, open).
2. **Recheck the official injury report on Oct 20** — probe the Oct 20 slots again from late morning CT;
   for the 2:00 PM CT BOS@DET tip the relevant reports are the Oct 20 morning/early-afternoon ET
   editions. Until a PDF is retrieved, availability stays with the labeled ESPN-feed secondary signal only.
3. **Expect BLOCKED, not a priced card, from the canonical runner.** ML/spread/total publish as
   `FAMILY_REGISTRY_NOT_VALIDATED` until a governance ruling validates a family — that is the standing
   rule, not a bug to patch before tip. Internal LEAN/PASS pricing exists underneath the gate.
4. **Team totals and player props stay off any card** — team totals: no league-board rows + NO_ENGINE;
   props: boards exist (143 rows recorded) but NOT_WIRED (no participation, no validation).

## Evidence files (this directory)

`espn_scoreboard_20261020.json`, `espn_scoreboard_20261019.json`, `espn_injuries_20261019.json`,
`injury_2025-10-21_07PM.pdf` (historical control), 403 XML bodies saved as `injury_2026-10-*.pdf`,
`dk_api_probe_20261019_1700ct.txt`, `smoke_test.py`, `smoke_results.json`, `smoke_run2.log`.
Source capture: `~/workspace/sportsedge/dk_line_archive/nba/2026-10-19/1154_ct.json` (manual, verified)
and `1053_ct.json` (failed scheduled capture).
