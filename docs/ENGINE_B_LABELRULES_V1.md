# Engine B Removal-Cause Labeling — `LABELRULES_V1`

Status at drafting: `INTEGRATION_UNRUN`.

Engine B is shadow-only with an evidence clock isolated from V6.

## Labels

Exactly one label per exit:

- `COMPLETED_PATH`
- `PITCH_COUNT_EXHAUSTION`
- `PERFORMANCE_HOOK`
- `TACTICAL_SUBSTITUTION`
- `INJURY_HEALTH`
- `WEATHER_DELAY`
- `UNKNOWN`

The labels are mutually exclusive and exhaustive. Frequency totals must sum to 100% across all exits.

## Workload prior

Pitch-count exhaustion is never defined by one universal threshold. Each start requires a pregame workload prior built only from information available before that start. A pitch count that is routine for a durable workhorse may represent exhaustion for a pitcher building back from injury.

Starter classes and workload priors must be defined ex ante and versioned.

## Score-state rule

Score state is bidirectional and asymmetric. Large leads and large deficits can both shorten outings for different reasons. A single monotone run-differential effect is structurally unsafe.

## Competing-rule precedence

When Rule 2 and Rule 3 both fire, assign `UNKNOWN` unless one cause dominates by a predeclared margin. Never silently break ties. Silent precedence lets one hazard absorb another and defeats the mechanism audit.

## Tactical substitution

Tactical pulls can concentrate in close, low-scoring games — exactly the games that decide unders. Folding tactical exits into `PERFORMANCE_HOOK` can preserve the mean while corrupting the left tail.

## Injury / health

Injury exits are expected to be incompletely identifiable from Retrosheet-like event data. If the reason cannot be established, leave the exit `UNKNOWN`. Never inflate `PERFORMANCE_HOOK` with unclassified injury exits.

## Weather / delay

Weather/delay exits are rare but contribute pure left-tail mass. Even low frequency matters near pitcher-outs thresholds such as 14.5/15.5.

## Coverage reporting

Report `cause_label_coverage` independently. If 60% of exits are classifiable, report 60%.

Two-layer reporting:

1. classifiable subset: compare cause frequencies,
2. unclassified subset: report frequency and bounds separately.

Unclassified exits still participate in distribution validation; they are not dropped because mechanism is unknown.

## Historical window

Use the most recent five completed seasons, with the exact season list frozen into the evaluation artifact. Bullpen and starter-leash behavior are not assumed stationary across a decade.

## Required version stamp

Each artifact must include:

- `historical_seasons`
- `starter_class_version`
- `workload_prior_version`
- `labeling_rules_version`
- `total_exits`
- `classified_exits`
- `unclassified_exits`
- `cause_label_coverage`
- `frequency_by_cause`

Sparse thresholds pool only within a predeclared starter class. If evidence remains sparse, report `INSUFFICIENT_EVIDENCE`; do not borrow strength opportunistically after seeing results.

## Three validation questions

1. **Distribution:** are mean, variance, quantiles, and tails correct out of time?
2. **Threshold:** is `P(Over X.5)` calibrated separately at 14.5, 15.5, 16.5, 17.5, and 18.5? Pooled calibration can hide a broken left tail.
3. **Mechanism:** is the distribution correct for the right reasons? A calibrated 17.5 threshold is not enough if exaggerated weather risk offsets an under-modeled performance hook.

## Implementation order

1. Confirm required Retrosheet fields actually exist.
2. Freeze the exact historical window.
3. Build the pregame workload prior.
4. Implement `LABELRULES_V1`.
5. Run the cause-label coverage audit.
6. Only then build the competing-risk simulator.

## Status convention

- Label spec: `PRESENT`
- Coverage audit actually run: `EXECUTED`
- Out-of-time mechanism/distribution evidence: `EVIDENCE`
