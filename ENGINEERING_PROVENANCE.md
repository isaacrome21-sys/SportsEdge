# Engineering provenance log

## 2026-09-09 — full-discovery environment contract

Status: durable environment fix recorded; no evidence, floor, eligibility, or Model_P claim is created by this record.

### Historical observation

A full-discovery run previously reported 33 module-import/collection errors. The same failure count was observed on revisions before and after the floor-resolver reordering. The failing interpreter did not have `pytest` installed. The individual historical stack traces were not retained, so this repository does not claim a reconstructed per-error catalogue.

The engineering risk behind the requested classification was whether resolver reordering introduced import breakage at unexercised call sites. The before/after observation rules out a count change across that reordering, and current contracted-environment collection is required to pass for both historical revisions. The historical failure is therefore recorded as an environment-contract failure, not silently reclassified as 33 code defects.

### Root cause and durable invariant

At the time of the failure the repository had no repo-level Python interpreter contract: no `pyproject.toml` `requires-python` declaration and no `.python-version`. CI selected Python independently, so an interpreter/environment without the test runner had no repository invariant to violate. `pytest` was later added to `requirements-test.txt`; that later repair does not retroactively establish that the historical environment was valid.

The repository now defines:

- `.python-version` as the exact CI/local interpreter selection for this workstream;
- `pyproject.toml` `project.requires-python` as the supported Python minor-version range;
- `pyproject.toml` `dependency-groups.dev` as the declared development/test dependency surface, including `pytest`;
- CI assertions that the running interpreter exactly matches `.python-version`, that it satisfies the declared `requires-python` minor-version contract, and that `requirements-test.txt` exactly matches the declared dev dependency group;
- historical before/after collection under that contracted environment, with nonzero collection return codes treated as failures rather than diagnostics only.

### Limits of the record

This entry does not invent the missing 33 stack traces, does not claim they were individually reconstructed, and does not attribute individual errors to code without retained evidence. It records the surviving causal evidence and adds the missing invariant so a future environment mismatch fails explicitly and attribution remains auditable.

No pre-analysis manifest is committed by this change. Governance remains unchanged; this record authorizes no market promotion and creates no fitted-model or replay evidence.

## 2026-09-09 — pre-derivation devig policy freeze

Status: policy decision frozen before any production edge-floor derivation; `truth_gate.edge_floors` remains empty.

The existing schema-v2 `truth_gate.devig_policy` remains the single floor/devig policy surface. The authoritative fair-probability estimator is `POWER_V1` for both below-trigger and longshot candidates. This choice is made before deriving any floor because favorite-longshot bias is continuous rather than appearing only at a single American-odds boundary; `MULTIPLICATIVE_V1` therefore remains a sensitivity/reference method rather than the decision estimator.

The +400 trigger remains frozen as the escalation boundary for three-method sensitivity (`MULTIPLICATIVE_V1`, `POWER_V1`, `SHIN_V1`). At or above that boundary on either side, an absolute fair-probability spread above 0.01 (1.0 percentage point) blocks. Below the trigger, the authoritative estimator is still `POWER_V1`; the three-method sensitivity spread is not promoted into a vote or implicit minimum rule.

The explicit probability haircut remains 0.0 points. The aggregation rule remains `ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS`. These values are policy inputs, not results selected after observing floor, replay, calibration, hit-rate, market-consensus, or handicapper outcomes.

No edge floor is created by this freeze. No market becomes eligible. No Model_P, calibration result, replay depth, hit rate, or evidence record is added or inferred.
