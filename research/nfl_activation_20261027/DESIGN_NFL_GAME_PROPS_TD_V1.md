# DESIGN — NFL game props (TD exotics beyond anytime-TD): `NFL_FIRST_TD_V1` + family map

**Status: DESIGN ONLY.** Family before this pack: NO_CONSTRUCTION for
everything beyond anytime-TD (the TD-scorer boards are captured inside
issue comments; one sibling market — 2+ TDs — already holds an Oct 20
preregistration draft). PAPER / research only.

**Boundary with the frozen family:** anytime-TD v1.1 is FROZEN and
running its own clock. Nothing here touches its construction, its
terms, or its rows. This family starts where ATD ends: the *ordering*
and *multiplicity* markets — who scores first, who scores twice or
more, and the milestone ladders.

## 1. Family map (what exists, what this pack adds)

| Market | State before this pack | This pack |
|---|---|---|
| First TD scorer (Yes board) | Engine assessment exists (`sportsedge/nfl_anytime_td.py: assess_first_td`); canonical coverage resolves the family **NO_DATA** (`NO_VERIFIED_FIRST_SCORING_ATTRIBUTION`); settlement evidence layer built Oct 20 (`research/nfl_first_td_pbp_20261020/BUILD_REPORT.md`) — postgame label extraction only, no prediction panel | Construction design (§2) + preregistration draft (`PREREG_NFL_FIRST_TD_FORWARD_V1_DRAFT.md`) + framework config |
| 2+ TDs (Yes board) | **Preregistration draft exists** (Oct 20, `research/forward_validation_program_20261020/drafts/PREREG_NFL_TWO_PLUS_TD_FORWARD_V1_DRAFT.md`) binding `NFL_PROP_ENGINES_V1`; its calibration screen recorded DOES_NOT_BEAT_BASELINE (ties the league pool B2: ΔCRPS −0.0007, CI spans 0) | **Unchanged.** This pack does not re-draft, re-screen, or re-state that market's terms. Its activation path is the one its own draft names: capture expansion (the 2+ TD board is not in Capture Spec V1's subset) + owner freeze. The screen result is the family's honest prior: the ≥2 TD tail is pool-dominated at that construction's resolution |
| TD milestone ladders (3+ TDs; TD-count milestones) | Captured in issue comments only; no draft | Declared as extension markets of the 2+ TD construction family (same engine, additional thresholds, separate market keys, verdicts per market). No separate design is offered: a ladder rung is the same tail probability at a higher threshold, and the 2+ screen's pool-domination result applies a fortiori. If 2+ TDs ever validates, ladders get their own prereg drafts then; designing them now would manufacture paper progress |

## 2. The first-TD construction — `NFL_FIRST_TD_V1`

**The market:** DraftKings' first-touchdown-scorer board — a Yes price
for each player to score the game's first touchdown (any type: rushing,
receiving, return, defensive — per DK settlement).

**Why it might be wrong:** first-TD prices are visibly derived from
anytime-TD prices — apply a roughly uniform "first" discount to the
anytime probability and re-margin. But the first touchdown is not a
random draw from the game's touchdowns. It is scored by the team that
scores first, on an early drive, and early drives are *scripted*: the
first ~15 plays are pre-planned, and offenses differ measurably in
whom the script features. A goal-line back on a run-heavy script, a
tight end who is the designed first-read in the red zone, a receiver
whose targets cluster in the opening drives — their share of their
team's *first* touchdown is systematically different from their share
of its touchdowns overall, and a uniform discount off anytime prices
cannot see it. The construction prices the two stages separately so
the script signal is in the model, not in the narrative.

