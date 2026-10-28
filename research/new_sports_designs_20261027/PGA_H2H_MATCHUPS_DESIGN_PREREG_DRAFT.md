# DESIGN + PREREGISTRATION (DRAFT) — PGA Tour tournament matchups (H2H): strokes-gained distribution simulation vs DraftKings matchup prices

**Status: DESIGN + DRAFT PREREGISTRATION — NOT FROZEN, NOT IN FORCE.**
Prepared Oct 27, 2026 under the owner's directive adding PGA, UFC and DWCS to
the program with every family carried toward clock-running / armed / screening.
**Freezing is the owner's act. No event, row, or matchup counts toward this
test before its freeze.** Nothing in this document starts a clock, verifies
anything, or creates a PLAY. All staking language is PAPER / research only.

Family: `PGA / TOURNAMENT_MATCHUPS_72H` (flagship for PGA).
Activation state today: **NO_CONSTRUCTION → DESIGN ONLY** (this document).
Sibling documents: `UFC_MONEYLINE_DESIGN_PREREG_DRAFT.md`,
`DWCS_DESIGN_NOTE.md` (same directory).

## 1. The market

DraftKings posts head-to-head tournament matchups (72-hole, and per-round) for
PGA Tour events, priced as two-way moneylines, alongside outrights and
top-5/10/20 finish markets. *(Market-surface statement: general knowledge —
DraftKings' public sportsbook pages are login-walled to text access, and golf
is not yet in this repo's capture records; the capture-scope addition in §7
must confirm the exact DK surface from rendered pages before any freeze.)*

## 2. Edge mechanism

Matchup prices are a by-product of field-wide pricing: books set them from
outright markets and syndicated models whose player ratings update slowly and
weight long-run skill over current form and course fit. This construction
builds its own player scoring distributions from free round-level data —
recency-weighted strokes-gained skill, a same-course history adjustment, and
player-specific scoring variance — and simulates the full field, so a matchup
probability reflects (a) who is actually playing well *now*, (b) who fits
*this* course, and (c) matchup-relevant variance (a high-variance player is
worth more against a favorite over 72 holes than a steady one). The claimed
edge is the disagreement between that simulation and prices derived from
slower, field-average assumptions. If the disagreement is not real, §6 is
designed to say so cheaply.

## 3. Inputs — every input tiered, design viable on FREE inputs alone

