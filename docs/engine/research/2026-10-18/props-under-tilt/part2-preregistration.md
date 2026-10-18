# Part 2: prospective under-tilt diagnostic preregistration

Recorded for issue #2388 on 2026-10-18. This is a diagnostic setup for a NEW committed construction, not recovery or retroactive freezing of the eight historical chat rows.

## Activation and identity
Before pricing the first eligible slate, commit the producing module, exact configuration, pool membership/weights, CV fitting artifact, historical-input identities, quote-selection rule, random seed if applicable, and this protocol. Record their commit/blob hashes in the run manifest. No eligible prospective run exists until those identities and timestamped input/quote receipts are present. This document alone does not activate an engine.
Prospective scoring begins with that first committed, preregistered run. The eight relayed morning rows remain historical-only. Preserve all priced rows before results, not only positive-EV or shortlisted rows.

## Required output on every slate
Report overall under-rate and stratify separately by exact games logged, games buckets 0–2 / 3–5 / 6–9 / 10+, and shrink-weight decile. Shrink weight means weight on the prior, K/(K+n) for the specified pseudo-game construction. Use fixed bins [0,.1), ... [.9,1], not sample-dependent quantiles. Report each numerator, denominator, ties, missing/unpriced count, stat, role, week and game cluster; empty groups are NA.
Count one row per game/player/stat/selected line, not both quote sides or duplicate books. Preserve alternate lines separately from the primary-line denominator; the primary-line selection rule must be pinned before pricing.
Define model under lean as P(under) > P(over), independent of EV or odds; equality is a tie and stays in the priced-row denominator. Report price-selected UNDER frequency separately so market prices cannot be confused with distribution tilt. Preserve negative-EV rows and flags.

## Yardage CV provenance
For EACH yardage stat (passing, rushing, receiving), record source_type as within-player or pooled; exact estimator, fitting seasons, data hash, grouping keys, sample counts, exclusions, zero handling, fitted CV, resulting shape and any posterior-variance contribution.
Within-player means variability around each player's own mean with aggregation/normalization documented. Pooled means dispersion across combined player-game observations with between-player variation retained. Unknown or mixed provenance cannot be silently assigned either label: mark the run incomplete until specified. Do not substitute fantasy-points CV for yardage without an explicitly separate, documented construction.

## Locked diagnostic interpretation
Week buckets: early weeks 3–6, middle weeks 7–9, late weeks 10+; weeks 1–2 reported separately. The early small-sample slice additionally requires n=3–5 games logged.
User's trigger: early under-rate >=80% flags a small-n artifact hypothesis. Retain #2388's late-control discriminator: early >=80% AND late <=60% supports prioritizing small-n shrinkage investigation; without the late control the hypothesis is unconfirmed.
Operational definition of "elevated in every week bucket": under-rate >60% in each evaluable early/middle/late bucket flags role-pool investigation. Empty buckets leave this criterion pending, not passed. Report weeks 1–2 if available without substituting them for required buckets.
These are prespecified investigation rules, not proofs of causal attribution: sample size, uncertainty, market-line placement, CV and selection effects remain relevant. No automatic tuning or replacement of frozen code follows a trigger. Any changed construction is separately versioned and preregistered.

A first slate can open the prospective record and measure its own bias diagnostics. It cannot by itself establish a multi-week pattern when other buckets are absent.

## Archival replay of the NEW construction
Test 1 may evaluate this same pinned new module on 2020–2025 using as-of, past-only inputs. Label it historical evaluation of the new construction, not reproduction of the missing morning module or an untouched holdout.
Report mean prediction error, observed/model median differences, under-rate and fitted-vs-within-player CV by role/week/games bucket. Use archived lines where available. A full-season realized-median proxy uses future outcomes: label it retrospective diagnostic only, never a pregame input or market-edge test. Preserve frozen settings; do not adapt to results and retain the old registration.

## Current state
Protocol committed; producing module, configuration and fitting/input artifacts still unresolved. No slate priced, no archival replay run, no forward record opened by this documentation change.
