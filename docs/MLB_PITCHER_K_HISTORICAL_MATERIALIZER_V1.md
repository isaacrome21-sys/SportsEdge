# MLB pitcher-K historical materializer v1

Status: **research-only candidate-test acquisition; zero forward/betting authority**.

This is the acquisition layer for the frozen 2023 fit / 2024 validation / 2025
candidate-test protocol. It produces rows consumed by
`mlb_pitcher_k_evaluation_runner.py`.

## PIT rules

For every target start:

- workload comes from the last 5–10 regular-season pitcher starts strictly before
  the target date;
- opponent-K uses the already validated #1509 index and date-bounded team hitting
  histories;
- target lineup adjustment is deliberately **not reconstructed from final
  boxscores**. Without a genuine pregame lineup archive, the validated fallback is
  `lineup_k=None`;
- Statcast skill uses only pitches before the target date;
- the target game outcome is read only after all candidate features have been
  constructed;
- incumbent probabilities are generated through the shipped pitcher joint engine
  on the same strictly-prior history and opponent-K context.

Historical rows are explicitly marked backfill/reconstruction and are never
forward evidence or promotion evidence.

## Acquisition efficiency

The Savant layer is fetched in overlapping 45-day chunks by default, de-duplicated
by pitch identity, and reduced immediately to only the fields needed for
whiff/chase/hand calculations. Rolling target-date windows are then computed
locally. This replaces hundreds of repeated full-league 30-day queries with a
small number of season chunks.

StatsAPI player/team game logs use the existing immutable-history cache. A
scheduled probable pitcher is retained only when the historical game log confirms
that pitcher actually started the target game.

Any missing or inconsistent source fails closed for that target row and is
counted in the materialization receipt. No synthetic fallback row is created.
