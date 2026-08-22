# Engine B Retrosheet Feasibility Audit

Integration state: `INTEGRATION_UNRUN`.

Research/design only. This document distinguishes what Retrosheet can establish from what would require inference or another point-in-time source.

Primary references: Retrosheet event-file specification, parsed play-by-play crosswalk, and CSV field descriptions.

## Field availability by LABELRULES_V1 cause

### COMPLETED_PATH — supported
Required observations: starter identity, pitcher sequence, outs recorded / game end. Retrosheet provides starting pitchers, `p_seq`, `p_ipouts`, play-by-play pitcher identity, inning/outs, and end-game context. A deterministic definition of "completed path" still needs to be frozen (for example, complete game vs a prespecified target-path definition), but the underlying event fields exist.

### PITCH_COUNT_EXHAUSTION — partially supported
Required observations: pitch count at exit plus a **pregame workload prior**. Retrosheet play records can contain pitch sequences / number of pitches when known, but pitch information is not complete for every historical game. The workload prior is not a single Retrosheet field; it must be built ex ante from prior starts using only information available before the target start. Missing pitch history must not be imputed into a universal threshold.

### PERFORMANCE_HOOK — inferential, not directly labeled
Retrosheet provides score state, runs/hits/events, baserunners, inning/outs, and pitcher identity around the exit. It does **not** provide an authoritative manager reason saying the starter was removed for poor performance. A rule may classify only high-confidence patterns; overlap with workload/tactical mechanisms must become `UNKNOWN` unless a declared dominance rule resolves it.

### TACTICAL_SUBSTITUTION — inferential, not directly labeled
Retrosheet `sub` records and play-by-play identify pitcher replacement and game state, but not the manager's motive. Close/low-scoring leverage context can be observed; tactical intent cannot generally be proven. Do not silently absorb ambiguous tactical exits into `PERFORMANCE_HOOK`.

### INJURY_HEALTH — generally not supported as an authoritative cause
Retrosheet identifies that a pitcher left and who replaced him, but there is no general structured field giving injury/health as the removal reason. Unless an explicit contemporaneous source is separately bound, classify these cases `UNKNOWN`. This is the highest-risk contamination path for `PERFORMANCE_HOOK`.

### WEATHER_DELAY — partially supported
Game/event data can establish interruption/game context, and Retrosheet schedule/game metadata contains weather/postponement information in some contexts. It is not safe to assume every in-game pitcher removal after a weather interruption has a structured removal-cause field. Only explicitly evidenced delay-linked exits should receive `WEATHER_DELAY`; otherwise `UNKNOWN`.

### UNKNOWN — required, not failure
`UNKNOWN` is the correct label whenever the event record proves an exit but cannot distinguish competing causes. Coverage must be reported honestly rather than forced to 100%.

## Coverage contract

Report `cause_label_coverage = classified_exits / total_exits` separately. The classifiable subset gets mechanism-frequency validation. Unclassified exits remain in distribution validation and get their own frequency/bounds report.

## Historical window

At execution time freeze the **most recent five completed MLB seasons** into the artifact as exact season numbers. Do not hard-code a rolling expression into the evidence artifact. Version-stamp:

- `historical_seasons`
- `starter_class_version`
- `workload_prior_version`
- `labeling_rules_version=LABELRULES_V1`
- `total_exits`
- `classified_exits`
- `unclassified_exits`
- `cause_label_coverage`
- `frequency_by_cause`

Starter classes are defined ex ante from pregame information. Sparse thresholds pool only within the prespecified class; if still sparse, return `INSUFFICIENT_EVIDENCE`.

## Validation questions

1. Distribution: out-of-time mean, variance, quantiles and tails.
2. Threshold: calibration separately at 14.5/15.5/16.5/17.5/18.5 outs.
3. Mechanism: correct cause mix, not merely a correct aggregate distribution produced by offsetting errors.

## Status

- PRESENT ON MAIN: no — research-branch documentation only
- RUNTIME EXECUTED: no Retrosheet dataset audit was executed in the repository
- PRODUCING EVIDENCE: no

A reconstructed standalone LABELRULES_V1 logic harness was executed outside the repository during research; that is not branch-faithful runtime evidence and is not promotion evidence.
