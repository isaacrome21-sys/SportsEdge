# CAPTURE-ARMING SPEC — CFB Player Props V1

# SPEC ONLY. NO CONSTRUCTION IS DESIGNED BY THIS DOCUMENT.

- Status: `CAPTURE_ARMING` — the family state stays **NO_DATA
  (history) / NO_CONSTRUCTION** until the accrual threshold in §5 is
  met. This spec exists so the dataset a future construction needs
  starts accruing **now**, in the right shape, instead of being
  wished for later.
- Date drafted: 2026-10-27
- Rationale (one line): no free historical CFB player-prop closing
  lines exist anywhere located (Gap G1, verified in the gap plan) —
  so there is nothing to screen against, and the only path to a
  prop construction is a forward-captured line archive. Every slate
  not captured is gone permanently (no backfill, ever).

## 1. Families in capture scope

Exactly the CFB player-prop families already registered research-only
in `sportsedge/family_market_registry.py` (`CFB_PLAYER_FAMILIES`) —
the ones with an existing research pricing path:

`player_passing_yards`, `player_passing_tds`, `player_pass_attempts`,
`player_completions`, `player_interceptions`, `player_rushing_yards`,
`player_rush_attempts`, `player_receiving_yards`, `player_receptions`,
`player_rush_plus_rec_yards`, `player_pass_plus_rush_yards`.

**Out of capture scope** (deliberately unregistered today; their
`NO_ENGINE` refusal is the truthful state): anytime / first touchdown
scorer, longest play, rushing/receiving TD props, kicking props,
defensive stat props. Capturing them into this archive requires a
separate registration act; this spec does not do it, and the lane
does not transcribe them into the prop archive (they may appear in
issue comment material under the general lane discipline, which does
not make them archive rows).

## 2. What gets captured, in what shape

For every CFB game where DraftKings posts player props (in practice:
marquee and televised games — the spec takes the board as it comes
and never inflates it), at each of the lane's two standing marks
(T-1H and FINAL, per the lines-lane cadence ruling):

- fixture identity: DK event id, away/home, commence time CT;
- player identity: full name as displayed, team, and — at ingestion —
  the CFBD roster join (team + jersey number + normalized name
  agreement; **never a name-only join**, per the program's identity
  rules; unresolved identities are `IDENTITY_UNRESOLVED`, excluded
  and counted, never guessed);
- market (one of §1), line, both sides' American prices (a one-sided
  prop offer is captured verbatim and flagged `SINGLE_SIDED`; it is
  not a valid entry/close pair for any future test);
- `captured_at` with zone, ENTRY/CLOSE designation by mark, source
  view, entered_by — the Capture Spec V1 field discipline, with the
  #2792 five-timestamp delivery receipts for the write itself.

Grammar precondition: rows are written in the CFB issue in the
parser-safe grammar the intake accepts for props (the NFL Prop-line
pattern is the template; the CFB intake's acceptance of each §1
market must be **verified against the parser before the first armed
slate**, and any market the parser rejects travels in the line-3
comment verbatim — a priced body line the parser does not recognize
fails the whole game, which is never an acceptable trade for prop
volume).

## 3. Settlement source

CFBD player game stats (game_id join to the fixture; player identity
via the §2 roster join). A captured row whose settlement cannot be
joined is `RESULT_UNAVAILABLE` in any future accounting — excluded
and counted, never filled from a second source's name match.

## 4. Exclusions

- **Illinois colleges:** props on any game involving an Illinois
  college team are refused `ILLINOIS_COLLEGE_EXCLUDED` at ingestion
  (`sportsedge/registry_gate.py` / `IL_COLLEGE_NAMES`, applied
  first). They are not archive rows and enter no denominator,
  including the §5 accrual counts.
- Games already started when first seen; suspended markets; rows
  with non-finite prices. Each refusal is one code, counted,
  reported per slate.

## 5. Accrual threshold — when a construction design may open

The design task opens (it does not auto-open a construction, a
prereg, or a clock) when the committed capture archive first holds
**all** of:

- ≥ **1,500** valid captured player-game line rows (both-sided,
  identity-resolved, non-excluded), **and**
- ≥ **150** distinct games with at least one valid row, **and**
- ≥ **10** distinct slates, **and**
- ≥ **300** valid rows in the largest single §1 family.

Thresholds are stated here, before accrual, and are not lowered to
meet a date. Progress is reported per slate as counts only (rows,
games, slates, per-family counts) — operational monitoring, no
accuracy or CLV figures, because there is no construction to grade
yet and inventing one retroactively is exactly what this spec
forbids.

**Design-data rule (binding on the future design):** every row
captured before a future construction's freeze is DESIGN data for
that construction. Its validation runs only on captures after its
own preregistration and freeze, under the program's standing law.
The archive buys the *design*; it never buys the verdict.

## 6. What this spec does not do

No construction, no preregistration, no pricing, no registration
change (the §1 families are already registered research-only; this
spec adds nothing to the registry), no clock, no picks. If accrual
stalls because DK's CFB prop board stays thin, the honest report is
the count — the family rests at CAPTURE ARMING rather than
manufacturing history that does not exist.
