# Research Freeze Status Matrix

Integration state: `INTEGRATION_UNRUN`.

This matrix separates repository presence, runtime execution, and verified evidence. Those states must never be collapsed.

| Item | PRESENT | EXECUTED | EVIDENCE | Notes |
|---|---|---|---|---|
| Main green fixture pipeline | YES | YES | YES | Existing verified baseline on main. |
| MULTIPLICATIVE_V1 paired-price devig | YES | YES | YES | Existing main behavior; 12-decimal assertion. |
| V7 game-totals engine | YES | YES | Existing evidence only | 50K default; no change under freeze. |
| V5 NRFI incumbent | YES | YES | YES / incumbent | Frozen incumbent; V6 remains parked. |
| Archive script/window logic | YES | YES historically | Current in-window acceptance UNRUN | T-180/T-90/T0 +/-8m windows present. |
| PR #96 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | Divergent topology; T1-T4 must run on exact composed tree. |
| PR #101 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | Heartbeat detection/delivery acceptance still unrun. |
| PR #102 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | No-vig consensus/EV. |
| PR #103 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | Candidate targeting. |
| PR #104 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | Distribution construction. |
| PR #105 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | Freshness/features; 50K default, 10K minimum. |
| PR #106 | YES on PR | COMPONENT/LOCAL only | NO integration evidence | Execution-price context. |
| PR #107 | YES on PR | docs only | NO runtime evidence required | Pending; untouched by this branch. |
| PR #108 | YES on PR | schema/docs only | NO pipeline evidence | Ledger contract; untouched by this branch. |
| Frozen RUN IT fixture spec | YES on docs branch | NO | NO | Must execute on exact composed tree Sept 1. |
| Sept 1 divergent-topology runbook | YES on docs branch | NO | NO | Documents required execution sequence. |
| Research backlog tiers | YES on docs branch | NO | NO | Research-only hypotheses. |
| Manual-analysis research-set rule | YES on docs branch | N/A | NO pipeline evidence | Retroactive Model_P/hash reconstruction prohibited. |
| V6 evidence-integrity spec | YES on docs branch | NO | NO | Integrity fix only; no V6 redesign. |
| Engine B LABELRULES_V1 | YES on docs branch | NO | NO | Shadow-only, separate evidence clock. |
| Heartbeat/status spec | YES on docs branch | Detection acceptance UNRUN | Delivery acceptance UNRUN | Detection and delivery are separate gates. |
| Archive acceptance test | YES as procedure | UNRUN | NO | Pre-register games_eligible before run. |
| Heartbeat stale detection | YES as procedure | UNRUN | NO | Must detect current stale lane. |
| Heartbeat alert delivery | YES as procedure | UNRUN | NO | Delivery previously disabled; separate gate. |

## Frozen conclusions

- `INTEGRATION_UNRUN` regardless of individual component PASS counts.
- No code, math, thresholds, promotion gates, or pending PRs were changed by this documentation branch.
- Research findings remain hypotheses until their prespecified evidence exists.
- `NO_ENGINE` never renders as PASS.
- Full coverage means every offered market is accounted for, not that every market generates a wager.
