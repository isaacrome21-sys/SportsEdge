# DESIGN — NFL quarters / halves: `NFL_PERIOD_SHARE_V1` (FAILED_SCREEN) and the family's path

**Status: DESIGN ONLY.** The construction specified below was screened
and **failed its screen**; it does not advance. This document records
the design, the failure, and the family's named missing steps.
Family before this pack: NO_CONSTRUCTION (period lines captured inside
issue comments only; no prereg). PAPER / research only.

## 1. Scope — which period markets, and which are not here

In scope: **quarter markets (Q1–Q4)** — spread, total, moneyline, team
total per quarter — and **first-half markets (1H)** — spread, total,
moneyline, team totals. All are regulation-defined (a quarter's and a
first half's scoring is complete at the period boundary, overtime
never enters), which keeps settlement unambiguous.

Out of scope: **second-half (2H) lines.** A 2H line is priced at
halftime, with the first half known — it is an in-play price, and DK's
2H settlement includes overtime. 2H belongs to the live family's
scope (`NFL_LIVE_CAPTURE_PILOT_SPEC_V1.md`), not to a pregame family.
The design screen computed a regulation-2H bucket as a diagnostic
only; no 2H market is declared in this family's config.

## 2. The market and why it might be wrong

Period lines are the least independently-modeled prices on an NFL
board. Desks derive them from the full-game lines by fractional
decomposition — a quarter is priced near a quarter of the game — with
modest adjustments. Two systematic facts argue the decomposition is
beatable in principle: **opening-script efficiency is a real team
trait** (coordinators script the first ~15 plays; some offenses are
measurably better in Q1 than their full-game rate), and **Q4 scoring
is game-state scoring** (trailing teams score faster and allow more;
leading teams trade yards for clock), so a quarter's expected points
depend on the *distribution of game states*, not on a fixed share of
the total. The construction below tested only the first of those two
claims (team period-share profiles). The screen says that claim, at
this resolution, is not enough. The second claim is the v2 direction
in §5 — stated here so the failure is read correctly: what failed is
share-profile modeling, not the proposition that period lines are
decomposition prices.

**Retired predecessors, not resurrected:** `sportsedge/market_coverage.py`'s
quarter totals and quarter team totals (declared-fraction margin-proxy
means) were built, **failed their harness vs naive baselines**
(NFL quarter totals Brier 0.2409 vs naive 0.2239; quarter team totals
0.2355 vs 0.2216), and are gated NOT_WIRED_WITH_REASON. This design
shares no machinery with them: they split a full-game margin proxy by
declared fractions; this construction modeled team period scoring
directly from point-in-time period outcomes. It failed on its own
terms, separately. (The same file's quarter spread/ML pricers are
IN_BUILD research and are Lane A surface, not this family's
construction.)

## 3. The construction as screened — `NFL_PERIOD_SHARE_V1`

For team T in a game with team-total mean μ_T from
`NFL_TEAM_TOTAL_DIST_V1` (sibling design, same pack):

- **Period shares** s_T,q for q ∈ {Q1..Q4}: from T's point-in-time
  sample (same sample rule as the team-total construction:
  same-season priors supplemented by prior-season games to 8), with
  points-scale shrinkage toward the league's point-in-time shares
  L_q: s_T,q = (T's sample period-q points + 150·L_q) / (T's sample
  total points + 150).
- **Period means:** μ_T,q = μ_T · s_T,q; 1H mean = μ_T,Q1 + μ_T,Q2.
  Period distributions: the team-total NB form scaled by share (the
  design's stated distribution layer).
- Baselines: B0 = μ_T · L_q (league shares — the market's
  decomposition logic with league-average shares); B1 = flat split
  (0.25/quarter, 0.50/half — the unfitted convention of
  `sportsedge/team_half_pricing.py`, the existing Lane A derivative).

## 4. Design screen — FAILED_SCREEN (recorded, not tuned away)

2023–2025, n = 1,632 team-games, criteria fixed before the run (full
record: `SCREEN_REPORT.md`): pooled MAE candidate 4.444 vs B0 4.423 /
B1 4.469; the candidate beat B0 in only 2 of 6 buckets. **Team period
shares at an 8-game sample do not beat league shares.** Diagnosis, for
the v2 designer: a team's quarterly points in ~8 games are a few dozen
scoring events — the share estimate is noise; and Q4 (the worst
bucket, 4.314 vs B0 4.257) is state-driven, as §2 says. No re-run with
different shrinkage, caps, or buckets was performed; per program law a
failed construction returns only as a new version under a new design,
and the screen's seasons are seen data in any case.

## 5. The family's path — named missing steps, in order

1. **Capture expansion (lane).** Quarter and 1H lines are today
   captured only inside the line-3 HTML comment of each game issue,
   verbatim and unpriced. A period family needs them as priced body
   material: entry and close, both sides, timestamped, under the
   #2792 receipt discipline — added to Capture Spec's per-game subset
   for the period board. Without paired entry/close captures there is
   no baseline and no test, whatever the model.
2. **Intake-grammar extension (lane).** The NFL parser reads ML,
   Spread, Total, TeamTotal, and Prop lines
   (`sportsedge/nfl_lines_intake.py`, strict_unknown=True); a priced
   period line in a body today fails the whole game. Period line
   forms (e.g. `Total 1Q 10.5 -110 -110`) need grammar, parser tests,
   and the comment-material migration in step 1 to land together.
3. **A v2 construction design** — drive-level and game-state
   conditioned: period scoring simulated from drive outcomes with
   state-dependent pace/urgency (two-minute drill, prevent defense,
   clock bleed), so Q4 is modeled from the distribution of states the
   game can be in, not from a share. Its design screen runs on the
   PBP period panel this pack built (the panel builder in
   `screen_nfl_activation_v1.py` is reusable; the panel's integrity
   checks are in `SCREEN_REPORT.md`). Only a v2 that passes its own
   pre-committed screen earns a freeze proposal.
4. The preregistration draft in this pack
   (`PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md`) already fixes the
   family's test terms — per-market verdicts, gates, close rules — so
   that when a construction passes a screen, the freeze decision is
   about the construction, not about terms written after seeing
   forward data.

Until steps 1–3 land, the family's honest state is **DESIGN ONLY**,
and the framework config (`nfl_period_lines.json`) is declared with
`model_version: "UNPINNED"` — a sentinel no row can match; there is no version to pin, and the framework
refuses to price a family whose version is undeclared.
