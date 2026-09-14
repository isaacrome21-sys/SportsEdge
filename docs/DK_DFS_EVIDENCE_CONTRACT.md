# DraftKings DFS evidence contract

This file freezes the remaining MLB DFS evidence rules that are easiest to accidentally overstate.

## 1. Starting-pitcher accounting

A simulated MLB starter path is not scoreable unless the damage is explicitly starter-scoped and the path records the starter's exit workload. Required fields are:

- `outs`
- `strikeouts`
- `earned_runs`
- `hits_allowed`
- `walks_allowed`
- `hbp_allowed`
- `starter_exit_batters_faced`
- `starter_exit_pitch_count`
- `starter_scoped_events=1`
- `lead_at_exit`
- `lead_preserved_to_final`

The +4 DraftKings win is derived inside the DFS scorer. It requires at least 15 outs, a lead at the starter's exit, and that lead surviving to the final. A final-score-only win flag or opaque `dk_points` pitcher path is rejected. Mean-only pitcher projections must also carry workload and win-qualification components; a naked `win_probability` is insufficient.

This does not prescribe a fixed 22-25 BF hook. The upstream simulator must model the hook, batters faced, and pitch count. The DFS layer verifies that those state variables exist and fails closed if it receives full-game or unscoped pitcher outcomes.

## 2. Ownership evidence clock

The realized-ownership evidence epoch is **2026-09-14 00:00 America/Chicago** (`2026-09-14T05:00:00Z`). Promotion evidence may not backfill contests before that epoch.

Ground truth comes from a complete DraftKings post-contest standings export for a contest actually entered. The freeze step requires:

- the user's entry ID to exist in the export;
- every entrant lineup to parse to the full roster size;
- entrant count to equal the expected contest field size;
- every player to resolve to a DraftKings player ID;
- the raw CSV SHA-256 to be stored with the derived ownership snapshot.

The resulting evidence class is `RETROSPECTIVE_REALIZED_OWNERSHIP`. It may calibrate ownership models for later slates. It may never influence optimization or field simulation for the slate from which it was learned.

Operational command:

```bash
python scripts/freeze_dk_ownership.py \
  --standings-csv contest-standings.csv \
  --salary-csv DKSalaries.csv \
  --contest-id 123456789 \
  --our-entry-id 987654321 \
  --slate-lock 2026-09-14T18:10:00-05:00 \
  --expected-field-size 2377
```

No realized ownership row exists until an actual post-contest export passes this contract. The system must report the lane as evidence-pending rather than synthesize ownership.

## 3. Promotion evidence

Contest ROI and top-1% finishes are noisy slate-level outcomes. They are telemetry, not positive promotion evidence.

The promotion gate is player-level out-of-sample distribution calibration. The default check uses the 10th, 50th, and 90th percentile forecasts and asks whether realized coverage is statistically compatible with 10%, 50%, and 90% using Wilson 95% intervals. The gate remains `BLOCKED` until at least 500 player-level observations exist.

Contest ROI can only veto an otherwise calibrated model. The current veto is one-sided: after at least 30 slates, ROI vetoes only when the approximate 95% upper confidence bound on mean slate ROI is below zero. Positive ROI can never rescue `BLOCKED` or `FAILED` calibration.

Top-1% rate remains descriptive telemetry and has no promotion vote.

## Governance summary

- calibration can promote;
- clearly harmful contest ROI can veto;
- positive ROI cannot promote;
- ownership evidence is forward-only and immutable;
- retrospective ownership cannot leak into the same slate;
- pitcher DK points cannot be produced from unscoped full-game outcomes;
- missing evidence is a terminal `BLOCKED` state for the affected lane, not permission to invent a default.