| Input | Source | Tier | Admission state |
|---|---|---|---|
| Round scores + per-round strokes-gained (OTT/APP/ARG/PUTT) by player/event, 2004–present | DataGolf free **past-results pages** (verified Oct 27, 2026: event pages publish round scores, SG category values, and outright Open/Close odds) | FREE web | NOT YET ADMITTED — needs a pin + hash admission like the CBB substrate |
| Season SG category stats (cross-check) | pgatour.com stats pages (public web; DataGolf's own FAQ names pgatour.com as its round-level source) | FREE web | NOT YET ADMITTED |
| Weekly player rankings archive (reference prior) | DataGolf Rankings page — free, weekly snapshots listed back through the 2000s (verified Oct 27, 2026; current snapshot Oct 26, 2026) | FREE web | NOT YET ADMITTED |
| Official world rankings (second reference) | owgr.com weekly rankings | FREE web | NOT YET ADMITTED |
| Event fields, tee times, course identity | pgatour.com / DataGolf free pages | FREE web | NOT YET ADMITTED |
| DataGolf API: pre-tournament prediction archive, **historical matchup / 3-ball odds**, live finish probabilities | DataGolf API (membership tier) | **PAID — OWNER DECISION** | NOT PURCHASED; design must not depend on it |
| Shot-level ShotLink data | PGA Tour partnership feeds (DataGolf holds a partnership; not sold as a public raw feed) | NOT AVAILABLE | Excluded |

**Free-only verdict: YES for the construction.** Features and outcomes are
fully computable from the free round-level record. What free sources do
**not** contain is a historical archive of matchup *prices* — see §6.

## 4. The construction (frozen at freeze; any change = new version, new clock)

1. **Skill**: per player, expected SG-total per round = shrinkage-weighted
   mean of round SG over the trailing 24 months, recency-decayed (half-life
   6 months), shrunk toward the field mean by rounds played; minimum
   40 measured rounds else the player is UNPRICED (no silent priors).
2. **Course fit**: additive adjustment from the player's prior editions at
   the same course (same composite key rule as §5), shrunk hard toward 0
   (prior weight equivalent to 8 rounds); no adjustment with <2 prior
   editions.
3. **Variance**: per-player residual round-score SD (same window), floored
   at the field's 10th percentile and capped at the 90th; plus a shared
   course-day condition draw per round (weather/field correlation).
4. **Simulation**: 100,000 simulated events; each player's four rounds drawn
   from his distribution (missed-cut players stop after R2 per the simulated
   cut); matchup probability = P(A finishes ahead of B), ties handled per
   DK house rules for the market as captured — the priced comparison uses
   the two-way de-vigged DK pair and the simulation's win/loss split
   conditional on a non-tied finish, with the tie mass reported.
5. **Output**: probability + PLAYABLE-TO price per matchup. No market price
   ever enters the feature vector (program law).

## 5. Point-in-time rules (hard)

- Features use only rounds **completed before the event's first tee time**.
  In-event rounds are never features for 72-hole markets.
- **Composite `(event_id, year)` keys everywhere** — the exact lookahead
  class that invalidated a published +6.0% ROI golf matchup backtest
  (repo `RECOMMENDATIONS.md` §5: the source reused `event_id` across annual
  editions; ~47% of one year's bets were priced on future data). Any cache
  or fixture keyed by event alone fails review.
- Backtest features must be reconstructed from round data dated before the
  event — never read from a page whose current state reflects post-event
  updates; archived snapshots or dated reconstruction only.
- Withdrawals before R1 void the matchup row (excluded, counted); a WD
  after R1 grades as captured by DK rules and is reported separately.

## 6. Validation protocol — two legs, criteria fixed in advance

**Leg 1 — historical calibration screen (executable on free data).**
Chronological: fit ≤2022 → test 2023; refit ≤2023 → test 2024; refit ≤2024
→ test 2025. All 72-hole matchups between two priced players, outcomes from
the free results archive. References: (a) a market proxy — pairwise
probabilities implied by the DataGolf past-results **outright Close odds**
(field-normalized); (b) an OWGR-points-implied reference rating.
**Leg 1 PASS requires ALL of:** pooled H2H log loss strictly better than
both references; calibration error (mean |predicted − realized| in
probability deciles) ≤ 0.05; ≥ 1,500 test matchups per season.
*Disclosed limit: outright closes are a proxy, not matchup closes. Leg 1
passing earns SCREEN_PASSED / ARMED — it is an entry ticket, not a verdict.*

**Leg 2 — market verdict (forward DraftKings capture; the actual test).**
There is **no free archive of historical DK (or any book's) closing matchup
prices**: DataGolf's API carries historical matchup odds behind its paid
tier, and the free record carries outright Open/Close only (majors' outright
closes also appear via SportsOddsHistory on Covers). The baseline is
therefore **forward capture** under the standing lane cadence adapted to
golf (matchup board captured pre-R1 and at each round's close).
**Leg 2 PASS requires ALL of, on the frozen construction:** ≥ 25 events
AND ≥ 500 graded matchup rows; CLV > 0 vs the final pre-R1 capture;
ROI > 0 at captured prices; log-loss delta vs the DK no-vig close ≤ 0.0.
Primary test for multiplicity (§7): the Leg-2 log-loss delta vs close.

## 7. Multiple testing, capture scope, blockers

- **α = 0.05 / k**, k = the number of families validated program-wide on
  the verdict date (owner's standing policy); this family's primary test
  is the single Leg-2 log-loss comparison named above. Secondary metrics
  are reported, never gated on.
- **Capture gap (blocker for Leg 2):** golf is not in the lines lane.
  Needs: DK golf board in the 36-hour scan (events run Thu–Sun; matchup
  boards post Mon–Wed), T-1H/FINAL-equivalent marks redefined for a
  four-day event, and a `[PGA LINES]` parser grammar (matchup lines are
  not team-sport lines). Lane work, not model work.
- **Admission gap (blocker for Leg 1):** the DataGolf free archive and
  PGA Tour stats need pin/hash admissions before any screen runs on them.
- **Owner-decision flag:** DataGolf API membership would replace Leg 2's
  forward-only market baseline with a historical matchup-odds archive and
  shorten time-to-verdict by seasons. Not purchased; the design stands
  without it.

## 8. Remaining PGA families — one-line sketches

- **Outrights** — same field simulation's win probabilities; the only PGA
  family with a free historical price archive (DataGolf outright
  Open/Close), so its calibration screen is fully executable historically;
  verdict still forward.
- **Top-5 / Top-10 / Top-20 finishes** — simulation tail probabilities off
  the flagship engine; no free historical prices exist → forward capture
  only, own prereg per finish band.
- **3-balls & round matchups** — round-level variant of the flagship
  (single-round distributions, in-event rounds < r only); separate clock,
  forward only.
- **First-round leader** — R1 tail of the sim; variance-dominated, thin
  prices; deprioritized until the flagship passes.
- **Make / miss cut** — cut-line distribution from the field sim; forward
  only.
- **Live in-play** — NO_CONSTRUCTION until the pre-tournament flagship
  passes; needs a hole-by-hole feed this program does not have.
- **SGP** — legs only; no SGP construction until its leg families validate
  (program law).

*End of draft. Prepared by Rocky (Muse) overnight Oct 27–28, 2026.
Evidence states: DataGolf free surfaces and rankings archive verified by
direct read Oct 27, 2026; DK golf market surface = general knowledge,
flagged for capture-scope confirmation; all other claims are design
statements, not results.*
