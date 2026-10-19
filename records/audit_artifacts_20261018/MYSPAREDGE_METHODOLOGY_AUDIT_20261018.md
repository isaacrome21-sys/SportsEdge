# MySpariEdge Methodology Audit — Oct 18, 2026

- **Author:** Rocky — Isaac's main-chat agent (the Muse / captures lane). Sole reader and author of this audit.
- **Date of underlying read:** October 18, 2026 — 21 MySpariEdge models/tools read that day (public and member pages; member access via Isaac's sign-in, completed by Isaac himself).
- **Delivered:** to Isaac in the main chat on the evening of Oct 18, 2026.
- **Status:** RESEARCH CONTEXT ONLY. This audit is research context, **not** evidence about SportsEdge models. All MySpariEdge numbers are source-labeled wherever used and are never blended into SportsEdge numbers. SportsEdge prices bind only to paired DraftKings captures.

---

## Findings

### 1. Player Props Edge — the only model that states a backtest basis
- **Model%** = calibrated selected-side win rate from 2023–25 testing.
- **Edge%** = Model% − implied probability **with the margin (vig) in**.
- Their **"Score" never subtracts negative edge — it is floored at zero.** It is a display rank, not a confidence rating.
- NFL props lock 90 minutes before kickoff.

### 2. Only two pages post records — and both are losing
**Edge Lab** (frozen NFL 2026 archive, 3,991 selections; flat-1u ROI negative in *every* Score band):
| Score band | ROI | n |
|---|---|---|
| <150 | −7.3% | 1,045 |
| 150–199.9 | −3.1% | 2,349 |
| 200–249.9 | −2.9% | 461 |
| 250+ | −5.5% | 90 |
| "Unknown" band | +12.6% | — |

The top-filter "systems" showing +16.7% to +28.5% are self-flagged **EARLY SAMPLE** on the page itself.

**Model Bets Tracker** (MLB, Oct 8–17): 20–23, −8.4u, −19.5% ROI, labeled "Small sample" on the page.

### 3. Best Bets — UNVERIFIABLE
No stated selection threshold or window. The cards show **no prices and no books**, so the picks cannot be checked against any market or reproduced after the fact.

### 4. "How Our Models Work"
Inputs are listed, and projections freeze at lineup lock — but weights, formulas, and thresholds are **explicitly withheld**, and no backtest seasons or sample sizes are given anywhere on the page.

### 5. NRFI/YRFI — their most disciplined page
- Starter hold probability is driven by season K/9.
- The first-inning record is shrunk toward the league baseline and **capped below the K/9 weight**.
- A top-3 OBP lineup adjustment is applied.
- Non-inputs are stated explicitly — the only page that says what it does *not* use.

### 6. Touchdowns
- **Model%** = P(≥1 rush/rec TD), which matches DraftKings settlement.
- The **Parlay Optimizer prices TD legs as INDEPENDENT, teammates included** — no correlation adjustment.
- Week 6 board top: Derrick Henry 67.1%; Christian McCaffrey 56.6% with Edge −16.7% (i.e., their own board showed the most likely scorer as a strongly negative-edge bet at the posted price).

### 7. No stated methodology at all
- **Player Prop Picks:** letter grades with the scale undefined.
- **Parlay Builder:** marked BETA; no methodology stated.

---

## Standing conclusions (adopted by Isaac in the main chat, Oct 18, 2026 — as recorded in the author's main-chat record)

1. This audit is **research context, NOT evidence about SportsEdge models**. A competitor's weak disclosure says nothing about whether SportsEdge's constructions win or lose; SportsEdge verdicts come only from SportsEdge's own tests against prices.
2. **All MySpariEdge numbers stay source-labeled, never blended** into SportsEdge numbers, prices, or EV estimates.
3. Where SportsEdge adopts a MySpariEdge-style *presentation* idea, it does so under SportsEdge discipline: real prices and books shown, negative edge shown as negative, independence assumptions stated on the card, and full records (wins and losses) published.
