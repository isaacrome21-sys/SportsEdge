# Engine B Labeling Rules

## Purpose
Preserve Engine B hazard-label audit rules without silently collapsing overlapping causes.

## Label set
The authoritative Engine B specification defines a **seven-label set**. The exact seven label names are not present in the available summary and therefore are not inferred here. They must be copied verbatim from the authoritative source before implementation or automated labeling.

## Precedence rule
The load-bearing precedence rule is:

- When **Rule 2** and **Rule 3** both fire, assign **`UNKNOWN`** unless one clearly dominates.
- Do **not** silently tie-break overlapping Rule 2 / Rule 3 cases.
- Silent tie-breaking allows one hazard class to absorb another and defeats the audit purpose of the labels.

## Injury handling
Injury is flagged as **probably unclassifiable** under the current labeling design. Do not force injury-driven cases into an existing hazard label simply to avoid `UNKNOWN` or an unclassified state.

## Audit principle
The objective is truthful attribution, not maximizing labeled coverage. Ambiguity is evidence. If competing hazard explanations cannot be distinguished from the predeclared evidence, preserve that ambiguity rather than manufacturing certainty.

## Source fidelity note
This file intentionally preserves only the rules supported by the available summary. The exact seven-label enumeration and full Rule 1–Rule 7 definitions must be copied from the authoritative source specification; they are not reconstructed from memory or general knowledge.
