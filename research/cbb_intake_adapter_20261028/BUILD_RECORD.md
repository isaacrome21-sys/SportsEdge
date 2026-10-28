# CBB intake adapter — BUILD RECORD (Oct 28, 2026)

Closes the gap the CBB forward-runners build (PR #2907) flagged as its
underdetermination 4: the shared lines-intake parser's `ADAPTERS`
registry covered MLB/NFL/CFB/NBA/NHL only, so `adapter_for("CBB")`
raised and no live [CBB LINES] body could be parsed into the board
shape the runners consume through `games_from_board`.

## What was built

| File | Change |
|---|---|
| `sportsedge/pipeline/adapters.py` | New `CBB` SportAdapter registered in `ADAPTERS`. Mirrors the CFB table exactly — canonical names MONEYLINE / SPREAD / TOTAL / TEAM_TOTAL (the names the runners filter on) — with the default team resolver. |
| `sportsedge/cbb_lines_intake.py` | New CBB intake wrapper `parse_cbb_lines(body, title=..., fixtures=...)` in the pattern of `nfl_lines_intake` / `nba_period_lines_intake`: strict parse, comment event-id extraction, fixture-keyed Illinois enforcement. |
| `tests/test_cbb_lines_intake.py` | 18 tests (below). |

## Grammar targeted

The lane's [CBB LINES] issue grammar, identical in shape to every
other sport: line 1 `Away @ Home` (DK display names; the issue title
is the fallback header), line 2 the plain `Captured:` line (ISO-8601
with offset), line 3 an HTML comment carrying all metadata and every
market the parser cannot read, then one market per line, both sides,
away/over price first. The wrapper parses priced lines through the
shared parser with `strict_unknown=True`: a priced line whose label
the adapter does not know fails the game with
`CBB_INTAKE_UNRECOGNIZED` (the NFL strict-unknown lesson — never a
silent drop). The shared parser's own default (skip-with-warning)
is unchanged for direct `parse_issue` callers.

The adapter registers exactly the four markets the forward runners
consume: MONEYLINE, SPREAD, TOTAL, TEAM_TOTAL (subject = team).

## Identity and exclusion (as built)

* The shared parser strips HTML comments before parsing, so the
  wrapper scans the raw body's comments itself (single in-order pass,
  games detected with the parser's own `parse_header`, alignment
  verified against the parsed games) and carries each game's
  `DK event:` and `ESPN event:` ids onto the capture. The ESPN event
  id is the crosswalk join key for the Nov 1 pre-check. DK display
  names are NOT identity and no name-based join is invented: a comment
  without an ESPN event id yields `espn_event_id=None`, stamped.
  Conflicting ids refuse (`CBB_INTAKE_EVENT_ID_CONFLICT`); a comment
  id disagreeing with the fixture's refuses
  (`CBB_INTAKE_EVENT_ID_MISMATCH`).
* Illinois exclusion is enforced at intake when identity is
  fixture-supplied — `fixtures` is the same table the runners'
  `games_from_board` consumes, keyed on the board's `AWAY@HOME`
  display-name pair. The rule is the capture-scope module's
  (`sportsedge/cbb_capture_scope.py`): denylist ESPN ID denies,
  Illinois institution state denies, crosswalk
  `capture_excluded_illinois` flag denies; the refusal is
  `CBB_INTAKE_ILLINOIS_COLLEGE_EXCLUDED`. The denylist is IMPORTED
  from `cbb_capture_scope` — the same import the runners' shared core
  makes — never copied, so it cannot drift. A game with no fixture is
  stamped `identity_state="UNVERIFIED"` (names alone cannot apply an
  ESPN-ID rule); the runners re-apply the same exclusion at pricing
  time regardless.

## Grammar disagreements found (named, with the reading chosen)

1. **Combined "Team Totals:" line vs per-line TeamTotal form.** The
   lane's generic issue-format spec shows team totals as one combined
   line (`Team Totals: MIL 3.5 +120 -154; TB 3.5 +120 -154` — the MLB
   example in the spec). The shared parser's grammar is one market
   per line; a combined line cannot parse and under strict mode fails
   the game loudly rather than dropping silently. **Reading:** CBB
   team totals are posted one per line in the parser's TeamTotal form
   (`TeamTotal <DK display name> <line> <over> <under>` — the NFL
   TeamTotal form), subject first also accepted. The combined form
   remains MLB's own-grammar business; nothing about MLB changed.
