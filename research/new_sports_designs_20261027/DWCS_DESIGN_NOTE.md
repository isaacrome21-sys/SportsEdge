# DESIGN NOTE — DWCS (Dana White's Contender Series): no flagship construction; capture + data accrual first

**Status: DESIGN NOTE — NO CONSTRUCTION, NO PREREGISTRATION.**
Prepared Oct 27, 2026 under the owner's directive adding PGA, UFC and DWCS to
the program. This note argues, with evidence, that DWCS is the one new sport
that must **not** get a flagship construction yet, and specifies exactly what
accrues instead so a construction becomes possible later. Nothing here starts
a clock or creates a PLAY. PAPER / research only.

Family: `DWCS / ALL` — Activation state today: **NO_CONSTRUCTION —
CAPTURE + ACCRUAL ONLY.**
Sibling documents: `PGA_H2H_MATCHUPS_DESIGN_PREREG_DRAFT.md`,
`UFC_MONEYLINE_DESIGN_PREREG_DRAFT.md` (same directory).

## 1. The repo already encodes this conclusion

`config/ufc_market_surface.json` (governance block) states
`"dwcs_requires_event_specific_validation": true` and
`"promotion_inherited_from_code_presence": false`. Repo law therefore
already forbids the tempting shortcut — letting DWCS ride on the UFC
moneyline engine's validation. A DWCS family must earn its own evidence,
and §2 shows it cannot have enough yet.

## 2. The evidence problem (why no construction is honest today)

1. **The sample ceiling is below the program's minimums.** Sherdog's DWCS
   index records ~89 events and ~440 matches in the promotion's entire
   history through 2025; a season is 10 weekly cards × 5 three-round bouts
   ≈ 50 bouts (Season 10 ran Aug 11 – Oct 13, 2026, Tuesdays at the UFC
   Apex — the repo's own S10 Week 3 card definition,
   `config/dwcs_s10w3_2026-08-25.json`, is five bouts). The UFC promotion
   contract's holdout minimum is **500 bouts** — more than DWCS has ever
   held. One full season of forward capture yields ~50 graded bouts.
2. **The fighters are debutants by construction.** DWCS exists to audition
   fighters with **zero** UFC bouts. The UFC flagship's features are
   UFCStats career rates — for a DWCS fighter, that record is empty *by
   design*. What exists pre-bout is regional data: win/loss records, finish
   rates and ages on Sherdog / Tapology — real, but with no standardized
   striking/grappling rate stats of UFCStats quality, inconsistent
   coverage by region and promotion, and opponent quality that is
   nearly unmeasurable across regional scenes.
3. **Post-bout data is fine — it just arrives too late to price with.**
   UFCStats publishes official fight stats for DWCS bouts (its DWCS
   fight-stats pages are the cited source for the series' records), so
   outcomes and stats accrue cleanly after each card. That builds a
   dataset; it does not create pre-bout features for the *next* card's
   debutants.
4. **Even the card itself has needed manual rescue.** The repo's Season 10
   Week 3 definition is labeled "Recovery-only card definition," with
   matchups hand-verified from UFC.com previews and a freshness guard so
   it cannot silently go stale. A market whose *fixtures* need hand
   verification is not ready to carry a frozen construction.

## 3. What could be modeled later (the honest sketch)

If the accrual in §4 completes, the first DWCS candidate would be a
moneyline rating built from: regional-record Elo (heavily shrunk — regional
opposition makes raw records near-uninformative), age, regional finish
rates (KO/SUB shares), reach/height, and camp/gym priors — with debut-style
uncertainty penalties on every row and pass criteria set *below* UFC's
sample demands only by pre-registered exception, never by drift. Whether
regional-record features carry any signal against DK prices is an open
empirical question; the prior should be skepticism. Method / rounds /
SGP / live families: no sketches until a moneyline verdict exists.

## 4. What accrues instead (the work this note actually commissions)

1. **Capture every DWCS card** under the standing lane cadence from the
   next season onward (Season 11 expected Aug 2027 — the 2026 season
   ended Oct 13, 2026): DK moneyline + method + rounds prices at T-1H and
   FINAL marks, so a paired price/outcome archive exists.
2. **Archive the post-bout record** for every captured card: UFCStats
   bout stats + the regional-record snapshot of both fighters *as of
   fight week* (Sherdog/Tapology states change after the fact; the
   as-of snapshot is the only point-in-time-honest version).
3. **Feature-availability audit after Season 11:** what fraction of
   fighters had a verifiable regional record, age, and finish history
   before their bout? If coverage < 80% of bouts, DWCS stays
   capture-only for another season — decided by audit, not enthusiasm.
4. **Revisit trigger:** ≥ 2 captured seasons (≥ ~100 paired bouts) AND
   the §4.3 audit passed → a preregistration draft may be written. Until
   then this note is the family's complete design record.

## 5. Multiple testing / governance

No test is proposed, so no α is spent. When a draft is eventually written
it faces the standing **α = 0.05 / k** at its own primary test, and per
§1 it inherits nothing from UFC.

*End of note. Prepared by Rocky (Muse) overnight Oct 27–28, 2026.
Evidence states: repo governance config and S10W3 card definition read on
main at 318377dfa; DWCS scale (~89 events / ~440 matches) and Season 10
dates from Sherdog's DWCS index and the repo config, read Oct 27, 2026;
UFCStats' DWCS coverage evidenced by its published DWCS fight-stats pages.
No performance claims are made anywhere in this note.*
