# NHL player props — construction design + preregistration draft

**Status: DESIGN ONLY — preregistration DRAFT, not frozen. No clock, no
verified claim, no PLAY.** Split into two sub-families with different
readiness, stated plainly: (A) skater shots on goal and goalie saves —
construction specified below; (B) goals / points / assists — a named
build prerequisite stands in front of any construction, so this draft
scopes it and specifies nothing it cannot yet mean.

## (A) Shots on goal + goalie saves

**Current state.** Prop machinery exists in-tree (role/event binding,
peripheral-prop and goalie-saves tests), and the card prereg holds these
markets at NO_MODEL because roles + confirmed starters are required and
no fitted owner exists. There are no historical NHL prop lines anywhere
in the program's sources (Gap G1 class): the market baseline is forward
DK captures only.

**Edge mechanism.** Shot volume is a role statistic before it is a skill
statistic: ice time, power-play unit, and line deployment drive attempts,
and DK's shot lines lag role changes (a winger promoted to PP1 carries
last month's line into this week's role). Saves are the mirror: opponent
shot volume against, conditioned on the opponent's rate state and the
game environment, against a line that mostly prices the goalie's own
recent save counts.

**Construction.** Per-skater shot distribution: expected TOI from
strictly-prior deployment (line + PP unit from official play-by-play
shifts where captured, else boxscore TOI history), shot rate per 60 by
role state, opponent shot-suppression adjustment; negative-binomial
count distribution. Goalie saves: opponent expected SOG from the parent
construction's shot rates × the confirmed starter's strictly-prior save
probability by shot quality band (MoneyPuck xG per shot as the quality
weight, pending admission); unconfirmed starter = degraded row, priced
only under the blend rule of design #4 and flagged. Identity is not
availability: a goalie is a confirmed starter only on sourced evidence
(official API / team reporting with timestamp), never on rotation guess.

**Inputs.** Official NHL API play-by-play/boxscore (research-admitted;
pricing role requires the same source-role decision as design #4),
MoneyPuck (pending admission), forward DK captures of the prop surface.

**Validation protocol (fixed; one look).** Window: Dec 15, 2026 –
Feb 15, 2027 (starts two weeks after sides, because prop capture depth
must be proven on the restart slates first), every paired DK offering in
shots (skaters with a posted line) and saves. Comparators: (a) a naive
role-free rate model — player's strictly-prior per-game mean as a Poisson
mean, named here as the existing-model stand-in because no fitted NHL
prop model exists to beat; (b) DK no-vig. Primary metric: log loss at the
offered lines. PASS = beats BOTH, alpha = 0.05 / k, one look. Minimum 300
priced player-games per market (shots, saves scored separately); window
extends by the fixed rule if unmet.

## (B) Goals / points / assists — scoped, not designed

`player_props.py` marks these unsupported, and honestly so: a points
distribution needs a per-player scoring engine (shot quality → goal
probability, primary/secondary assist allocation by on-ice context) that
does not exist in the program. Prerequisite build: a points engine on the
parent construction's shot-level rates, screened on design data
(2023–2026 official PBP + MoneyPuck), with its own design document. Until
that screen exists, this sub-family is NO_CONSTRUCTION with a named
prerequisite — this draft deliberately writes no validation protocol for
a model that has not been specified.

## Activation state on landing

DESIGN ONLY (A specified; B scoped). Both wait on capture restart with
prop depth confirmed; (A) also on the source-role decision for official
play-by-play in pricing paths.

## Blockers

- DK NHL prop capture depth on restart (event pages carry the props; the
  lane grammar must carry them in comment where unreadable, as with NFL).
- Source-role decision for official API PBP in pricing paths (it is
  admitted research-only today).
- (B): points engine does not exist.
