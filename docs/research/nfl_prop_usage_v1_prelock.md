# NFL player-prop usage v1 — pre-lock

**Status:** menu and windows locked. No scoring in this document.
Research only. Live phone card stays `NO_MODEL` for every player prop.

This is the SportsEdge translation of the public prop-board *outline*
(usage first, grade only with a line, freeze on lineup). It is not a port of
another site's projections, diffs, or grades.

## Markets (v1)

| Position | Usage knob (What-If) | Counting markets |
|---|---|---|
| QB | pass attempts | pass yds, completions, pass TD, INT, rush att, rush yds |
| RB | rush attempts + targets | rush yds, receptions, rec yds, rush+rec yds |
| WR | targets | receptions, rec yds, rush att, rush+rec yds |
| TE | targets | receptions, rec yds |

Out of v1: anytime TD, longest completion/rush/rec, sacks, tackles,
team totals as player props, same-game parlays.

## How a row is built

1. Usage from strictly-prior snap / route / target / carry rates and the
   frozen Attempt-9 team total (script). No market prices as features.
2. Counting stats = usage × rate. Rates shrunk toward position-season means.
3. No confirmed lineup / inactive list → show nothing or `NO_MODEL`.
   Pending is not a grade.
4. No book line pasted in the phone issue → no Diff, no Grade, no Edge%.
5. Same simulated game as the team total. A WR rec-yds row that cannot live
   with the game total is `NO_MODEL`, not an independent projection.

## Windows

| Role | Window |
|---|---|
| Fit / shrink | 2021–2024 REG |
| Validate once | 2025 REG |

2026 W1–W3 is spent for Attempt 9 diagnostics and is **not** the prop gate.
If v1 fails 2025, v2 needs a new unused window.

## Gates on 2025 (must all hold)

On players with a posted close line and a known starter/inactive list:

1. Mean |predicted P(over) − observed| at the close line ≤ 6 pp across
   pass yds, rush yds, rec yds (separate rows, then pooled).
2. Brier not worse than a position-mean baseline built on 2021–2024 only.
3. Zero rows emitted when the inactive list is missing.

## After a pass (separate promotion PR)

Phone card may list the v1 markets. Label `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.
Parity test between research rates and the production copy.
