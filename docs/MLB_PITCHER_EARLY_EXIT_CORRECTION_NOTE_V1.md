# Correction note — MLB pitcher early-exit V1 freeze provenance

**Status: CORRECTION. No change to any verdict, number, or code.**

The case-check record (`docs/MLB_PITCHER_EARLY_EXIT_CASE_CHECK_V1.md`) states that the
preregistration was committed alone as commit `6f2217716` before any component or
scoring code existed.

Repo check, done after the record was written:

- `6f2217716` does not exist in the repository. `get_commit` returns "No commit found."
- On this branch, the only commit above `main` (`07b46d383`) is `8e2033fd5`
  (2026-10-19 03:49:18Z), which contains the prereg, the component, and the case check together.
- The freeze-order copy branch `research/mlb-pitcher-early-exit-v1-freeze-order-20261018`
  has its prereg-freeze commit `a093907438d496c01b4a52b59c981c5d1087a0fc` at
  2026-10-19 03:51:41Z, which is after `8e2033fd5`.

**What this means:** the prereg-before-code order is **builder-attested, not repo-verifiable.**
The builder reports a local-only commit `6f2217716` at 03:37:06Z that was squashed
before push. The repo does not contain that commit, and the copy branch's freeze
timestamp comes after the primary branch's build.

**Unchanged:** the prereg content hash (`d9b276a4…`, the prereg file on this branch),
the case-check numbers, the verdict CASE_CHECK_PASS, and n = 2. This is a case
check, not validation. Component remains research-only and wired into nothing.

Audit thread: SportsEdge #2409, comment `6267887116`.
