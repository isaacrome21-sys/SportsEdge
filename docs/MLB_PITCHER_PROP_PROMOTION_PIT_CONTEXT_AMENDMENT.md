# MLB pitcher-prop decision-time context amendment (2026-10-05)

This amendment is frozen before the one allowed final promotion look. It changes no model parameter, market threshold, sample threshold, or outcome rule.

For PITCHER_K and PITCHER_BB, current-game lineup and plate-umpire information must come from the immutable data-branch MLB context archive. The evaluator selects the latest snapshot captured at or before the archived quote time and no more than 20 minutes old.

If the archived snapshot says the context was present, the evaluator uses that exact archived lineup or umpire assignment. If it says the context was absent, the evaluator uses the production fallback that was available at that time. If no fresh snapshot exists, or a present snapshot is incomplete, the unit is excluded and counted.

Future or postgame current-game context may not be used to reconstruct what was known at quote time. Prior-game information remains valid because those games were completed before the target date.

This amendment was created from code audit before any final study result was inspected.
