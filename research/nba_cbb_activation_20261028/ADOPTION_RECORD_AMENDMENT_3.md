# ADOPTION RECORD — CBB 1H Amendment 3 (§2 design-screen spec completion, G-1H-1..6)

**Status: ADOPTION ACT. Prepared, not in force.** Under Amendment 3 §9,
adoption is recorded **by merge** of the PR carrying it, after independent
review closes on that exact head and the owner's authorization is recorded.
It is never recorded by the draft's landing, a commit, or a review comment.
Until that merge the CBB first-half family stays DESIGN ONLY, with no
construction run and no clock; its screen stays NOT_EXECUTABLE on the
attempt-1 record (PR #2911).

- **Adopted document:** `research/nba_cbb_activation_20261028/AMENDMENT_3_DRAFT.md`,
  **sha256 `b284443fe154e57418425c12209a0cc99e3e7a74100a6eb2529077e9961127e0`**
  (on main via PR #2913, merge `be8d19a1e`). Its text is not edited.
- **ADOPTION-REVIEW FLAG 1, confirmed by name: Reading A.** The baseline is
  the climatology of the 1H quantities themselves: the strictly-prior league
  mean of the actual 1H total and 1H margin, fitted walk-forward on the §6
  fitting universe (§2 of the amendment).
- **Owner authorization (verbatim):** Owner Isaac ruling, Oct 29 2026,
  relayed in chat: **"CBB 1H Amendment 3: Adopt with Flag 1 Reading A."**
  Also recorded on PR #2913, comment 6509461869.
- **Effect on adoption:** G-1H-1 through G-1H-6 stand supplied. Adoption
  runs nothing, freezes nothing and counts nothing. The screen then runs as
  **attempt 2** on its own record.

## Sequencing

This PR is **stacked on the Amendment 2 adoption PR** and should merge after
it. Amendment 3 cites Amendment 2 (§2 discusses its game-cluster form), and
the owner ordered the CBB acts that way.

## Remaining before the merge

- [ ] The Amendment 2 adoption PR merges first, or the owner rules otherwise.
- [ ] Independent review closes on this PR's exact head.
- [ ] Owner merge, which is the recording act.
