# PILOT SPEC — CFB SGP + Live In-Play V1

# SPEC ONLY. NEITHER PILOT IS ARMED BY THIS DOCUMENT.

- Status: SGP — `PILOT_SPEC_DEPENDENT_NOT_ARMED`. Live —
  `PILOT_SPEC_NOT_ARMABLE` on current infrastructure (blockers named
  in §3). Date drafted: 2026-10-27.
- Why a joint spec: both families price **joint / state-dependent**
  outcomes rather than a single pregame line, and both are blocked
  not by ideas but by dependencies — SGP on its leg families, live on
  capture infrastructure that does not exist. This spec names the
  dependencies precisely so "not yet" is a checklist, not a mood.

## 1. SGP — `CFB_SGP_JOINT_PILOT_V1`

### 1.1 What an SGP price is

A same-game parlay price is a **joint probability** over legs from
the same game (e.g. team total over + QB passing yards over + game
total under). DK computes it with its own correlation model and a
margin; a construction earns anything here only by estimating the
joint distribution *better than the book's implied joint* — which
requires (a) leg distributions that have individually survived
validation and (b) a correlation structure estimated from data, not
assumed independence (independence is the one specification known in
advance to be wrong: QB yards and team scoring are strongly
positively coupled; game total and team totals likewise).

### 1.2 Construction sketch (for the pilot, when armed)

- Leg distributions: taken **only** from CFB families that have
  passed their own preregistered screens under this program
  (team totals, period lines, game props, player props if a
  construction ever exists, and sides/totals only if the G3 audit
  ever reopens them — it has not).
- Dependence: a Gaussian-copula layer over leg marginals, with the
  correlation matrix estimated walk-forward from cfbfastR PBP
  residuals (per leg-pair, shrunk toward the pooled estimate;
  estimation window and shrinkage fixed at pilot build, recorded in
  the pilot run record). NCAA-specific couplings (blowout game
  scripts suppressing passing volume, garbage-time rushing) are
  reported as named residual risks, not modeled silently.
- Output: joint probability → fair price for a captured DK SGP
  offer; comparison is against the offer's implied probability
  (with the book's SGP margin stated, since SGP offers are not
  two-sided and carry no no-vig pair — comparisons are labeled
  `VS_OFFER_IMPLIED`, never CLV).

### 1.3 Arming gate (all required)

1. At least **two** CFB leg families with `SCREEN_PASS` (or a frozen
   forward `BEATS_MARKET`) on record under this program.
2. The copula estimator validated as a **diagnostic** on historical
   PBP: joint-event Brier score beats the independence assumption on
   held-out seasons (walk-forward), reported per leg-pair class.
3. A captured-offer substrate: DK CFB SGP offers captured verbatim
   (legs, combined price, timestamp) under the lane's comment
   discipline for ≥4 slates — the pilot prices only offers that
   actually existed.

### 1.4 Pilot phase (when armed)

Shadow only: for each captured SGP offer whose legs all come from
qualifying families, log model joint probability vs offer implied
probability and the settlement. No picks, no card rows, no clock.
Exit report after ≥4 shadow slates: calibration of joint
probabilities (Brier vs offer-implied), per leg-pair class, labeled
SHADOW. A freeze request may follow only from that report, under a
separate preregistration written for SGP itself.

**Honest state:** legs qualifying under §1.3.1 today: **zero** (team
totals is DESIGN ONLY; the rest are earlier still). The pilot is
therefore correctly NOT ARMED, and its distance from arming is
exactly the leg families' distance — no separate SGP effort can
shorten it.

## 2. Live in-play — `CFB_LIVE_STATE_PILOT_V1`

### 2.1 What a live construction would be

A state-conditional model: given score, clock, down/distance, field
position, and possession, the distribution over remaining scoring —
yielding live win probability and live total/spread fair prices to
compare against DK's in-play board.

### 2.2 Infrastructure blockers (each one sufficient to block arming)

1. **No live play feed is admitted.** cfbfastR PBP is post-game.
   A live construction needs a play-by-play feed with in-game
   latency (ESPN live endpoints or CFBD live data are candidates an
   admission audit has not yet evaluated for timestamp integrity —
   and timestamp integrity *is* the admission question for live).
2. **No in-play capture scope exists.** The lines lane is pregame
   only (T-1H / FINAL marks; never edit after start — standing
   ruling). In-play lines move continuously; capturing them is a
   new lane scope with its own cadence and receipts design, not an
   extension of the pregame grammar.
3. **No live baseline discipline exists.** A live verdict needs a
   definition of the contemporaneous market at decision time
   (quote timestamp vs state timestamp alignment) that no document
   in this program has written yet. Writing it is part of the pilot
   design task, after blockers 1–2 fall.

### 2.3 What may run today (diagnostic only)

Historical PBP calibration diagnostics: fit the state-conditional
scoring model on past seasons' PBP (walk-forward) and report
next-score / remaining-points calibration vs naive state baselines.
Labeled `DIAGNOSTIC` wherever reported. It can kill a bad state
model cheaply. It validates nothing against a market, earns no
clock, and its numbers are never presented beside live prices.

### 2.4 Illinois exclusion

Identical to the rest of this pack, and it binds the diagnostic too:
Illinois-college games are excluded from fitting and scoring
(`ILLINOIS_COLLEGE_EXCLUDED`).

## 3. What this spec does not do

No construction is built, no pilot is armed, no capture scope is
changed, no clock exists, nothing is priced. When a blocker's state
changes (a leg family passes; a live feed is admitted; a live
capture scope is separately designed and approved), the affected
pilot's arming is requested as its own act with its own review —
this spec is the checklist that request is checked against.
