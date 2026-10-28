# NFL first-scoring attribution panel — admission record, and NFL_FIRST_TD_V1 build record

Date: 2026-10-28. Basis: `research/nfl_activation_20261027/
DESIGN_NFL_GAME_PROPS_TD_V1.md` sections 2–3 and
`PREREG_NFL_FIRST_TD_FORWARD_V1_DRAFT.md` (PR #2852), which named
the blocker this pack removes for design purposes:
`NO_VERIFIED_FIRST_SCORING_ATTRIBUTION` — "no admitted panel
labels the credited first touchdown scorer of each game."

Nothing in this pack is frozen. The framework config
(`sportsedge/forward_validation/configs/nfl_first_td.json`)
still reads `model_version: "UNPINNED"` and is untouched, as are
the frozen anytime-TD family and the Oct 20 2+ TD prereg draft.

## Part 1 — Panel admission

**Verdict: ADMITTED for design-stage use** (the design screen and
any successor design work). The panel does not by itself change
canonical coverage: the design's steps 2–3 (forward capture of
priced slates against committed rosters/depth) remain unbuilt,
so the family still resolves NO_DATA for forward purposes.

### Derivation rules, as pinned (builder: `build_panel.py`, DERIVATION_VERSION `NFL_FIRST_TD_PANEL_DERIVATION_V1`)

The design pins the label (design section 3 step 1): "the
credited first scorer (player + team + type) from play-by-play
scoring plays, joined to verified player identities," with the
evidence layer's refusal classes "applied as counted/reported
exclusions." The builder implements exactly that, through the
merged evidence module `sportsedge/nfl_first_td_pbp_evidence.py`:

- LABEL: the credited player on the game's first touchdown event
  (design section 2 settlement identity). The evidence layer
  enforces the derivation rules: field goals and safeties are not
  touchdowns; a non-scoring period 5 is legal; touchdown types
  are the evidence module's eight-value taxonomy.
- TD TYPE MAPPING from nflverse flags (no `def_touchdown` column
  exists in this feed — a defensive/return TD is identified by
  td_team ≠ posteam): pass_touchdown → RECEIVING; rush_touchdown
  → RUSHING; return_touchdown → INTERCEPTION_RETURN if
  interception = 1, else by play_type: kickoff → KICKOFF_RETURN,
  punt → PUNT_RETURN, field_goal → BLOCKED_KICK_RETURN, anything
  else → FUMBLE_RETURN; a TD with no mapping →
  OTHER_EXPLICIT_CREDIT.
- ORDER: plays are ordered by (period ascending,
  quarter_seconds_remaining descending, play_id) — the feed's
  event-time chronology. play_id alone interleaves
  administrative rows (timeouts, no-plays) whose play_id sits in
  the next period's id range (49 false out-of-order games), and
  game_seconds_remaining restarts at the overtime boundary (121
  false games). The label is insensitive to the choice: the first
  TD under play_id order and under the pinned order is the same
  player in all 1,949 games with a touchdown (verified at
  admission over the full pull). OUT_OF_ORDER_EVENTS applies
  where event time itself is missing: any play without a period,
  or a touchdown play without a clock stamp (a non-scoring play
  without a clock stamp is placed last within its period; 68 such
  administrative rows exist, none is a touchdown).
- COMPLETENESS (structural, asserted by the builder; the
  evidence module's posture stays UNVERIFIED): the game's plays
  exist, the periods span 1..max with max ≥ 4, and the play count
  clears a recorded threshold of 100, else INCOMPLETE_PBP.
- TEAM CODES: the schedules file is the fixture authority. The
  PBP feed retro-recodes the 2019 Raiders as LV; all 37
  PBP-vs-fixture team mismatches on touchdown plays trace to
  that single recode. Recorded normalization:
  (2019, "LV") → "OAK". No other normalization exists.
- IDENTITY: the credited player_id must resolve in the pinned
  nflverse players file (UNVERIFIED_PLAYER_ID), the credited
  team must be a fixture team (CREDITED_TEAM_NOT_IN_FIXTURE), a
  touchdown without a credited player_id is
  MISSING_SCORER_IDENTITY. Excluded games contribute no rows to
  the panel or the companion history store.
- PACKETS: scheduled start from the schedules file (gameday +
  gametime, America/New_York → UTC); completed_at = observed_at
  = the pinned PBP asset's own release updated_at (the packet was
  observed in that release; postgame by construction).

