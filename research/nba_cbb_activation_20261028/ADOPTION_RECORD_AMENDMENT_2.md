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
- **Owner authorization (verbatim):** Owner Isaac ruling, Oct 29 2026,
  relayed in chat: **"CBB Amendment 2: Adopt with pooled reading."** Also
  recorded on PR #2906, comment 6509461063.

## ⚠ Reading to confirm at review — "pooled" vs the text of §2

The owner's ruling names a **pooled reading**. Amendment 2 does **not** name
pooled-vs-per-market as an explicit adoption flag, and its §2 (G-2 interval)
reads **per-market** as written: "Efficiency: one statistic for SPREAD rows
and one for TOTAL rows; the leg passes only if **each** named market's
interval clears … the screen read its leg the same per-market way." The
provenance table marks the per-market application as a NEW narrow
completion.

So "pooled" cannot be adopted as a reading of §2 without changing a term.
Under §8, a conflict is "itself recorded as a defect for the adoption's
review to resolve". The reviewer and owner must settle one of these by name
**before** the merge:

- **(P)** Pooled, a term change: one statistic over SPREAD+TOTAL rows for
  the efficiency family's accuracy leg. This needs the changed term written
  out in this record and reviewed.
- **(M)** Adopt §2 as written (per-market), and record that the ruling's
  "pooled" referred to something else, for example the σ̂ derivation in §1.2,
  which uses the screens' **pooled** candidate MAEs.

This record does **not** silently pick one. As prepared, it adopts
Amendment 2 at the pin above and carries the owner's "pooled" ruling,
**pending that confirmation**.

## What adoption does not do

It freezes nothing and counts nothing. Each family's freeze act stays a
separate prospective act. Its prerequisites are still owed: data gate (iii),
capture delivery proven on the opening slates, and the forward-runner build
(finding F-1).

## Remaining before the merge

- [ ] Reviewer/owner confirm (P) or (M) above by name.
- [ ] Independent review closes on this PR's exact head.
- [ ] Owner merge, which is the recording act.
