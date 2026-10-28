# NHL game props / SGP / live — scoping designs

**Status: SCOPING DESIGNS — design only, not frozen. No clocks, no
verified claims, no PLAY.** These families are dependency-ordered behind
NHL designs #4–#6. Each entry states what the market is, where its
probabilities come from, what validation would look like, and what blocks
it — so the taxonomy has no blank cells, and no cell pretends to be more
than it is.

## Game props (period markets, race-to, first goal)

- **Markets:** 1P moneyline/total, period puck lines, first team to
  score, race to 2/3 goals, both-teams-to-score variants, regulation-only
  derivatives.
- **Source of probabilities:** the parent simulation's period state —
  the attempt-2 sim already resolves regulation period by period in its
  machinery (period engines exist in-tree, `test_nhl_periods.py`); 1P
  distributions are the sim's first-period marginal, race/first-goal are
  path statistics of the same simulated games.
- **Validation shape (to be preregistered when reached):** scored as
  secondary families inside a Stage-B-style forward window on DK
  captures; comparator = DK no-vig and the game-line-implied derivation
  (e.g. 1P total as a fixed share of game total — the naive split, made
  explicit); primary metric log loss at offered lines; alpha = 0.05 / k;
  one look. No window is scheduled in this document.
- **Blocker:** parent construction + a capture-depth confirmation that
  DK posts these on the event pages the lane reads (they ride the
  comment block where the parser cannot read them).

## SGP

- **Rule (same as MLB design #2):** the joint distribution is the family.
  Legs only from NHL families with constructions (sides/totals,
  team totals, player props A); joint probabilities from the one shared
  simulation (a goalie's saves and the opponent's team total are the
  same simulated game, and their correlation is the product).
- **Validation shape:** independence-product of leg probabilities as the
  existing-model comparator; DK SGP implied as the market comparator;
  log loss on combination outcomes over a forward window that cannot
  open before the leg families' own windows close (earliest realistic:
  Feb–Mar 2027). Verdict capped by legs, exactly as in the MLB SGP
  design.
- **Blockers:** legs first; DK SGP builder capture for NHL does not
  exist yet.

## Live (in-play)

- **Pilot-first, mirroring the MLB live pilot spec:** shadow-only
  snapshots at period boundaries and after goals, model state =
  (period, clock bucket, score diff, manpower state, remaining
  goaltender/line state) propagated from the parent sim's rates; scored
  against DK live lines at matched timestamps with latency recorded per
  the #2792 receipts discipline; pilot output is a go/no-go report, not
  a verdict.
- **Why last:** NHL live lines move on every shot; the capture-latency
  problem is the worst in the program, and a live construction on a
  pregame parent that has not passed Stage B would be a derivative of an
  unproven base.
- **Blockers:** in-play capture infrastructure (does not exist);
  parent's Stage B verdict; pilot scheduling is the owner's call on the
  MLB pilot's evidence.

## Activation state on landing

SCOPING only. These three designs exist so the families are specified,
dependency-ordered, and honestly labeled — the work that activates them
is designs #4–#6 landing first.
