# NBA + CBB activation designs — Oct 28, 2026

**Status: DESIGNS AND PREREG DRAFTS ONLY — nothing in this directory freezes
a family, starts a clock, counts a row, or makes any family verified.**
Prepared overnight Oct 27–28, 2026 (America/Chicago) under the owner's
directive that every family be brought to clock-running / armed / screening.
What this packet does is finish the *paperwork of activation*: for each
family below there is now a named construction or a named gap, a drafted
test, and a named next gate. The remaining gates are owner acts (freezes),
data admissions, and capture builds — each stated in its document.

All output remains PAPER / 0u research. "Verified" is used only in the
owner's Oct 27, 2026 sense: a family is verified when it has **passed its
preregistered chronological out-of-sample validation against both the
existing model and a contemporaneous market baseline**. No family in this
packet has done that.

| # | Family | Document | Activation state reached |
|---|---|---|---|
| 1 | NBA period lines (quarter/half totals) | `NBA_PERIOD_LINES_PREREG_DRAFT.md` | PREREG DRAFTED on an existing screened candidate |
| 2 | NBA game props | `NBA_GAME_PROPS_DESIGN.md` | DESIGN (Phase A spec'd; no construction exists) |
| 3 | NBA SGP | `NBA_SGP_DESIGN.md` | DESIGN ONLY (gated on leg families) |
| 4 | NBA live (in-play) | `NBA_LIVE_PILOT_SPEC.md` | PILOT SPEC ONLY (no in-play capture exists) |
| 5 | CBB sides / totals | `CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md` | DESIGN + DESIGN-SCREEN SPEC + PREREG DRAFTED |
| 6 | CBB team totals + 1H lines | `CBB_TEAM_TOTALS_1H_DESIGN.md` | DESIGN (TT rides #5's screen; 1H has a named data prerequisite) |
| 7 | CBB player props | `CBB_PLAYER_PROPS_CAPTURE_ARMING_SPEC.md` | CAPTURE-ARMED (spec); construction stays NO_CONSTRUCTION + NO_DATA |

## Fences this packet observes

- **NBA player props V2 is QUARANTINED** (owner ruling Oct 27, 2026). No
  document here touches, restarts, or routes around the V2 family clock.
  NBA player props of any kind are out of scope for this packet — including
  as SGP legs and including the Oct 20 secondary player-prop build
  (`research/nba_secondary_prop_20261020/`), which this packet does not
  build on.
- **NBA team totals is already ARMED** under its own preregistration
  (PR #2504) with a governance receipt act outstanding. It is a sibling,
  not a subject, of this packet; the period-lines draft expressly excludes
  the full-game team-total family.
- **NBA sides/totals** are owned by the successor design (PR #2786),
  blocked on a timestamp-authenticated baseline. Not re-opened here; game
  props and SGP treat that family as a deferred dependency, never a
  detour around the block.
- **DIST_V1 stays retired.** Nothing here resurrects it or reuses its
  signals. In-tree simulation machinery adjacent to it is cited only as
  existing code, never adopted without its own review.
- **CBB:** Illinois **college** teams are excluded (conference/roster-
  aware, fail-closed; Illinois professional teams are unaffected).
  **KenPom is NOT ADMITTED** (paid) — Torvik only, via the admitted
  archive route (draft PR #2832). Schedule reality per the hash-verified
  hoopR substrate (draft PR #2835): **0 games on Nov 1, 2026 and exactly
  50 on Nov 2** — no design in this packet assumes a Nov 1 slate.
- **Composition, not duplication (CBB):** open PRs #2152 (as-of ratings
  model / ESPN-ID binder), #2197 (fixture IDs), #2350 (game/halves and
  player-stat foundations, Illinois exclusion) and #2280 (DK captured-
  market evidence contract) already claim implementation areas, per
  `research/cbb_season_prep_20261020/READINESS_CONTRACT_DRAFT.md`. The CBB
  documents here are activation designs and test drafts that compose with
  that work; they reimplement none of it and preempt none of it.
- **Freeze coverage:** every path in this directory was checked against
  all 11 bundles in `config/freeze_reconciliation_registry_v1.json` on
  main `318377dfa` — none is governed.
