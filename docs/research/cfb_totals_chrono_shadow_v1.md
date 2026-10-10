# CFB totals: chronological offset and shadow research (2026-10-09)

**Research only: zero wagering authority.** No changes to frozen score model, production card, bet selection, or eligibility.

## Observed problem

The native SportsDataverse live scoring path intentionally avoids the CFBD-only moment-matching transform. The SHA-receipted run 38008285250 has four paired market totals, model-versus-market point gaps +8.59, +8.37, +5.83, +6.06 (average +7.21); all four oversized OVER edges were properly rejected.

The home+away intercept in the frozen model totals 55.1875; features reduce the four specific matchup totals but do not reach the market. Previous historical market-anchored totals research did not demonstrate a useful trading signal (issue #1602). Four model/market disagreements alone do not prove a bias in outcomes or sportsbook error.

## New research plumbing

- scripts/research_cfb_total_offset_chrono.py fits an additive offset from **settled scores on earlier time periods only**, and evaluates on later held-out weeks. Historical closing lines are optional separate evaluation values and never enter fitting.
- Retrospectively reconstructed rows must be RECONSTRUCTED_DEVELOPMENT. CAPTURED_PREGAME_RESEARCH claims additionally require timezone-aware prediction, kickoff, and settlement timestamps in strict order, plus a 64-character source SHA256. Claimed evidence is not independent vintage verification.
- scripts/research_cfb_total_offset_shadow.py reads a CFB_SDV_CARD_V2 card and research calibration artifact, adjusts each projected team mean by one-half the offset (preserving game margin), and recomputes OVER probabilities from the adjusted score-total distribution. It does **not** modify the original card or staking logic; all output is RESEARCH_ONLY_NO_BET, with bets_enabled=false.
- tests/test_cfb_total_offset_chrono.py and tests/test_cfb_total_offset_shadow.py cover chronology, source claims, no-leakage from closes, symmetry, pairing, and research-only zero betting authority.

## Retrospective development check

The original source archive is at https://github.com/isaacrome21-sys/SportsEdge/actions/runs/38008285250

Reconstructed 2026 outcomes: train weeks 2–4, 124 games, estimated correction −2.550 points. Evaluate subsequent weeks 5–6, 58 games: total MAE 15.130 before versus 15.009 after. Naively subtracting seven points made held-out MAE 15.23. This is a retrospective reconstruction, NOT a verified PIT, decision-priced, or future holdout test.

| Game | Frozen model | Research-only shadow |
|---|---:|---:|
| Iowa State @ BYU | 55.09 | 52.54 |
| Wyoming @ San Jose State | 50.87 | 48.32 |
| Washington State @ Utah State | 49.34 | 46.79 |
| Iowa @ Washington | 46.56 | 44.01 |

No model validation, EV, betting ROI, or probability calibration has been established.

## Before any genuine wager qualification

1. Check historical/live native feature definitions (two-season blend, EPA and success rate, opponent join, field position, venue, missing weather).
2. Keep candidate frozen and gather future independently archived **pregame** model/source and same-time paired quotes, with subsequent closes and outcomes.
3. Evaluate untouched model calibration, Brier, MAE/RMSE, pushes, and actual decision-price net return by total bucket and season before any approval.
4. If results justify it, implement a separate controlled mean-scoring revision. Preserve all fail-closed safety checks and the -165 straight-bet ceiling.

## Research CLI

    python -m unittest tests.test_cfb_total_offset_chrono tests.test_cfb_total_offset_shadow -v
    python scripts/research_cfb_total_offset_chrono.py --input research_rows.json --output chrono_report.json --train-year 2026 --train-week 4 --holdout-year 2026 --holdout-week 5
    python scripts/research_cfb_total_offset_shadow.py --card cfb_sdv_card.json --calibration chrono_report.json --output shadow_totals.json
