# Sept 1 Execution Runbook — Divergent-Topology Amendment

Status at drafting: `INTEGRATION_UNRUN`.

This runbook supersedes any sequence that assumes PR #96 and PRs #102-#106 form a linear stack. They do not. Their branch histories diverged. Merging branch heads is not a valid integration test.

## Required order

0. **Restore infrastructure and verify the substrate.** Confirm GitHub Actions billing/minutes are restored, repository Actions are enabled, and record the current `data` branch head before any execution or merge work.

1. **Proof of life on `main`.** Record the exact baseline SHA. Execute:
   - `python3 scripts/archive_raw_game_odds.py --self-test`
   - `pytest` on `main`
   Record the command output and summary. Inspection is not execution.

2. **Restart the archive before any merge work.** Archive capture is the only lane losing unrecoverable data.
   - Choose one MLB game and target either T-90m or T0 in America/Chicago time.
   - Hand-count every game whose target lies inside the script's `+/-8 minute` acceptance band.
   - Write the expected `games_eligible` count down **before** running.
   - Run:
     `SPORTSEDGE_EXECUTION_MODE=MANUAL python3 scripts/archive_raw_game_odds.py`
   - Verify `capture_window` matches the target aimed at.
   - Verify `games_eligible` equals the pre-registered count.
   - `BLOCKED_NO_CREDITS` is a PASS for this acceptance test; the test is window math, not successful price capture.
   - Persist the status row durably to `data` and push immediately.
   - Never change the pre-registered count after observing output.
   - Never backfill the Aug 17 outage gap.

3. **Harden `AutoRunReport` construction before composition.** Convert every construction site to keyword arguments. Add a regression mechanism that prevents positional construction from being reintroduced after future schema changes. PR #96's T1-T4 runner tests do not cover every constructor site, so green T1-T4 cannot be treated as coverage of this risk.

4. **Compose PR #96 changes onto one frozen base, then execute that exact tree.** Do not merge the branch head as a proxy for composition. Confirm T1-T4 actually execute:
   - **T1:** offered market + no engine -> `NO_ENGINE`; never absent and never PASS.
   - **T2:** declared market never fetched -> `ACQUISITION_MISSING`.
   - **T3:** all rows BLOCKED -> composed `run_status != READY`; this is a composition rule, not a string-only check.
   - **T4:** retry-eligible prop absent inside its availability window -> `NOT_OFFERED`; overall run health is not degraded.

   Expect seam breakage. Engines A/B/C were logic-verified against reconstructed/local files, not branch-faithfully integrated.

5. **Compose PRs #102-#106 onto the same proven frozen tree.** Apply their individual changes, not branch-head assumptions. Run imports, unit tests, and seam tests on that exact composition. Individual component/local PASS results remain component evidence only.

6. **Run the frozen fixture twice, then under irrelevant execution variation.** Everything is frozen, including the market snapshot. Require byte-identical canonical decision output for:
   - run A vs run B under the same frozen inputs,
   - a fresh process,
   - a different working directory,
   - a different wall-clock execution time.

   A changed canonical decision payload means nondeterminism: unseeded RNG, environment leakage, ordering instability, or a timestamp/process artifact leaking into the decision artifact.

7. **Only after the exact composed tree proves itself may merge cleanup begin.** Verify every merge SHA and CI conclusion. Do not claim a merge or integration PASS from inspection, reconstructed execution, or component-only tests.

## Hard invariants

- `INTEGRATION_UNRUN` remains the integration state until the exact composed tree executes successfully.
- Do not unpark V6 because CI resumes.
- Do not relax any threshold to increase bet count.
- Do not reinterpret `NO_ENGINE` as PASS.
- Do not backfill missing archive observations from the outage.
- Report `PRESENT`, `EXECUTED`, and `EVIDENCE` separately.
