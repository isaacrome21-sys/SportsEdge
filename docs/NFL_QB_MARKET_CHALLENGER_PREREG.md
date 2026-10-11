# NFL QB + market-blend challenger — pre-registration

**Status:** frozen. No fit or results until this document is committed and its SHA is logged on #1479.
**Location:** research lane next to Attempt 9. Lean-only if it fails.
**Data:** free nflverse only (schedules, PBP, weekly stats, QB identifiers). No paid Odds API.

## Features (frozen)
- QB-adjusted team ratings (nfelo-style rolling EPA or equivalent from nflverse PBP, prior weeks only).
- Market line blend: closing spread or moneyline no-vig as a prior (context only; not a Model_P input).
- Recency weights matching Attempt 9 decay (0.85) for consistency, but coefficients are independent.

## Training / holdout
- Training seasons: 2016–2022 (or earliest complete QB-adjusted data).
- Holdout seasons: 2023–2025 (out of sample).
- Prospective 2026 weeks stay locked until the holdout clears.

## Pass bar
- Beat 52.4% win rate at -110, or positive expected value vs no-vig closing lines, consistently across holdout seasons.
- Must hold in most seasons, not just pooled.
- If it fails: remains lean-only. Never promoted to OFFICIAL or Truth Gate.

## Governance
- This file is listed in `config/reconciliation_coverage_v1.json` so main-merge-hold passes.
- No changes to Attempt 9, M2, key-number mixture, or frozen 2026 confirmation policy.
- Whole-number lines remain blocked.
