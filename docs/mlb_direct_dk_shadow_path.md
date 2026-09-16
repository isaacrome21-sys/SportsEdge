# MLB direct-DraftKings shadow path

Status: **implemented for review; zero OFFICIAL authority**.

This path is the first-bets-out increment for MLB game markets. It uses DraftKings' direct web board (`DRAFTKINGS_DIRECT_WEB_V1`) for MONEYLINE, RUN_LINE, and TOTALS, binds each provider event to exactly one MLB StatsAPI game, then feeds the existing market-blind SportsEdge MLB model through the existing HYBRID/unified card path.

## What this changes

- Adds keyless DraftKings game-market acquisition with exact two-sided admission.
- Uses SportsEdge HTTP receipt time as `retrieved_at`; no provider `last_update` is invented.
- Preserves exact raw board bytes separately and records their SHA-256 in source provenance.
- Writes content-addressed shadow-ledger entries for `MODEL_CANDIDATE` rows carrying `SHADOW_BET`, `SHADOW_PASS`, or one-sided candidate economics.
- Leaves `config/deployments.json` unchanged and grants no promotion or OFFICIAL authority.

## What remains blocked

OFFICIAL betting remains fail-closed until the existing deployment/evidence requirements pass. This increment does not supply historical PIT replay, calibration, CLV, or promotion evidence and does not alter any frozen Truth Gate threshold.

The existing full MLB automatic runner remains authoritative for the broader market catalog. The new `scripts/run_mlb_direct_shadow.py` is the explicit keyless game-market shadow lane; the next integration step is to place this source ahead of ESPN in the resilient runner's game-market fallback chain without reducing prop coverage when native acquisition is healthy.

## Acceptance surface

`tests/test_mlb_direct_dk_shadow_path.py` covers exact raw-byte identity, StatsAPI event binding, exact two-sided game-market admission, spread mismatch rejection, one-sided-total non-synthesis, unbound-event rejection, and immutable zero-authority shadow-ledger behavior.
