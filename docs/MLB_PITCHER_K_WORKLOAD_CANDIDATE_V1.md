# MLB pitcher-K workload candidate v1

Status: **research only — not deployed and not eligible for production probability input**.

This is the first implementation step under the pitcher-K refinement frozen in
`config/research/mlb_card_postmortem_refinement_v1.json`. It does not choose a
new probability formula and it does not inspect the October 5 outcome.

The bundle reuses the existing strictly-prior StatsAPI pitching game-log rows that
SportsEdge already fetches for pitcher props. No new live source is introduced.
For the last 5–10 starts it preserves batters faced, pitch count, strikeouts, and
outs, then records simple descriptive means for batters faced, pitch count, outs,
K per batter faced, and pitches per batter faced.

Those fields cover the preregistered workload/leash portion of the next candidate
while keeping the later model comparison honest. Any weighting, combination with
opponent-K/lineup-K, whiff/chase data, promotion threshold, or probability mapping
must be frozen separately before evaluation on untouched PIT outcomes.

Missing or impossible workload fields fail closed. Production pricing remains
unchanged.
