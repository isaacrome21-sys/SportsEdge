# SportsEdge finish audit — 2026-09-28 UTC

This is an operational audit, not a promotion or performance readout. No real CLV/ROI gate was evaluated.

## Verified repository changes

- #1108 merged at b23654ad: Python cache ignores and 1e-12 routing-test tolerance.
- #1107 merged into #1084: earliest valid decision per game/market/selection; exact duplicate evidence and mixed-market rejection; missing coverage blocks; pre-kickoff PENDING reporting.
- #1111 merged normally at 9b9e0e0fd4477c34b77c338acc5458c87f08591f. Its two evaluator files match #1084 head 40571654 byte-for-byte. #1084 was closed only after this preservation check.
- Main ruleset 23637426 requires `main-merge-hold from the freeze-reconciliation-hold` and `CFB readiness`, with strict up-to-date checks. Both ran. The old branch was behind; a commit-status API returning no entries did not mean check-runs were absent.
- #1112 consolidates inference enforcement. Frozen policy bytes are bound to Git blob 00fd09af015fe60f18a8d325c2dde3e9c7c123ee. Both IID and CR1 week-cluster tests must pass; at least 12 clusters; clustered cutoff max(2, Student-t 0.975 with G-1 df). The attached alternative patch's numeric-drift gap is not adopted. Added workflow coverage and strict drift/hand-calculation tests; 54 targeted tests pass.

## Forward archive verification

Inspected data commit ebda0861bec9e737e1878abb2687dd3ffa428145, not just green workflow badges.

| Lane | Observed records | Remaining limit |
|---|---|---|
| NFL Week 2 opener | Explicit MISSED_OR_BLOCKED | Cannot reconstruct/backfill |
| NFL Week 2 close | 10 games in two canonical final files; both raw hashes verify | Four other kickoff groups have missed markers |
| NFL Week 3 opener | 16 games; raw hash verifies; run 35742109751 matches source commit/time | Price archive only |
| NFL Week 3 canonical close | 2 games in final/20260927T200334Z.json; raw hash verifies; run 36346587981 matches | Other groups missed |
| NFL Week 3 Rams–Broncos close | One game in legacy final_20260927T235000Z.json; raw hash verifies; run 36358567364 ran 23:24–23:50 UTC | Shared reader ignores this legacy path; do not silently rewrite historical evidence |
| NFL attempt-9 decisions/outcomes | No decision/evidence schema records found under data, runtime or archive; no attempt9 paths | No model-specific forward clock verified; no scheduled caller of build_decision/write_decision |
| NBA/NHL | No sport capture paths found on inspected data commit | Forward capture unverified |

The direct NFL writer used `weekNN/final_TIMESTAMP.json` while shared consumers scan `weekNN/final/*.json`. This repair changes future writes to the canonical directory. A producer-to-reader regression test verifies visibility. It does not move old files or erase missed markers. Historical legacy-path admission needs a separate provenance adjudication.

Price captures do not imply model decisions. Settlement cannot repair absent pregame decisions. Existing v2g or other research lanes cannot be relabeled attempt-9 evidence.

## Backlog disposition

- #467, #717 and #963 were already closed when rechecked.
- #824 closed: all 16 changed paths identical to verified main 0ecfa75.
- #993 closed: ancestor of open #996, with both added files unchanged in the descendant.
- #1013 was already closed; its two-file scoring-composition contract is preserved on main. This does not preserve every ancestor's full change set.
- #1062 is the canonical Score-B board integration candidate, still parked pending integration/testing. Preserve differing #996/#999/#1002/#1010/#1031 work until each dependency is accounted for.
- All 82 remaining PRs in the read snapshot were compared path-by-path to main 9b9e0e0f; none met the all-changed-paths-identical closure rule. This does not prove they are all needed: it means no further byte-identical closure was justified.
- CFB/NBA/NHL PRs were converted to drafts where needed and labeled parked. No age-based closure.

## Scheduled work

The paid closing-line archive and paused CFB weather collector lose their cron triggers and remain manually dispatchable. This removes 288 + 144 configured launches/day. Their allowlist entries are removed. The cron audit passes. NFL attempts 3–10 already have no schedules, so no runtime shutdown was necessary. Active NFL confirmation and irreversible source collectors remain untouched.

## Completion dependencies

| Sport | Verified code | Work needed before a clean model clock / promotion |
|---|---|---|
| NFL | Frozen attempt-9 artifacts, immutable decision/evidence contracts, evaluator | Bind real pregame features to frozen runtime prediction; schedule immutable decisions; capture original-threshold closes; source settlements; prove per-market coverage; accumulate required weeks/decisions |
| MLB | Joint game-path research and PIT capture modules | Review #1029 feature freeze, fit/calibrate frozen full-game partitions, verify lineup/starter/bullpen/park/weather provenance and forward prices; no inheritance by props |
| NBA | Simulation, availability/rotation, training/calibration, integrated engine modules | Integrate #1018/#1042 without discarding unique work; freeze fitted model; timestamp injury/availability inputs; paired price capture and settlement |
| NHL | Simulation, rate fitting, pricing, roles and OT/period modules | Review #916/#1043; bind fitted rate/goalie artifacts; PIT goalie confirmation and invalidation; settlement validation and paired forward capture |
| CFB | Frozen research candidates and source audits | Finish #1067 postmortem; maintain pause until candidate and timestamped source contract are accepted; no historical/current source relabeled a clean close |

The earlier claim that NHL had no simulator was stale. Module existence does not establish fitted artifact quality or evidence eligibility. Likewise #1018 (integration) and #1042 (pace fitting) are complementary work, not an automatic either/or choice.

No sport can be completed by asserting a future sample already exists. No cross-sport policy is silently substituted for the NFL-only 2026 inference addendum. Future seasons need explicit policy handling; the current addendum is scoped to 2026.
