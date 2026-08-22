# Engine B Retrosheet Feasibility Audit

Integration state: `INTEGRATION_UNRUN`.

Research/design only. This document distinguishes what Retrosheet can establish from what would require inference or another point-in-time source. It does not create mechanism evidence and does not authorize Engine B.

Primary references: Retrosheet's official event-file specification, parsed play-by-play crosswalk/data dictionary, and CSV field descriptions.

## Retrosheet structures actually available

### Starter / substitution identity

Event files provide `start` and `sub` records with player ID, team, batting-order position, and fielding position; fielding position `1` is pitcher. A substitution is preceded by a `play,...,NP` marker. `pitching.csv` also provides `p_seq` (`1` = starter), `p_ipouts`, `p_bfp`, and pitching-line statistics.

### Play state

Parsed play-by-play provides inning, top/bottom, outs before/after, visitor/home score, batter, pitcher, handedness where known, event result and baserunner state. It also provides `count`, `pitches`, and `nump` when pitch detail exists.

Retrosheet explicitly warns that pitch detail is not present for every game. Event files expose `info,pitches,pitches|count|none`; blank pitch sequences are a legitimate missing-data state.

### Environment / interruption metadata

Event `info` records can provide `fieldcond`, `precip`, `sky`, `temp`, `winddir`, `windspeed`, and umpire assignments. These are game metadata, not a structured pitcher-removal cause.

`com` records carry explanatory text but are not a complete structured cause taxonomy. Retrosheet defines a structured suspension comment:

`com,"Suspend=YYYYMMDD,ParkID,Vis,Home,Outs"`

That proves a suspension point, but Retrosheet states a game may be suspended by weather **or other conditions**; `Suspend=` alone does not prove weather as cause. Historical Retrosheet data-entry guidance also documents rain-delay comments, but there is no complete standardized player-injury-removal field.

---

## Field availability by LABELRULES_V1 cause

To remove the prior Rule-2/Rule-3 ambiguity, the frozen research taxonomy numbers the declared labels in order:

1. `COMPLETED_PATH`
2. `PITCH_COUNT_EXHAUSTION`
3. `PERFORMANCE_HOOK`
4. `TACTICAL_SUBSTITUTION`
5. `INJURY_HEALTH`
6. `WEATHER_DELAY`
7. `UNKNOWN`

### Rule 1 — COMPLETED_PATH

Required observations:

- starter identity: event `start` at pitcher position or `pitching.csv:p_seq == 1`
- final starter outs / last starter play: `p_ipouts`, play-level `pitcher`, inning and outs
- an ex-ante starter class / target-path definition from pregame information

Availability: **PARTIAL / inferential**.

Retrosheet can establish how long the starter actually remained in the game. It does not contain the manager's pregame intended outing length. Therefore `COMPLETED_PATH` must be defined against an ex-ante, versioned path rule; it is not a direct Retrosheet cause field.

### Rule 2 — PITCH_COUNT_EXHAUSTION

Required observations:

- starter identity
- cumulative starter pitches through exit from `nump` / pitch sequence where available
- `info,pitches` availability state
- pregame workload prior and starter class from point-in-time prior-start information

Availability: **PARTIAL**.

Pitch count is usable only where pitch detail is sufficiently complete. Missing pitch detail must not be imputed into a mechanism label. The exhaustion threshold is relative to the pregame workload prior; Retrosheet cannot supply manager intent or a universal threshold.

### Rule 3 — PERFORMANCE_HOOK

Required observations:

- pitcher identity and exit point
- inning / outs
- score state
- recent plays, runs, hits, walks/baserunners and base state while the starter is responsible pitcher
- a declared performance-hook rule and evidence-strength function

Availability: **INFERENTIAL, not directly observed**.

Retrosheet can reconstruct the performance state immediately before removal. It does not record "manager removed pitcher for poor performance" as a structured cause. Only a frozen deterministic rule can classify high-confidence patterns; ambiguous cases remain `UNKNOWN`.

