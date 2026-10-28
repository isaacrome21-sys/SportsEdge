# CFB activation designs — team totals, period lines, game props, player props, SGP/live

**Date:** 2026-10-27 (America/Chicago). **Status of this pack: DESIGN ONLY.**
Nothing in this directory is frozen, nothing starts a clock, nothing is
validated, and nothing changes any family's registry state. Every document
here is a draft written so that an independent review can clear it, a screen
can be built against it, and — only after a screen passes — an owner freeze
can be requested under a separate prospective act.

Written under the owner's Oct 27, 2026 directive: *every family to
clock-running / armed / screening; nothing sits at NO_CONSTRUCTION.* This
pack covers the five CFB families that were at NO_CONSTRUCTION / NO_DATA in
`VERIFIED_MODELS_GAP_FILL_PLAN_20261027.md` §1. **CFB sides/totals are NOT
in this pack** — they wait on the G3 point-in-time QB admissibility audit
running elsewhere, and no document here designs, implies, or smuggles in a
sides/totals construction.

## Standing law these drafts obey

- VERIFIED (owner ruling, Oct 27, 2026, repealing the ≥50-picks gate) =
  preregistration + chronological out-of-sample validation against BOTH the
  existing model and a contemporaneous market baseline. The slate/row
  minimums inside the prereg drafts below are **test-design minimums of
  each family's own forward test** (the same role they play in the NBA
  team-totals prereg), not a label gate.
- FAILED constructions stay retired: CFB PM / AM / PRIOR_CURRENT_BLEND /
  CFB_CONVERGED_ANCHOR_V1 are named in the failure record and are not
  revised, re-run, or resurrected by anything here. CFB team totals is a
  **new family with a new construction** (a single team's scoring
  distribution), not the retired joint-score constructions wearing a new
  label — the non-resurrection argument is made explicitly in the design.
- Historical data seen by failed constructions is DESIGN data only.
  Verification accrues forward only — no backfill, ever.
- CFBD / SDV closes are untimestamped snapshots: a DESIGN baseline only.
  Flat −110 ROI is an ASSUMPTION and is labeled wherever it appears;
  vs-close on untimestamped closes is never "verified CLV."
- Illinois **college** teams are excluded from all CFB modeling scope
  (Illinois pro teams are in scope). Every design below carries the
  exclusion, enforced by the existing mechanism:
  `sportsedge/registry_gate.py` applies
  `artifacts.free_models.IL_COLLEGE_NAMES` first and returns
  `ILLINOIS_COLLEGE_EXCLUDED` before any family gate.
- PAPER / research only. No staking authority anywhere in this pack.
- Multiple testing: intervals and verdict tests use α = 0.05 with the
  Bonferroni-style divisor **k** = the number of families with an active
  forward clock overlapping the test window, recorded at freeze and at
  review (the larger k governs), per the NBA team-totals prereg §9
  pattern.

## Family states on landing

| Family | Before this pack | On landing (honest state) | Next step |
| --- | --- | --- | --- |
| CFB team totals | NO_CONSTRUCTION | **DESIGN ONLY** — construction + screen + forward prereg drafted; screen not yet run | Build + run the §-screen in the prereg draft; SCREEN_PASS earns the right to *request* an owner freeze |
| CFB quarters / halves | NO_CONSTRUCTION | **DESIGN ONLY** — construction + forward prereg drafted; market validation is forward-only (no historical period lines exist) | Lane capture-arming for priced 1Q/1H lines, then screen diagnostics on PBP; freeze request only after capture proves out |
| CFB game props | not inventoried | **DESIGN ONLY** — derived-probability construction + forward prereg drafted; pilot is shadow-pricing only | Confirm DK prop categories against captured comment material; shadow-price captured offers |
| CFB player props | NO_DATA | **CAPTURE ARMING SPEC** — no construction; design deliberately deferred to a named accrual threshold in the spec | Lane captures DK CFB prop offers under the spec; design task opens only at the threshold |
| CFB SGP | not inventoried | **PILOT SPEC — DEPENDENT, NOT ARMED** | Arms only after ≥2 leg families pass their own screens |
| CFB live in-play | not inventoried | **PILOT SPEC — NOT ARMABLE on current infrastructure** (no live play feed admitted, no in-play capture scope) | Historical PBP calibration diagnostics only until the named infra exists |

Registry note (honest): the family registry gate
(`sportsedge/family_market_registry.py`) currently registers CFB
moneyline/spread/total as research-only; **team totals and player props are
deliberately NOT in `CFB_RESEARCH_REGISTERED_FAMILIES`** and stay BLOCKED
at `sportsedge/registry_gate.py`. These drafts do not change that. A
registration change is a separate governance act that follows a screen
pass, never precedes it.

## Files

- `DESIGN_CFB_TEAM_TOTALS_V1.md` — the team-totals construction.
- `PREREG_CFB_TEAM_TOTALS_FORWARD_V1_DRAFT.md` — its historical screen
  (fixed criteria) + forward preregistration draft, in the NBA
  team-totals prereg pattern. **DRAFT — NOT FROZEN.**
- `DESIGN_CFB_PERIOD_LINES_V1.md` — quarters/halves construction +
  forward preregistration draft.
- `DESIGN_CFB_GAME_PROPS_V1.md` — game-props construction + forward
  preregistration draft.
- `CAPTURE_ARMING_SPEC_CFB_PLAYER_PROPS_V1.md` — capture-arming spec;
  construction design deferred to the accrual threshold named inside.
- `PILOT_SPEC_CFB_SGP_LIVE_V1.md` — SGP joint-pricing pilot + live
  in-play pilot, with their dependency gates and infrastructure blockers.
- `SPEC_HASHES.txt` — sha256 of every file in this pack.
