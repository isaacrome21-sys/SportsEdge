# MLB batter props successor — research construction protocol (2026-10-26)

**Status:** DESIGN ONLY; not a freeze, forecast, card, or promotion. Failed or unverified predecessor constructions do not inherit authority.

## Hypothesis and market scope
Develop a hierarchical plate-appearance/opportunity model and conditional outcome distributions for batter hits, total bases, home runs and RBIs, each screened separately. Inputs: as-of confirmed lineup/batting slot, opposing starter and bullpen availability, park/weather, handedness, rest and historical batter/pitcher skills. No outcome-derived lineup or post-first-pitch data. Refuse missing starter/lineup rather than fabricate certainty.

## Market identity and capture
Bind MLB StatsAPI game_pk, official_date and game start to authenticated schedule bytes; bind player ID, team, opponent, market, integer/half-line, side, paired DraftKings American prices and timestamped raw quote receipt. Require an independently witnessed final and exact settlement rule (including postponements, nonstarts and voids). A SHA-shaped manifest alone is NOT authenticated provenance. Do not substitute pitcher props, team totals or game-line receipts for batter-specific captures.

## Leakage-resistant screen
Season-chronological walk-forward with embargo around game day and player trades, grouped game/player holdouts, training-only calibration, explicit exclusions and missing-data audits. Compare against a captured no-vig bookmaker baseline on identical event/line/time pairs. Score Brier/log loss, calibration, ROI under labeled observed entry prices, uncertainty intervals and sample sizes by prop. Reject thin subgroups, price/line mismatches and same-game duplicated outcome credit.

## Decision protocol
Preregister construction and screening thresholds before data evaluation; hold out a final untouched chronological period. If robust out-of-sample evidence fails, close **NO VIABLE CONSTRUCTION** with the negative result intact. Otherwise pin one final reviewed head and artifact, name the first counted future slate and begin forward-only ledger. No backfill, no retroactive frozen test edits. Verified gate: >=50 graded forward picks + authentic timestamped CLV >0 + observed-price ROI >0. Until then PAPER/0u.

## P0 dependency
Live DK capture latency and receipt completeness must be fixed and demonstrated end-to-end; synthetic timing diagnostics are not provider capture proof.