2. **The lane comment names only "DK event:"; the crosswalk join
   needs the ESPN event id.** The standing line-3 grammar carries the
   DK event id, but the CBB crosswalk (PR #2898) joins DK slates via
   the ESPN event id and DK names are not a mapped source.
   **Reading:** CBB lane bodies should carry BOTH ids in the comment
   (`DK event: …; ESPN event: …`); the wrapper extracts both and
   invents neither.
3. **TeamTotal subject resolution.** NFL resolves bare nicknames
   through an alias table; no lawful DK-name alias source exists for
   CBB (the crosswalk deliberately does not map DK names).
   **Reading:** the adapter uses the shared default resolver
   (whitespace-normalized display names), so the TeamTotal subject
   must textually equal the header's display name — the parser
   refuses `CBB_INTAKE_TEAM_NOT_IN_GAME` otherwise, fail-closed.
4. **First-half sections.** The capture-scope census names
   FIRST_HALF_SPREAD / FIRST_HALF_TOTAL among its seven sections, but
   those live in the CBB_CAPTURE_V1 manifest grammar, not the lines
   grammar, and no forward runner consumes 1H lines (the 1H family's
   screen has not run). **Reading:** the adapter registers only the
   four runner-consumed markets; a priced 1H line in a [CBB LINES]
   body fails loudly under strict mode instead of being silently
   dropped, and 1H material rides in the comment meanwhile — the same
   separation NBA period lines got with their own specs + module.
5. **Captured-line scope.** In this grammar the header precedes the
   `Captured:` line, so the instant lands as the game's own capture
   and `board_captured_at` stays None. That is the shared parser's
   documented semantics for every sport and the runners already fall
   back game-first; recorded here so nobody "fixes" it later.

## Verification run with this build

* New tests: 18/18 pass — adapter registration and canonical names;
  representative body (all four markets incl. both TeamTotals);
  comment ids carried, comment-carried priced extras ignored;
  board-dict shape vs the runner-consumed keys; strict failure on
  priced 1H and player-prop lines; one-sided and third-team-subject
  failures; UNVERIFIED stamping without fixtures; fixture/comment
  event-id mismatch and comment-id conflict refusals; Illinois
  refusal by each of the three rule legs (denylist ID, institution
  state, crosswalk flag) plus a clean-fixture pass; title-fallback
  and two-game id attribution.
* Cross-check against PR #2907's actual runner code (run in that
  build's checkout with this adapter + wrapper temporarily in place,
  then restored): `parse_cbb_lines(...).to_board_dict()` feeds BOTH
  runners' `games_from_board` — efficiency SPREAD/TOTAL quotes and
  team-total TEAM_TOTAL_AWAY / TEAM_TOTAL_HOME sections land with
  the right lines. **Caveat of record:** PR #2907 was still open when
  this was built (this branch is on main 53ca9868b); the adapter
  targets the parser-output shape, and the pair must be re-verified
  together once both land. The wrapper's three-leg Illinois check
  mirrors the runners' core `illinois_excluded` with the denylist
  imported from the module of record; re-verify against the core
  then (the denylist itself cannot drift — imported, and pinned by
  the runners' capture-scope sha).
* No regression: the other sports' intake suites pass unchanged
  (cross-sport parity, hostile boundaries, NFL/NHL/NBA-period/MLB
  intake, exact prices, puck-line both-lines, phone-issue suites —
  231 passed); the full CBB selection on main passes (163 passed,
  including the 18 new).
* Repo PR gates: dependency parity 11 = 11 (no dependencies added);
  `ruff check --select E9,F821,F822,F823,F811 .` clean.
* Freeze-coverage self-check (repo matcher over all registry
  bundles): none of this build's four paths are covered.

This build records captures only: it prices nothing, starts no
clock, freezes nothing, and confers no eligibility.
