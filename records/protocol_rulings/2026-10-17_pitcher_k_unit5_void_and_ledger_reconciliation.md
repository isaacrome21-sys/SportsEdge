# Pitcher-K forward protocol — Unit #5 VOID (owner ruling) + ledger reconciliation

**Ruling (Isaac, Sat 2026-10-17, ruling 1):** VOID the stale-priced unit #5
for actionable accounting, with an explicit reason. Preserve the original
immutable record. Any fresh capture is a NEW record with its actual event,
price, and timestamp. Never rewrite historical evidence or count the game
twice.

## The voided unit (as described in BRIEF_FOR_CLAUDE_AI.md / BLUEPRINT §4.1 M23)

- Nick Martinez, Over 2.5 K @ +133, recorded on the Fri Oct 16 card.
- The game (ALCS G4) was **POSTPONED** to Sat Oct 17, 19:08 CT.
- **VOID reason:** `POSTPONED_GAME_STALE_PRICE` — the price was captured
  for a game that did not start on its scheduled date. That price is not a
  pregame quote for the game actually played.
- The original record is not edited or deleted. This file is an additive
  accounting record. **Unit #5 counts 0 graded units, 0 P&L.**

## Ledger reconciliation (finding from primary sources, data branch)

Checked against the frozen protocol's create-only ledger
(`data/mlb_pitcher_k_forward/` on `origin/data`, protocol
`config/research/mlb_pitcher_k_forward_validation_v1.json`):

- **Unit #5 does not exist in the frozen automated ledger.** Every Oct 16
  Martinez capture by the automated lane was refused before prediction:
  - run `38940009126` @ 2026-10-16T17:30Z → BLOCKED
    `PITContextError:PIT_CONTEXT_FRESH_SNAPSHOT_MISSING`
  - run `38968196437` @ 2026-10-16T21:17Z → BLOCKED (same)
  - Today's run `39021159725` @ 2026-10-17T09:27Z also blocked Martinez
    (same reason; context not yet fresh).
  The +133 unit therefore lives only in the card-based / operator ledger,
  where this VOID applies. Nothing in the frozen ledger needs voiding.
- **The brief's count ("5 recorded / 4 graded, 1–3") does not match the
  frozen ledger.** The frozen ledger holds **11 predictions and 11 graded
  settlements**. Under the frozen selection rule
  (`LAST_PROSPECTIVELY_CAPTURED_PAIRED_PRE_FIRST_PITCH_PREDICTION_PER_GAME_PITCHER`,
  `sportsedge.mlb_pitcher_k_forward_readout.select_judged_units`), that is
  **8 judged units** (Oct 7: Martinez, Mahle, Fried, Glasnow; Oct 14:
  Gasser, Snell; Oct 15: Drohan, Glasnow). The two counts come from two
  different ledgers. **The frozen ledger is the one that governs the
  ≥150-unit protocol.**
- **Double-count protection:** tonight's game can enter the frozen ledger
  only through the automated lane, once, as the last pre-first-pitch
  paired prediction for (game_pk, Martinez). Unit #5 is VOID in the
  operator ledger, so the game is counted at most once.

## Interim descriptive readout — NOT a verdict

8 judged units, against the 150 required. Per-unit candidate-minus-market
log loss (negative = candidate better): Glasnow +0.167, Drohan +1.159,
Snell +0.325, Gasser +0.462, Glasnow +0.158, Mahle +0.382, Martinez
−0.355, Fried +0.052. **Mean +0.294**, candidate worse than the de-vigged
market on 7 of 8. This is reported for transparency only. The protocol
forbids interim tuning (`no_interim_parameter_tuning: true`), and nothing
changes because of it. The verdict comes at ≥150 units.
