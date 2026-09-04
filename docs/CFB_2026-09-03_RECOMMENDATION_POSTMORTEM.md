# SportsEdge CFB — September 3, 2026 Recommendation Postmortem

Purpose: grade the recommendation process honestly and prevent later recommendation changes from rewriting what the user could have acted on earlier.

## Important scope note

This document grades the **SportsEdge recommendation history from the conversation**, not the user's exact betting tickets. Exact ticket P/L cannot be determined without the user's actual wagers, prices and stakes.

## What happened

The first prominent CFB RUN IT card presented three top plays:

1. Akron/Wake Forest UNDER 48.5 (-108)
2. Georgia Tech -6.5 (-115)
3. Colorado/Georgia Tech OVER 50.5 (-118)

Those three early recommendations all lost:

- Wake Forest 38, Akron 16 — total 54: UNDER 48.5 lost.
- Colorado 14, Georgia Tech 13 — Georgia Tech -6.5 lost.
- Colorado 14, Georgia Tech 13 — OVER 50.5 lost.

**Initial three-play card: 0-3.**

That is the operationally relevant result if the user acted on the first card. Later improvements do not erase it.

## Recommendation churn during the day

### UMass at Rutgers

Early state:
- PASS at total 52.5.

Later state:
- OVER 51.5-52 became a context lean when the total moved down.
- When the total rebounded to 53.5, the Over was downgraded to PASS.
- UMass +29 or better was then added as a context lean.

Final score:
- UMass 37, Rutgers 21.

Process observation:
- Both the lower-number Over and the later UMass side would have won, but they were not part of the original top-three card.

### Akron at Wake Forest

Early state:
- UNDER 48.5 was the top context play.

Later state:
- Under was downgraded as QB/eligibility information became less clean.
- Akron +24.5, then +25.5/+26.5, became the preferred side.
- Very late, unresolved QB status caused the bigger dog number to be downgraded to HOLD/PASS until confirmation.

Final score:
- Wake Forest 38, Akron 16.

Process observation:
- Early Under lost.
- Akron +24.5 or better covered.
- The side switch happened after the original card and therefore cannot be used to grade the original recommendation as a win.

### Colorado at Georgia Tech

Early state:
- Georgia Tech -6.5 was a top play.
- Colorado/Georgia Tech OVER 50.5 was also a top play.

Later state:
- Conflicting market/handicap context caused Georgia Tech -6.5 to be downgraded.
- Colorado +7 became the preferred side, with +6.5 smaller.
- Late personnel news reduced confidence but did not fully remove Colorado +7.

Final score:
- Colorado 14, Georgia Tech 13.

Process observation:
- Both original GT -6.5 and original Over 50.5 lost.
- Later Colorado +7 won.
- The directional flip is exactly the type of churn the freeze-card protocol is meant to control.

### UAB at Illinois

Early state:
- Illinois -27.5 was WATCH.
- Under became attractive at 55/55.5 as personnel news accumulated.

Later state:
- At 54.5 and especially 54.5 -115, the Under was downgraded to PASS / do not chase.

Final score:
- Illinois 42, UAB 23 — total 65.

Process observation:
- A bettor who took the earlier Under 55/55.5 lost.
- The late pass was correct process discipline, but it does not retroactively erase an earlier actionable lean if it was already bet.

## Why the prior "3-1 final card" framing was misleading

A later snapshot contained winning positions such as UMass and Colorado plus Akron at improved numbers, but this was not a single stable card available to the user from the start. Grading the best late version creates hindsight bias.

Going forward, SportsEdge will grade only **FROZEN actionable recommendations**. Research updates can improve or cancel future action, but cannot rewrite historical card performance.

## Root causes

1. **No authoritative freeze point.** Research updates and bet recommendations were mixed together.
2. **Context was allowed to change direction too easily.** New articles/splits sometimes carried too much operational weight relative to the model layer.
3. **Price thresholds existed but were not consistently treated as the boundary between BET and PASS.**
4. **No immutable recommendation ledger.** It was too easy to quote the latest card instead of the first actionable card.
5. **Model vs context separation was stated correctly but not always reflected in recommendation stability.**

## Corrective action

The canonical `docs/CFB_FREEZE_CARD_PROTOCOL.md` now governs CFB HYBRID operation.

For every future CFB slate:

- research/watchlist first;
- obtain current DraftKings pricing;
- refresh injuries/QB/weather/market context;
- run SportsEdge model when available;
- publish one FROZEN CARD;
- reopen only for a defined material trigger;
- grade the frozen card at the frozen price;
- never claim a later flip as a win against an earlier frozen loss.

## September 3 process grade

**Bet-selection process: D**

Reason: the first top-three actionable card went 0-3 and recommendation churn was too high.

**Information monitoring: B**

Reason: several later signals were useful and identified better sides/numbers, but the information was not converted into a stable operating process.

**Governance honesty after review: PASS**

Reason: the record is being corrected to the first actionable recommendations rather than the best hindsight snapshot.
