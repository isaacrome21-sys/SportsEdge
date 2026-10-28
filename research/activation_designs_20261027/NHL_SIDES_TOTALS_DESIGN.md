# NHL sides / totals — attempt-2 construction design + preregistration draft

**Status: DESIGN ONLY — preregistration DRAFT, not frozen. No clock, no
verified claim, no PLAY.** NHL re-enters under the owner's explicit ruling
of Oct 27, 2026 (23:04 CT) lifting the pause. This is attempt 2, scored by
version: attempt 1's no-edge verdict stands on the record unchanged, and
the #1249/#1253 generation — including the totals path that fit on final
scores and added OT/SO a second time — is retired. It is not shipped,
quiet-fixed, or re-scored here.

## Two stages, in order — Stage A is already locked and is not rewritten

**Stage A (accuracy, locked Sep 29, 2026 — cited, not amended).** The
home-ice v2 pre-lock (`docs/research/nhl_home_ice_v2_prelock.md`): fit =
2024–25 regular season, regulation goals only, home-ice free; validate
ONCE on 2026–27 regular-season games Oct 8 – Nov 30, 2026; score moneyline
|gap| and Brier vs coin and vs the 2024–25 home-win rate, puck line −1.5
|gap|, totals 5.5/6.5 |gap| and Brier; October numbers are a first read
only; the one-shot verdict is November 30, 2026 on the pre-lock's own pass
line. This draft changes none of that. If Stage A fails, Stage B below
does not run and this construction returns to design.

**Stage B (market validation — this draft's contribution).** Accuracy
against naive baselines is not an edge. Stage B tests the same construction
against the market and against the program's existing NHL model, under the
Oct 27 validation law.

## Construction (attempt-2 v1, bound by this draft)

1. **Rates from shot-level xG.** Team offensive/defensive goal rates built
   from MoneyPuck shot-level expected goals (the data foundation named in
   the `nhl-second-attempt` goal record), strictly prior games only,
   exponentially weighted with a half-life fixed at freeze, shrunk toward
   league rates by games played. Goaltender adjustment from the confirmed
   starter's strictly-prior save performance vs shot quality faced;
   unconfirmed starter = the team's weighted starter/backup blend, and the
   row is flagged degraded (starter identity is not availability — the
   blend is used until a sourced confirmation exists, per the program's
   evidence rule).
2. **Regulation-first simulation.** Regulation goal distributions per team
   (Poisson with a dispersion parameter fit on design data), then OT/SO
   resolution layered on the regulation result — the exact inverse of
   attempt 1's double-count: the sim's regulation mean is a regulation
   mean, and OT/SO probability mass is added once, from the regulation
   tie probability.
3. **Outputs.** Moneyline (incl. OT/SO), puck line −1.5/+1.5, game totals,
   and regulation-only markets, all from the one simulation.

## Inputs (with their honest admission states)

- MoneyPuck shot-level data — named foundation in the goal record and
  referenced in-repo (cross-checks vs the official API documented in
  `docs/nhl_api_research_source_20261024.md`, incl. the ±1 shootout-goal GA
  convention). No standalone admission record was found in-repo: **an
  admission record (or a derived-xG route from official play-by-play) is
  owed before any fit under Stage B.** Hockey-Reference is likewise named
  in the goal record and is NOT yet wired in-repo; it is a cross-check
  candidate, not an input, until admitted.
- Official NHL API (api-web.nhle.com) — admitted as a research/archive
  collector (`scripts/collect_nhl_api.py`), envelopes marked
  `pricing_input: false`. It supplies schedule/results/rosters ground
  truth for design and grading. Any pricing-path role requires a separate
  source-role decision; this draft does not grant it.
- The public boxscore baseline (`sportsedge/sports/nhl/public_baseline.py`)
  — the EXISTING MODEL comparator for Stage B (development baseline;
  explicitly non-xG, never relabeled).
- Forward DraftKings captures under the standing cadence (T-1H + FINAL)
  with #2792 receipts — the market baseline. No historical NHL closing
  archive is claimed.

## Stage B validation protocol (fixed in advance; one look)

Precondition: Stage A verdict = PASS on Nov 30, 2026, and NHL capture
flowing under the restart pack. Window: Dec 1, 2026 – Jan 31, 2027
regular-season games with paired DK captures (ML, puck line, total from
the FINAL write). Candidate: attempt-2 v1 as specified above, fitted only
on games before Dec 1 (MoneyPuck design fit) and updated strictly forward.
Comparators on identical games: (a) the public boxscore baseline's
probabilities; (b) DK closing no-vig probabilities. Primary metrics: log
loss on moneyline; log loss on the total (distribution evaluated at the
offered line). PASS = candidate beats BOTH comparators on moneyline log
loss AND does not lose to either on totals log loss, paired one-sided
significance at alpha = 0.05 / k, moneyline calibration slope within
[0.8, 1.25]. One look, Feb 1, 2027. Puck line is scored and reported,
not gated (its |gap| discipline lives in Stage A). CLV/ROI graded and
reported; not gates.

## Activation state on landing

DESIGN ONLY. Stage A's locked window is already running on the calendar;
nothing in this draft alters it. Stage B additionally waits on: MoneyPuck
admission, the xG rate fit artifact (no frozen NHL rate artifact exists on
main today — the card correctly reports NO_MODEL until one does), and
capture restart.

## Blockers

- MoneyPuck admission record owed; Hockey-Reference not wired (cross-check
  only until admitted).
- No frozen rate artifact: construction code + fit are build work owed
  before Stage B's window opens Dec 1.
- Capture restart dependency (restart pack, separate workstream).
