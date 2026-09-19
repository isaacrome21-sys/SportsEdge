# Engine readiness and public repository review — 2026-09-19

This is an engineering review, not model-validation or promotion evidence.

## Immediate operational repair

NFL confirmation capture previously committed and pushed from its code checkout. Protected main can reject that write and lose newly captured bytes when the runner exits. The repair restores the existing data-branch archive before admission, refuses differing bytes at an existing identity, persists through the existing create-only data-branch writer, and preserves a uniquely named per-run artifact even on failure.

The workflow is part of the capture hash lock. Its changed hash must remain visible as a mismatch against any existing lock. This repair does not reset locks, change frozen capture windows or models, adjudicate records, or authorize promotion. A hosted capture/persistence run is still required to establish operation. Restoring previously captured bytes is not retrospective capture or backfill.

## Public repositories inspected

| Repository | Applicable use | Decision |
| --- | --- | --- |
| https://github.com/actions/upload-artifact | Per-run artifact retention, unique names and fail-path upload | Use the existing pinned official action for NFL recovery backup; durable archive remains the data branch. |
| https://github.com/nflverse/nflreadpy | NFL data access | Keep existing nflverse schedule contract; a new client does not repair scheduler or persistence failures. |
| https://github.com/jldbc/pybaseball | Statcast, FanGraphs and Baseball Reference research data | Candidate for separately preregistered research; do not substitute these inputs into the frozen StatsAPI engine. |
| https://github.com/CFBD/cfbd-python | Official CFBD API client | Does not remove provider quota or change the frozen advanced-stat source contract. No substitution. |

No third-party model code was copied, and no new predictive dependency was introduced.

## Remaining readiness boundaries

- CFB: reconstructed materialization remains quota-blocked; the frozen plan requires 244 calls plus a 50-call reserve. Selection, fitting and prospective validation remain necessary.
- NFL: the workflow is enabled, but no scheduled run newer than September 17 was returned in the reviewed schedule query. A successful pull-request contract job does not establish live capture continuity.
- MLB: all 38 markets remain deployment-ineligible, without frozen edge floors. The live shadow-run stack trace showed waits in MLB StatsAPI team-history transport. Import repair does not establish live provider availability or paper-card completion. The 2027 promotion-evidence boundary remains unchanged.
