# ADOPTION RECORD — CBB Amendment 2 (§5 forward-term completion: G-1 pick rule, G-2 interval, G-3 close validity)

**Status: ADOPTION ACT. Prepared, not in force.** Under Amendment 2 §8,
adoption is recorded **by merge** of the PR carrying it, after independent
review closes on that exact head and the owner's authorization is recorded.
It is never recorded by the draft's landing, a commit, or a review comment.
Until that merge both families remain DESIGN ONLY, `verified_play = false`,
PAPER / 0u, and nothing counts.

- **Adopted document:** `research/nba_cbb_activation_20261028/AMENDMENT_2_DRAFT.md`,
  **sha256 `25be46029ca1933e1a2eb7d7aa6a858928f3879a254285e90a0b9bf1270d926a`**
  (on main via PR #2906, merge `5e043a269`). Its text is not edited; this
  record adopts it by reference and pin.
- **Families:** `CBB_TORVIK_EFFICIENCY_V1` (freeze package PR #2903) and CBB
  team totals (freeze package PR #2904). On adoption, gaps G-1, G-2 and G-3 in
  both packages' PREREG_FINAL §8 stand supplied by Amendment 2. The
  PREREG_FINAL pins are unaffected.
- **Owner authorization:** Owner Isaac ruling, Oct 29 2026, relayed in
  chat: "CBB Amendment 2: Adopt with pooled reading." (recorded on PR #2906,
  comment 6509461063). That ruling's reading was then **settled by the
  delegated owner adoption reading posted on PR #2906 at 5:07 PM CT, Oct 29
  2026: "PER-MARKET, NOT POOLED."** Its text: "For CBB_TORVIK_EFFICIENCY_V1,
  the spread and total accuracy intervals/legs must each satisfy the frozen
  §5 bar on their own; a pooled improvement cannot mask a failing market. CBB
  team-total accuracy remains its own separate family/statistic. Carry the
  Amendment 2 §2 per-market reading into a dedicated prospective adoption
  act, with no weakened thresholds, no backfill."

## Reading adopted — per-market (§2 as written)

This act adopts Amendment 2 **exactly as written**. No term is changed. §2
(G-2) reads: "Efficiency: one statistic for SPREAD rows and one for TOTAL
rows; the leg passes only if **each** named market's interval clears." Team
totals: one statistic over team rows, as its own family. The earlier
"pooled" wording is superseded by the delegated per-market reading above. No
pooled statistic is adopted anywhere.

## What adoption does not do

It freezes nothing and counts nothing. Each family's freeze act stays a
separate prospective act. Its prerequisites are still owed: data gate (iii),
capture delivery proven on the opening slates, and the forward-runner build
(finding F-1).

## Remaining before the merge

- [x] Pooled-vs-per-market settled: per-market (delegated owner reading, #2906, Oct 29 5:07 PM CT).
- [ ] Independent review closes on this PR's exact head.
- [ ] Owner merge, which is the recording act.
