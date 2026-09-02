# MLB V8 replay and forward evidence

## Goal

Preserve enough immutable, timestamped evidence to evaluate MLB predictions chronologically without reconstructing observations after the fact. V8 forward evidence begins with the 2026-09-03 Chicago slate. Nothing collected later is relabeled as a forward observation for an earlier date.

## Evidence lanes

`FORWARD` is the clean lane. The lightweight odds archive preserves exact raw market bytes around T-180, T-90 and T0, while automated MLB runs preserve the exact card, associated game-odds/diagnostic files, prediction journal, Git SHA and per-row model/distribution/readout identity. Event rows observed after first pitch are retained but are not pregame decision evidence.

`HISTORICAL_BACKFILL` is the replay lane. Provider-native timestamped history can support a replay only when the provider timestamp proves the quote existed by the requested replay as-of time. Backfill never changes a Truth Gate status by itself.

## Source classes

The source registry is `config/mlb_v8_sources.json`.

- `PIT_SNAPSHOT` / `PIT_TIMESERIES`: eligible for historical decision-time replay when timestamps are valid. The Odds API historical snapshots, PropLine history, licensed SportsDataIO line movement and licensed OpticOdds time series fit here.
- `OPEN_CLOSE_ONLY`: eligible for closing-price/CLV evidence but not for reconstructing a T-90 decision quote. SportsGameOdds is intentionally classified this way.
- `EXCHANGE_PIT`: useful as a sharp-market reference; never substituted for an executable sportsbook price.
- `OFFICIAL_RESULT_CONTEXT`: game identity/results only. MLB StatsAPI does not become market evidence.
- `PIT_UNVERIFIED`: quarantined until original source, timestamp semantics and reuse rights are verified.

## Replay acquisition

`python3 -I scripts/backfill_mlb_v8_replay.py --self-test`

The remote adapters are resumable and bounded:

- `--provider the-odds-api` queries regular-season MLB historical snapshots at pregame anchors. The default anchors are T-90 and T-5 and the default one-book/three-market historical request is conservatively budgeted at 30 credits per snapshot.
- `--provider sportsgameodds` pages finalized MLB events with per-book open/close values.
- `--provider propline` stores exact monthly historical CSV exports when the account has backfill/export access.
- `--provider external-import --source-id ... --input ...` stores exact licensed exports from registry sources such as SportsDataIO, OpticOdds or Betfair without pretending the import time is the market observation time.

The manual `mlb-v8-replay-backfill` workflow persists raw files, manifests, status and the resume ledger to `data:archive/mlb_v8/`.

## Forward collection

The `archive-mlb-game-odds` workflow packages each raw capture into a hash-bound V8 market bundle and persists it to `data:archive/mlb_v8/`. The `auto-mlb` workflow packages the exact decision card, live odds, diagnostics and prediction journal. Both paths are start-guarded at 2026-09-03 CT.

All persistence is immutable by path and SHA-256. An existing path with different bytes is a hard failure. Concurrent data-branch pushes retry by fetch/rebase rather than silently discarding evidence.

## Promotion rule

Evidence collection and predictive promotion remain separate. Replay data must still pass chronological holdout, paired decision-to-close comparison, no-vig calibration, CLV, after-vig ROI and existing sample gates before any market can become eligible. Missing periods remain explicit gaps.