### Inputs (full pin tuples in `panel_manifest.json`)

16 consumed assets from nflverse-data GitHub releases, each
recorded with release id, asset id, size, updated_at, and the
pulled bytes' sha256: play_by_play 2019–2025 (release 58152862),
games.csv.gz schedules (release 251386473, asset 684975992,
515,852 bytes, updated 2026-10-28T12:46:30Z, pulled sha256
84354cb61320f3d784cab3ab65ed9c3488b8bb363bb478752c7a7b3b80b6904a),
weekly rosters 2019–2025 (release 73313637), players.csv
(players release, asset 681915686, 7,306,094 bytes, sha256
14f38ca9… full value in the manifest).

Drift disclosures: (a) the schedules release is a rolling
release — the pulled games file differs from both byte pins
recorded in PR #2831; fixtures were therefore re-verified game
by game (all 1,960 panel games matched their fixture; the 37
team-code mismatches are the LV/OAK recode above, not drift).
(b) The games file's season-type column is `game_type` with
values REG/WC/DIV/CON/SB; the panel covers REG + all playoff
rounds, matching the design's "NFL games."
(c) Depth-chart files 2020–2025 were pulled and NOT consumed:
the 2025 file's schema diverges completely from 2020–2024
(source switch). Weekly roster records are the uniform
membership source (see R-CANDIDATES below).

### Coverage

**1,960 of 1,960 games admitted, zero exclusions of any class**
(builder-reported counts, reproduced in the manifest):
2019: 267 · 2020: 269 · 2021: 285 · 2022: 284 · 2023: 285 ·
2024: 285 · 2025: 285. Panel window per the design = 2020–2025
(**1,693 games**); 2019's 267 games are PRIOR_ONLY rows — the
cold-start pool source for 2020 under the Part 2 training-season
convention, not part of the admitted window. No-TD games: 11
(2020: 0). First-TD types over 2019–2025: RECEIVING 1113,
RUSHING 729, INTERCEPTION_RETURN 51, FUMBLE_RETURN 22,
PUNT_RETURN 15, KICKOFF_RETURN 11, OTHER_EXPLICIT_CREDIT 8.
Companion history store `player_td_game_2019_2025.csv`: 10,118
credited touchdown rows (every TD, not only firsts) — the
construction's anytime/first history source.

Panel sha256
`11867ac3be6ee75c086e6069e2c914fd13aa01da529d1359b638874efdc24cd4`;
companion sha256
`5a0e96c8383d081624ae7f279e12f93c2415ba4fb894680743d97a5295cc2ed2`.
The full pull (22 release assets) is recorded in the manifest's
source metadata; pulled bytes stay outside the repo.

### Spot verification — 10 of 10 against a second source

Checked 2026-10-28 against Pro Football Reference box-score
scoring tables (via public search results; PFR pages were not
scraped) and, where noted, official/contemporary scoring
summaries. Panel label first, second source second:

1. 2020_21_KC_TB (Super Bowl LV) — Gronkowski, TB, RECEIVING Q1
   → NFL scoring summary: Butker FG first score; Gronkowski
   8-yd TD Q1 0:37, first TD. MATCH.
2. 2024_22_KC_PHI (SB LIX) — Hurts, PHI, RUSHING Q1 → PFR:
   Hurts 1-yd rush Q1 6:15, game's first score. MATCH.
3. 2021_22_LA_CIN (SB LVI) — Beckham, LA, RECEIVING Q1 →
   contemporary reports: Beckham 17-yd TD Q1 6:22, "first
   touchdown of Super Bowl LVI." MATCH.
4. 2025_22_SEA_NE (SB LX) — Barner, SEA, RECEIVING Q4 →
   recaps: 12 points of FGs through Q3; Barner 16-yd TD early
   Q4, game's first touchdown. MATCH.