### Rule 4 — TACTICAL_SUBSTITUTION

Required observations:

- pitcher `sub` event / new pitcher identity
- inning, outs, score and base state
- batter identity/hand and pitcher hand where known
- a predeclared tactical rule using game-state/matchup conditions

Availability: **INFERENTIAL and expected low-confidence**.

Retrosheet proves that a pitching change occurred and provides surrounding state. It generally does not record the manager's tactical motive. Close/low-scoring or platoon context can support a deterministic research rule but cannot become free-form narrative inference. Any unresolved overlap with another inferred hazard is `UNKNOWN`.

### Rule 5 — INJURY_HEALTH

Required observations:

- exit/substitution point
- an explicit contemporaneous Retrosheet `com` record that unambiguously states injury/illness, if present

Availability: **MOSTLY UNCLASSIFIABLE**.

There is no complete structured player-injury-removal field in the event-file specification. `com` text can sometimes carry explanatory material but is not guaranteed or standardized for player injuries. Absence of an injury comment is not evidence of no injury. Unresolved cases remain `UNKNOWN` and must never inflate `PERFORMANCE_HOOK`.

### Rule 6 — WEATHER_DELAY

Required observations:

- exit point
- structured `Suspend=` and/or an explicit delay comment identifying weather/rain near the interruption
- inning/outs/score at interruption

Availability: **PARTIAL / sparse**.

`Suspend=` proves a suspension but not necessarily weather. Pregame `precip`, `sky`, or wind metadata cannot by themselves prove that an in-game pitcher removal was caused by weather. No weather label is allowed from conditions alone.

### Rule 7 — UNKNOWN

Required observations: a valid starter exit record.

Availability: **FULL**.

`UNKNOWN` is the mandatory fallback whenever the source cannot distinguish the mechanism. It is not a data-quality failure; it is the correct label for unresolved competing risks.

## Important out-of-taxonomy case

Retrosheet has structured ejection comments, but `EJECTION` is not one of the seven frozen labels. A starter ejection must not be silently folded into `PERFORMANCE_HOOK` or `TACTICAL_SUBSTITUTION`; under `LABELRULES_V1` it remains `UNKNOWN` unless the taxonomy is deliberately versioned in a future research cycle.

## Coverage contract

Report `cause_label_coverage = classified_exits / total_exits` independently. The classifiable subset gets mechanism-frequency validation. Unclassified exits remain in distribution validation and get their own frequency/bounds report.

## Historical window

For this 2026 research cycle the most recent five **completed** MLB seasons are frozen as:

`[2021, 2022, 2023, 2024, 2025]`

Do not replace this with a rolling expression inside an evidence artifact.

Version-stamp:

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

## D1 conclusion

Retrosheet is sufficient to identify starter chronology, pitching changes, surrounding game state, and—when present—pitch counts. It is **not sufficient to directly observe most removal causes**. Engine B mechanism validation is therefore feasible only as a coverage-aware deterministic labeling audit with a substantial `UNKNOWN` bucket.

That is acceptable by design: classifiable exits receive cause-frequency validation; unclassified exits stay in distribution validation and are reported separately.

## Status

- PRESENT ON MAIN: **NO — research-branch documentation only**
- RUNTIME EXECUTED: **NO — source audit, not a Retrosheet dataset run**
- PRODUCING EVIDENCE: **NO**

A standalone `LABELRULES_V1` logic harness has been executed outside the repository. That is `LOCAL_RECONSTRUCTED_PASS`, not branch-faithful runtime evidence and not promotion evidence.

Sources consulted: Retrosheet official event-file format (`/eventfile.htm`), parsed play-by-play documentation (`/downloads/plays.html`, `/downloads/pbpcrosswalk.html`), CSV content documentation (`/downloads/csvcontents.html`), and Retrosheet's published historical guidance on delay comments.
