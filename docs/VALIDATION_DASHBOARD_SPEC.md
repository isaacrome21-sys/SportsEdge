# SportsEdge Validation Dashboard Contract

Status: RESEARCH CONTRACT — does not alter production eligibility, deployments, Truth Gate floors, or V6 gates.

## Purpose

Provide one source of truth for model/market readiness. Every market row must describe the exact model/feature version that generated the evidence and must distinguish infrastructure health from predictive eligibility.

## Required row identity

Each row is keyed by:

- sport
- market
- model_version
- model_sha
- feature_contract_version
- feature_sha
- evidence_window_start_utc
- evidence_window_end_utc

Rows from different model or feature hashes must never be silently pooled.

## Required columns

| Field | Meaning |
|---|---|
| `status` | `PRODUCTION`, `RESEARCH`, `QUARANTINED`, `INSUFFICIENT_EVIDENCE`, or `STALE_EVIDENCE` |
| `settled_bets_n` | Frozen recommendations with final settlement |
| `settled_passes_n` | Frozen passes with counterfactual market outcome/close when available |
| `effective_n` | Evidence count after identity/deduplication rules |
| `brier` | Proper score on binary probabilities |
| `log_loss` | Proper score on binary probabilities |
| `calibration_slope` | Slope from out-of-time reliability fit when supported |
| `calibration_intercept` | Intercept from out-of-time reliability fit when supported |
| `calibration_mae` | Weighted reliability gap |
| `mean_clv` | Mean closing-line value in the canonical CLV unit |
| `pct_beating_close` | Fraction of eligible frozen bets beating the close |
| `mean_edge_at_freeze` | Mean model probability minus fair market probability at freeze |
| `mean_ev_at_freeze` | Mean expected value per dollar at freeze |
| `last_durable_evidence_utc` | Latest persisted evidence timestamp for this market |
| `evidence_age_hours` | Age of latest durable evidence at dashboard generation |
| `lineup_confirmed_share` | Share of graded predictions using confirmed lineups where relevant |
| `price_verified_share` | Share with exact player/market/side/line/odds/book/timestamp identity |
| `external_disagreement_n` | Material disagreements logged against tracked external models |
| `truth_gate_accept_n` | Opportunities accepted by the Truth Gate |
| `truth_gate_pass_n` | Opportunities rejected by the Truth Gate |
| `notes` | Human-readable blocking reason or audit note |

If a metric is not supported by evidence, persist `null`; never invent or backfill it.

## Status precedence

Use the first matching state:

1. `STALE_EVIDENCE` — durable evidence heartbeat exceeds its market/source freshness policy.
2. `QUARANTINED` — calibrated research diagnostics materially deteriorate or monotonicity/reliability checks fail with sufficient evidence.
3. `INSUFFICIENT_EVIDENCE` — minimum sample/evidence age requirements are not met.
4. `PRODUCTION` — only when the existing production promotion contract is satisfied.
5. `RESEARCH` — otherwise.

Infrastructure recovery alone can clear `STALE_EVIDENCE`; it cannot promote `RESEARCH` to `PRODUCTION`.

## Market separation

At minimum maintain separate rows for:

- MLB_MONEYLINE
- MLB_RUN_LINE
- MLB_TOTAL
- MLB_TEAM_TOTAL
- MLB_NRFI
- MLB_YRFI
- MLB_PITCHER_OUTS
- MLB_PITCHER_K
- MLB_PITCHER_BB
- MLB_PITCHER_HITS_ALLOWED
- MLB_PITCHER_ER
- MLB_BATTER_HITS
- MLB_BATTER_TOTAL_BASES
- MLB_BATTER_HR
- MLB_BATTER_RUNS
- MLB_BATTER_RBI
- MLB_BATTER_HRR

No market may inherit another market's validation status.

## Calibration requirements

Dashboard generation must preserve point-in-time ordering and use only frozen predictions. Random train/test pooling is prohibited for promotion evidence.

Report Brier and log loss before ROI. ROI is descriptive only and is not a model-promotion criterion.

Calibration slope/intercept are optional until enough evidence exists to fit them robustly; null is preferred to unstable estimates.

## CLV requirements

CLV requires a reliable closing quote with exact market identity. If the close cannot be matched unambiguously, CLV fields for that row remain null for that observation.

Do not reconstruct historical closing prices from present-day quotes.

## Truth Gate quality section

For every market with frozen pass data, calculate separately:

- accepted-bet mean CLV
- rejected-pass counterfactual mean CLV
- accepted-bet Brier/log loss
- rejected-pass counterfactual Brier/log loss where a model probability was frozen
- false-negative share: rejected opportunities that later beat the close by the configured materiality threshold
- tier monotonicity: higher confidence tiers should not realize worse calibration/CLV than lower tiers over adequate samples

These diagnostics evaluate the gate; they do not retroactively change settlement labels.

## Provenance

Every generated dashboard artifact must include:

- schema version
- generated_at_utc
- source branch/ref
- model SHA(s)
- feature SHA(s)
- evidence artifact hashes
- dashboard generator SHA

## Fail-closed rules

Dashboard generation must fail or mark the row incomplete when:

- evidence identities conflict
- model/feature SHA is missing
- outcomes disagree for the same frozen identity
- prices are ambiguous
- closing-line identity is ambiguous
- timestamps are not timezone-aware
- market labels are unsupported

## Non-goals

This dashboard does not:

- change production gates
- choose bets
- lower edge floors
- promote V6
- repair missing historical data
- treat CI success as predictive evidence
