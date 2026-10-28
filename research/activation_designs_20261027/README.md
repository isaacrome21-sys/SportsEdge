# Activation designs — MLB pitcher extension / MLB SGP / MLB live pilot / NHL (all families)

Written Oct 27, 2026 (America/Chicago), under the owner's directives of that
night: every family carried to clock-running, armed, or screening; the NHL
pause LIFTED by explicit recorded decision (Oct 27, 23:04 CT); backtest and
fix until constructions honestly pass.

**Status of every document in this directory: DESIGN + PREREGISTRATION
DRAFT. Nothing here is frozen, no clock is started, no family is verified,
and nothing here creates a PLAY.** Freezing is the owner's act, per family.

## The validation law these drafts are written under (owner ruling, Oct 27, 2026 ~22:53 CT)

VERIFIED = a construction that has passed its preregistered chronological
out-of-sample validation against BOTH (a) the existing model for its family
and (b) a contemporaneous market baseline. The former >=50 graded forward
picks gate is repealed and appears nowhere in these drafts. Forward clocks
keep grading and reporting (CLV first) but do not gate the label. Frozen
preregistrations already in force run exactly as written — these drafts bind
none of them and amend none of them. PLAY eligibility additionally faces the
multiple-testing policy alpha = 0.05 / k, k = the number of validated
families at verdict time. Every validation below is ONE LOOK at a window and
criteria fixed in advance (anti-peeking): a failed look is recorded, and any
successor is a new version with its own preregistration — never a retune of
the version that failed. Historical data seen by a failed construction is
DESIGN data only. PAPER / research only, 0u, no staking authority.

## Activation states on landing (honest)

| # | Family | Design file | State on landing |
|---|--------|-------------|------------------|
| 1 | MLB pitcher props extension (pitches; hits+walks combo; either-pitcher variants) | MLB_PITCHER_PROPS_EXTENSION_DESIGN.md | DESIGN ONLY — screen executable on StatsAPI/Savant design data; market leg is forward-only (no historical pitch-prop lines) |
| 2 | MLB SGP | MLB_SGP_DESIGN.md | DESIGN ONLY — gated on its leg families; no SGP validation may run before the legs it combines are validated or explicitly carried as unvalidated inputs with the SGP verdict capped accordingly |
| 3 | MLB live (in-play) pilot | MLB_LIVE_PILOT_SPEC.md | PILOT SPEC — shadow only; requires live-capture infrastructure that does not exist yet |
| 4 | NHL sides / totals | NHL_SIDES_TOTALS_DESIGN.md | DESIGN ONLY — Stage A is the already-locked home-ice v2 accuracy verdict (Nov 30, 2026, unchanged); this draft adds the Stage B market validation after it |
| 5 | NHL team totals | NHL_TEAM_TOTALS_DESIGN.md | DESIGN ONLY — derivative of #4; activates with the parent's Stage B window |
| 6 | NHL player props (shots, saves; points/goals/assists scoped) | NHL_PLAYER_PROPS_DESIGN.md | DESIGN ONLY — shots/saves construction specified; points/goals/assists carry a named build prerequisite |
| 7 | NHL game props / SGP / live | NHL_GAME_PROPS_SGP_LIVE_SCOPING.md | SCOPING DESIGNS — dependency-ordered behind #4–#6 |

## Neighbors these drafts deliberately do not touch

- MLB pitcher-K ridge protocol (running, 4/150 graded) — untouched, not redesigned.
- `docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md` (v2, Oct 4, 2026) — the one-shot
  promotion study covering PITCHER_K / PITCHER_BB / PITCHER_ER /
  PITCHER_HITS_ALLOWED over the archived 2026 PIT quote archive. Frozen terms;
  runs as written. Design #1 covers only the markets that study does not.
- `research/forward_validation_program_20261020/drafts/PREREG_MLB_PITCHER_OUTS_FORWARD_V1_DRAFT.md`
  — the Oct 20 outs forward draft. Design #1 cites it and does not duplicate it.
- MLB batter incumbents and the MLB game-line Phase D core (reduced-fidelity
  FAIL recorded Oct 27, draft PR #2833; full-fidelity re-run in flight
  elsewhere) — recorded states stand; no design here depends on Phase D's
  outcome and none resurrects it.
- NHL attempt 1 — the no-edge verdict stands on the record (goal
  `nhl-second-attempt`); the #1249/#1253 generation, including its known
  totals double-count quirk, is retired and is not shipped, quiet-fixed, or
  re-scored by any design here.
- NHL home-ice v2 pre-lock (`docs/research/nhl_home_ice_v2_prelock.md`) — its
  window and pass criteria are already locked; design #4 cites them verbatim
  as Stage A and changes nothing in them.
- `NHL_PUBLIC_BASELINE_VALIDATION_RESEARCH_FREEZE_V1` governed paths
  (`config/research/nhl_public_baseline_validation_*`,
  `scripts/validate_nhl_public_baseline.py`) — untouched.

## Freeze-coverage check (performed before writing)

Every path in this directory was checked against all 11 bundles in
`config/freeze_reconciliation_registry_v1.json` on main `318377dfa`: no
bundle's coverage prefixes or paths govern `research/activation_designs_20261027/`,
and no governed path is modified by this pack.

## Shared capture dependency (NHL)

All NHL designs assume the standing lines-lane cadence (T-1H write inside
75–45 min pre-start; FINAL write inside the last 20 min; parser-safe grammar)
with NHL re-enabled per the owner's Oct 27 ruling, and the #2792 delivery
receipts contract. The capture restart pack is being built separately; if
capture does not land, the NHL validation windows below slide — the criteria
do not change.