**Stage 1 — which team scores first, and when.** From the sibling
team-total construction's distributions
(`NFL_TEAM_TOTAL_DIST_V1`, same pack) plus point-in-time
first-score rates: P(team T scores the game's first TD) ∝ T's
expected scoring rate in the opening segment, estimated from T's
point-in-time first-TD frequency (share of T's games in sample where T
scored first) shrunk toward the league rate with the Part 2 K = 3
form on game counts, and adjusted by which team receives the opening
kickoff **only when that is known pre-kickoff from a committed source**
(coin-toss outcomes are not known at entry-capture time on the
standing cadence; the construction therefore models first possession
as the league-average defer/receive mixture and says so — it does not
consume information the capture does not have).

**Stage 2 — who, given the team.** P(player p scores T's first TD |
T scores first) from p's point-in-time **first-TD share**: p's share
of T's first touchdowns over the sample (same sample rule as Part 2:
same-season prior games, role-gated — p must be an established
skill-position player on T's active roster per the week's committed
roster/depth records), shrunk toward p's share of T's *any* touchdowns
(the anytime profile — the model's prior for a player with thin
first-TD history), and that toward the positional league pool
(RB/WR/TE/QB first-TD shares). Two-level shrinkage, constants fixed in
the prereg draft (K1 = 3 games-scale on first-TD counts toward the
anytime share; the anytime share itself is the Part 2-style shrunk
estimate). Defensive/return first TDs are a single pooled outcome
class (`DEF/ST TD`) with its own point-in-time rate — DK's board
prices individual defensive players thinly or not at all, and the
class exists in the model so probabilities sum honestly; rows are
priced only for players DK actually lists.

**P(p first TD) = P(T first) × P(p | T first)**, renormalized over
the listed board + the DEF/ST class + the no-TD outcome (a game can
end without a touchdown; its point-in-time rate is in the model for
the same honesty reason).

**Settlement identity:** the first TD is credited by the official
play-by-play scoring attribution (the Oct 20 evidence layer's
contract: explicit credited player on the first TD event, including
defensive/return scores; never inferred from the passer). DK
settlement governs payment; any DK-vs-PBP attribution difference is
recorded against the row, never silently absorbed (the 2+ TD draft's
settlement rule, adopted).

## 3. Why no screen accompanies this design

The family's blocker of record is data, not imagination: canonical
coverage resolves first_td **NO_DATA — NO_VERIFIED_FIRST_SCORING_ATTRIBUTION**.
A calibration screen needs a point-in-time panel of (pre-game features
→ realized first scorer) — which is exactly the attribution panel the
evidence layer was built to make possible but which has not been
admitted: the panel requires a complete PBP feed with official
scoring-player attribution and observed-at discipline for every event
(the evidence build's own remaining-steps list, items 1–2). Running a
"screen" on unattributed or partially attributed data would
manufacture a number the program would then have to un-believe.
**Named missing steps, in order:**

1. **Attribution panel admission:** build the PIT first-TD panel from
   nflverse play-by-play (free, public): per game, the credited first
   scorer (player + team + type) from the scoring plays, joined to
   verified player IDs, with the panel's own hash pin and the
   evidence layer's refusal classes (missing scorer identity,
   incomplete PBP, out-of-order events) applied as panel exclusions,
   counted and reported.
2. **Calibration screen:** on that panel (2020–2025 design seasons),
   the §2 construction scored for calibration and log loss against
   two baselines fixed in advance: B1 = anytime-share-only model
   (stage 2 collapsed — the "uniform discount" the market is accused
   of, built from the model's own anytime shares); B2 = league
   positional pool only. Screen criteria fixed in the prereg draft
   (§1 there). A fail ends this construction (FAILED_SCREEN), it does
   not invite a re-tune.
3. **Capture expansion (lane):** the first-TD Yes board joins Capture
   Spec's per-game subset at entry and close (today it is
   comment-only material). Anytime-TD's board is already in the
   subset; this is a sibling board, added without touching ATD's.
4. Owner freeze of the prereg draft, naming the first counted slate.

Until steps 1–3 land: **DESIGN ONLY**, and the framework config
(`nfl_first_td.json`) carries `model_version: "UNPINNED"` (a sentinel no row can match, so every row is refused fail-closed).

## 4. CLV form (declared here so the prereg draft is short)

One-sided Yes board ⇒ the **locked anytime-TD CLV form** (adopted
from the frozen ATD test via the 2+ TD draft): CLV is the change in
the Yes price's **raw** implied probability, entry to close — no
de-vig exists on a one-sided board. Its known bias (book cut drift
counts toward the reading, most on longshots) is carried into every
readout, verbatim in effect. Selection: PICKED iff model probability
exceeds the entry Yes price's raw implied probability (the locked
ATD selection rule); every other priced row is PASS, is reported with
its own CLV read, and never enters the verdict sample.
