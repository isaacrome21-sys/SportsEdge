# SCREEN REPORT — CBB first-half lines (1H spread / 1H total), design screen attempt 1

**Verdict: NOT_EXECUTABLE — `SCREEN_SPEC_INCOMPLETE_1H`.**
Family state after this record: DESIGN ONLY — no construction run, no
share fitted, no clock, nothing frozen. Evidence class: DESIGN.

**Design executed (as written, nothing edited):**
`research/nba_cbb_activation_20261028/CBB_TEAM_TOTALS_1H_DESIGN.md` §2
(PR #2843), composed with the parent design
`CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md` §§1–3.

## 1. What changed since the last record of this family

PR #2892's screen record carried this family as **NOT_EXECUTABLE —
`PBP_PREREQUISITE_MISSING`**: the design's one named prerequisite, a
full-tuple-pinned, schema-verified hoopR play-by-play manifest, did
not exist. PR #2901 has since landed that admission (9 season files,
2015–2023; Method A running-score derivation admitted at 33/33 against
ESPN's published linescores; Method B refused; the final-agreement
consumer gate binding). **The data prerequisite is satisfied. The
screen still cannot run — the blocker moved from the data to the
spec.** That is this packet's finding, and it is a different refusal
from #2892's, recorded as a new code rather than a re-run of the old
one.

## 2. What §2 specifies — and what it does not

§2, headed "Screen shape (once the prerequisite lands)", states:
the candidate is the parent full-game expectation × a first-half
share (one share for team points, applied to margin and total alike);
the share is fitted on seasons strictly before each scored season;
1H outcomes are derived from the pinned PBP itself; the metrics are
1H-total MAE and 1H-margin MAE vs a naive half-share climatology
baseline, under the DESIGN-evidence label.

Measured against what the executed sibling screens ran on — parent §3
for spread/total (seasons, walk-forward protocol, two constructed
baselines, and the bar "Design pass = CI upper bound < 0 against both
baselines on both legs", season-block bootstrap) and §1 of this same
design for team totals (which explicitly imports §3's protocol and
names its leg's two baselines and its own CI) — §2 leaves six terms
unstated. Each is a term a runner would have to invent, so each is
recorded as a gap instead (full probe evidence in
`screen_result.json` → `spec_audit`, reproducible via
`audit_screen_spec.py`):

| Gap | Missing term |
|---|---|
| **G-1H-1** | **Verdict rule.** No CI test, threshold, or DESIGN_PASS condition for either 1H leg. Parent §3's bar is written for the spread/total legs; §2 does not import it. |
| **G-1H-2** | **Baseline construction.** "Naive half-share climatology" is a name, not a forecast: what full-game expectation it scales and how its share is estimated are unstated. |
| **G-1H-3** | **Share estimator.** Mean of per-game ratios vs ratio of sums; league-wide vs per-team; overtime treatment; fitting universe (final-gated PBP vs all PBP) — all unstated. |
| **G-1H-4** | **Scored seasons.** §2 names no span. Pinned PBP starts 2014-15, so under strictly-prior fitting the first season's status (scored vs fit-only) is undecided in the text. |
| **G-1H-5** | **Inference procedure.** No bootstrap design, resample count, or seed for the 1H legs. |
| **G-1H-6** | **Universe composition.** Parent three-way-agreed universe ∩ PBP final-agreement gate, vs schedule universe under the PBP gate alone — never chosen in the text. |

## 3. Criteria

| Criterion | Result |
|---|---|
| 1H-total MAE vs naive half-share climatology | **NOT RUN** (G-1H-1, G-1H-2) |
| 1H-margin MAE vs naive half-share climatology | **NOT RUN** (G-1H-1, G-1H-2) |

No MAE is reported for any leg, because no lawful leg exists to
compute one under. No share was fitted; no fixture was priced or
scored; Method B was not used anywhere.

## 4. Fixture universe (what the data would have offered)

From the PR #2901 admission manifest's coverage block, recomputed by
the audit script: 52,126 schedule games in span; 48,623 with PBP;
3,503 NO_DATA (no PBP); **47,903** passing the binding Method-A
final-agreement gate. The parent screens' three-way-agreed universe
was 26,553 fixtures (#2891/#2892) — whether the 1H universe is that
set under the PBP gate is exactly G-1H-6. The Illinois-college
exclusion binds any future run identically; its count inside the 1H
universe was not computed, because the composition it would be
computed on is undefined. **Scored this attempt: 0** — the honest
count for a NOT_EXECUTABLE screen, not a data failure.

## 5. What would unblock

A design amendment for the 1H family supplying the six terms — the
same instrument that closed the sibling families' forward-term gaps
G-1/G-2/G-3 (Amendment 2, PR #2906) — adopted as the owner's recorded
act. This packet proposes none of the six terms; proposing them inside
a screen run would be inventing the test the construction is graded
against.

## 6. Non-effects

No criterion, threshold, or leg of any design was edited; no other
family's record was touched (the #2892 first-half block stands as
executed at its run time — superseded only as to its stated reason);
no freeze, clock, or play eligibility arises from this record.