5. 2019_01_BUF_NYJ — Mosley, NYJ, INTERCEPTION_RETURN Q1 →
   PFR: Mosley 17-yd interception return Q1 10:34, game's first
   score (the game's Q3 safety is correctly not a TD). MATCH.
6. 2021_09_BUF_JAX — NO_TD → AP reports: 9–6, "didn't feature a
   single touchdown," five FGs. MATCH.
7. 2022_05_IND_DEN — NO_TD → PFR scoring table: seven field
   goals only, OT included. MATCH.
8. 2019_03_DET_PHI — Agnew, DET, KICKOFF_RETURN → PFR: Elliott
   FG Q1 11:28 (first score), Agnew 100-yd kickoff return
   11:14, first TD. MATCH (FG-first game labeled by first TD).
9. 2019_11_ATL_CAR — Barner, ATL, PUNT_RETURN → PFR: Koo FG
   Q1 11:39 (first score), Barner 78-yd punt return Q1 0:59,
   first TD. MATCH.
10. 2023_01_BUF_NYJ — Diggs, BUF, RECEIVING Q2 → contemporary
    reports: FGs traded 3–3, then Allen→Diggs TD in Q2, "the
    night's first touchdown." MATCH.

All seven Super Bowl first-TD labels in the window were also
checked as a group (LIV Mahomes rushing, LV Gronkowski, LVI
Beckham, LVII Hurts rushing, LVIII McCaffrey, LIX Hurts rushing,
LX Barner) — all correct.

## Part 2 — NFL_FIRST_TD_V1 build

Module: `sportsedge/nfl_first_td_v1.py`. Implements the design
section 2 form exactly: Stage 1 team-first share by the Part 2
K = 3 form on game counts toward the league rate, first
possession at the league-average mixture (no coin-toss input);
Stage 2 player first-TD share shrunk at K1 = 3 toward the
player's shrunk anytime share (Part 2 K = 3 toward the
positional league pool RB/WR/TE/QB); DEF/ST as a single pooled
outcome class per team with its own point-in-time rate; the
no-touchdown outcome carried; renormalization over board +
DEF/ST + no-TD. No market input anywhere (asserted by test).

### Documented readings (where the design text needed one)

- R-COLDSTART: the league pools (the G terms) for weeks 1–3 come
  from the previous season's full-season pool, per the Part 2
  calibration prereg's own week 1–3 fallback; team and player
  counts are always same-season prior games only, per Part 2's
  sample rule.
- R-CANDIDATES: the priced board is the set of weekly-roster
  records with status ACT for the game's week (the design's
  "week's committed roster records"), all positions; position
  group of record at history-update time is that game-week's
  roster position, falling back to the players file. Thin-
  history players are routed to the pool by the shrinkage, per
  the design.
- R-NOTD: the no-TD weight is the pool source's point-in-time
  no-TD rate, unsmoothed — as the design specifies the outcome
  is carried "with its point-in-time rate." Before a season's
  first no-TD game that rate is 0; the screen reports those
  games per arm (SCREEN_REPORT.md) rather than flooring any
  probability.
- Scorer-position grouping for pool shares uses the credited
  player's roster position group; return/defensive scorers route
  to the DEF/ST class by touchdown type, never to a player row.

### Build-stage correction (recorded, not hidden)

The screen's zero-probability diagnostic caught a defect in the
first build of `position_group()` (RB mapped to the QB pool),
which invalidated the partial run; it was fixed and the screen
re-run from scratch. The episode is recorded here because the
screen's refusal to proceed silently is what surfaced it.

### Screen verdict

**FAILED_SCREEN** — full numbers in `SCREEN_REPORT.md`:
Δ log loss vs B1 +0.1674 (95% CI [+0.1397, +0.1952], FAIL);
vs B2 −0.0158 ([−0.0680, +0.0377], FAIL); top-decile
overstatement 1.8 points (PASS); 1,682 of 1,693 panel games in
the paired means. The construction does not advance and returns
only as a new version (prereg draft section 1).

### Tests and gates

- New tests: `tests/test_nfl_first_td_v1.py` (8 — shrinkage
  forms, renormalization, DEF/ST + no-TD carried, PIT isolation,
  B1 collapse invariance, no-market-input surface) and
  `tests/test_nfl_first_td_panel.py` (9 — defensive TD first,
  FG-first game, safety is not a TD, OT first TD, return-type
  taxonomy, missing identity, out-of-order, incomplete PBP,
  LV→OAK normalization). With the pre-existing evidence suite:
  33 passed.
- Ruff gate (E9,F821,F822,F823,F811) clean on all new files.
  No new dependencies (pyproject / requirements-test untouched).
  Freeze-coverage matcher over every touched path: no bundle
  covers any of them.
- Panel rebuild is byte-identical after the final derivation
  edit (sha256 verified before/after).
