# MLB Prop Candidate Finder v1

## Purpose
Surface a small slate of props worth pricing. Candidate score is not a probability, EV, recommendation, or promotion evidence.

## Source-derived inspiration
The reviewed MySpariEdge graphics visibly use: recent hitter hit streaks; pitcher hits-allowed streaks; pitcher fade tiers; K-over/K-under profiles; recorded-outs profiles; workload/return caution; Statcast percentiles; and bullpen season/recent ERA screens. Those visible ideas are used only as candidate categories. The screenshots do not reveal proprietary formulas or weights.

## SportsEdge design
SportsEdge intentionally downweights descriptive streaks and raw short-window ERA. Structural signals receive more weight:
- hitter hits: projected PA, lineup slot, contact, platoon, opposing SP xBA allowed, bullpen, environment
- pitcher hits allowed: projected BF, xBA/hard-hit/barrel allowed, opponent contact and handedness matchup
- strikeouts: K%, whiff, chase, opponent K tendency, pitch count, workload
- bullpen attack: xFIP/FIP-style quality, availability, back-to-back workload, platoon fit; last-7 ERA is secondary

## Fail closed
Missing features reduce coverage. Candidates below minimum feature coverage are suppressed instead of treating missing data as neutral/good.

## Separation
`promotion_evidence` is always false. This layer cannot promote V6, cannot alter model gates, and cannot create an official bet. A later pricing layer must project a distribution, compare to de-vigged market consensus, calculate EV, and pass the Truth Gate.
