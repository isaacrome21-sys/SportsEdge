# #2432 M50 full-game terminal-score tie-state discrepancy — review-only disclosure

**Status:** DRAFT REVIEW COMPANION. NOT A VERDICT ON #2432. NO CODE CHANGE, NO CHANGE TO ITS VERIFIED HEAD, NO GOVERNANCE/PROMOTION AUTHORITY.

## Mechanism the independent verifier must adjudicate

The incumbent `sportsedge.game_total_distribution` constructs a Cartesian-product joint from separate away and home final-run count marginals: `P(A=a,H=h) = P(A=a) × P(H=h)`. Nothing in that construction forbids **a == h**. Those equal-score cells normally have positive mass (for example `P(3,3)`), even though an MLB **completed final game result** is decided in extra innings when regulation is tied. Note: exceptional suspension/forfeit/called-game settlement must be handled by an explicit official game/status and book rule; they cannot be guessed from a model score.

**The core error would be calling this a physically valid MLB completed-final-score distribution without resolving its tied cells.** Four consequences matter:

1. **Winning margin / winning team:** a final-score tie selection is not an ordinary settled MLB full-game winner. Allocating a TIE margin band and calling its probability a final result is inaccurate under a final-result incl-extras market. Summing only HOME/AWAY margins and *silently dropping tied mass* violates normalization. Renormalizing HOME/AWAY on their own is also not a justified conditional extras model.
2. **Correct score:** a cell such as `AWAY_3_HOME_3` cannot represent the normal completed MLB final score. Merely moving all tied cells to `ANY_OTHER` makes the probability partition sum to one but does **not** assign the corresponding extra-inning scored runs to their real final cells. That is not a valid final-score forecast.
3. **BTTS and team parity:** extra innings may increase both clubs' final run counts, changing BTTS rungs and each club's odd/even final-run parity. Preserving a tie-capable nine-inning state but calling it **final** misstates even these seemingly order-insensitive market outcomes. Conditioning away equal-score states gives wrong unconditional event probabilities.
4. **Extra innings YES/NO:** an actual tie **at the end of nine** is the relevant trigger; the *terminal final score* by itself has no extra-inning indicator. A tie cell in an unconstrained independent final-run joint is not an authenticated nine-inning tie event and must not be used as an extra-innings prediction.

## Correct model requirements for a future challenger

A coherent MLB market-specific score process must make an explicit distinction between **regulation through nine** and **terminal after extras**:

- Derive and pin a strictly-prior nine-inning regulation score-state distribution with a validated dependence structure (including tie probability). Prove it uses genuine inning/score evidence rather than an invalid independence assertion.
- Conditional on regulation tie, model legal extra-inning scoring and the resulting winning final score, accounting for home batting conditions/walkoffs, inning path, runner-on-second rules where applicable, and official completion/settlement status. All terminal outcomes must be non-tied under ordinary completed MLB final-result rules.
- Provide separate readouts for **market-specific regulation 3-way** versus **full game including extras**. Do not conflate them. DK market ID, period, quoted outcome set, and explicit official settlement must be independently pinned. A regulation-time 3-way TIE can be legitimate if the market is for nine-inning regulation, and differs from full-game ML incl extras.
- Hand-recompute row normalization, full support conservation, score-to-event parity, BTTS rung mass, correct score including catch-all, and margin partition under a **physically supported final-score distribution**. Re-evaluate against strictly-prior baselines and independently admitted quote lines; no backfill of a failed screen.

## What #2432 does and does not prove

PR #2432 currently offers additive readout functions over an existing `GameTotalDistribution`. Its unit tests for score-cell summation, Jeffreys posterior and F5 grammar parity may all pass while **the source distribution is misinterpreted as an MLB final-score forecast**. Code-level conservation is necessary but insufficient: a normalized PMF with impossible final ties is still unfit for final-result market pricing.

This memo does NOT imply that the independent verifier has issued a result, and does not amend #2432's engine, tests, schema, historical test spec, quote binding, registry, eligibility or deployment. Until verifier disposition and any separately reviewed model correction, the proposed terminal-score readouts must remain **UNVALIDATED RESEARCH ONLY / NOT DEPLOYABLE / NO MARKET TEST**, with the final-vs-regulation issue explicitly identified as **OPEN**.

## Minimal verifier probes

- Create a finite incumbent joint with positive equal-score mass; report `sum(P(a,a))`. Confirm exactly how #2432 treats that mass in its BTTS, parity, correct-score and winning-margin readouts. Flag any undocumented drop, unsupported conditioning or mislabelled final-result tie.
- Construct two hypothetical valid **after-extra-inning** worlds with the same tied nine-inning state but different final score allocations: show their correct-score/parity/BTTS/winning-margin outcomes differ. This proves the final-score readout is **not identifiable** solely from an unresolved regulation tie joint.
- Confirm PR #2432's tests cannot claim real-world full-game-market validation without the 9-inning→extra-inning construction and proper market-identity settlement labels.

**Owner/verifier instruction:** This is a docs-only review aid. Rocky retains full code verification and merger control of #2432. No changes or approval are requested to frozen files.
