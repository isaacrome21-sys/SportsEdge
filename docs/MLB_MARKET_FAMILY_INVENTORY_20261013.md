# MLB market-family inventory vs #2143 DK event-offering reconciliation (2026-10-13)

Research inventory only. **Nothing is promoted.** `config/deployments.json` was read, not changed. Market baseline MISSING everywhere.

## Column meanings
- **Offered (per event):** comes from `sportsedge.provider_book_evidence_audit` (#2143) applied to a caller-supplied DK event report.
  - No DK event reconciliation report is stored in the repo today, so every event is **UNKNOWN (uninspected)**.
  - That is never NOT_OFFERED and never a universal claim. A family becomes OFFERED_ON_THIS_EVENT or NOT_OFFERED_ON_THIS_EVENT only for an inspected event.
- **Engine:** the `stage` field in `config/deployments.json`.
- **Validation:** `config/mlb_validation_evidence.json` evidence status, with `—` meaning no field recorded.
- **Decision:** `eligible=false` everywhere, so the decision is BLOCKED (no PLAY authority). WATCH would be possible only for research display with no stake, and none is granted here.

| family | market | offered (per event) | engine stage | validation | eligible | decision | notes |
|---|---|---|---|---|---|---|---|
| Game ML/RL/total | MONEYLINE | UNKNOWN (uninspected) | VALIDATED_MATH | — | false | BLOCKED | live production inference path not attested |
| Game ML/RL/total | RUN_LINE | UNKNOWN (uninspected) | VALIDATED_MATH | — | false | BLOCKED | deployment parity unresolved |
| Game ML/RL/total | TOTALS | UNKNOWN (uninspected) | VALIDATED_MATH | — | false | BLOCKED | fresh calibration required |
| Team totals | TEAM_TOTALS | UNKNOWN (uninspected) | SHARED_READOUT_CANDIDATE | UNRUN | false | BLOCKED | shared V7 score-distribution readout implemented; historical PIT, calibration, forward evi |
| First inning | NRFI | UNKNOWN (uninspected) | CANDIDATE_FORM | — | false | BLOCKED | negative-binomial form implemented; empirical parameters and forward evidence still requir |
| First inning | YRFI | UNKNOWN (uninspected) | CANDIDATE_FORM | — | false | BLOCKED | negative-binomial form implemented; empirical parameters and forward evidence still requir |
| F5 sides/totals | F5_MONEYLINE | UNKNOWN (uninspected) | F5_STATE_CANDIDATE | UNRUN | false | BLOCKED | strictly-prior actual first-five score distribution implemented; PIT holdout, calibration, |
| F5 sides/totals | F5_RUN_LINE | UNKNOWN (uninspected) | F5_STATE_CANDIDATE | UNRUN | false | BLOCKED | strictly-prior actual first-five score distribution implemented; PIT holdout, calibration, |
| F5 sides/totals | F5_TOTALS | UNKNOWN (uninspected) | F5_STATE_CANDIDATE | UNRUN | false | BLOCKED | Grok #2156: per-event offering via #2143 audit; UNKNOWN unless inspected |
| F5 sides/totals | F5_TEAM_TOTALS | UNKNOWN (uninspected) | F5_STATE_CANDIDATE | UNRUN | false | BLOCKED | Grok #2156: walk-forward lost to naive; prereg ZINB 2024→2025 holdout FAIL |
| Batter props | HITS | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | RESET (RNG_IDENTITY_QUOTE_SIDE_REMOVED) | false | BLOCKED | shared strictly-prior game-row engine implemented; PIT holdout, calibration, forward evide |
| Batter props | HOME_RUNS | UNKNOWN (uninspected) | GENERIC_MEASURED_BASELINE | — | false | BLOCKED | measured generic baseline remains canonical; joint HOME_RUNS candidate requires independen |
| Batter props | TOTAL_BASES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | RESET (RNG_IDENTITY_QUOTE_SIDE_REMOVED) | false | BLOCKED | shared game-row engine implemented; HITS/TB coherence repaired; evidence ladder required |
| Batter props | RBI | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | shared game-row engine preserves multi-RBI outcomes; behavioral validation required |
| Batter props | RUNS | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | shared strictly-prior game-row engine implemented; evidence ladder required |
| Batter props | STOLEN_BASES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | shared strictly-prior game-row engine implemented; evidence ladder required |
| Batter props | BATTER_BB | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | shared game-row engine enforces realized PA support; evidence ladder required |
| Batter props | EXTRA_BASE_HITS | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | exact marginal of doubles+triples+home runs from same prior-game rows; no promotion eviden |
| Batter props | SINGLES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | exact hit-type marginal from same prior-game rows; evidence ladder required |
| Batter props | DOUBLES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | exact hit-type marginal from same prior-game rows; evidence ladder required |
| Batter props | TRIPLES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | exact hit-type marginal from same prior-game rows; evidence ladder required |
| Batter props | BATTER_K | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | same prior-game PA-supported rows; evidence ladder required |
| Batter props | HITS_RUNS_RBIS | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | exact arithmetic on same prior-game rows; evidence ladder required |
| Batter props | HITS_RUNS_STOLEN_BASES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | exact arithmetic on same prior-game rows; no promotion evidence yet |
| Batter props | RUNS_RBIS | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | exact arithmetic on same prior-game rows; no promotion evidence yet |
| Batter props | HITS_STOLEN_BASES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | exact arithmetic on same prior-game rows; no promotion evidence yet |
| Batter props | HITS_WALKS_STOLEN_BASES | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | exact arithmetic on same prior-game rows; no promotion evidence yet |
| Batter props | FIRST_HOME_RUN | UNKNOWN (uninspected) | ORDERING_AWARE_CANDIDATE | UNRUN | false | BLOCKED | confirmed-lineup ordering-aware first-HR simulation implemented; no-HR sportsbook policy,  |
| Pitcher props | PITCHER_K | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | shared prior-start joint pool implemented; evidence ladder required |
| Pitcher props | PITCHER_OUTS | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | bounded [0,27] joint workload pool implemented; historical quote evidence required |
| Pitcher props | PITCHER_ER | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | crooked-inning shape retained empirically; historical quote evidence required |
| Pitcher props | PITCHER_HITS_ALLOWED | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | — | false | BLOCKED | shared prior-start joint pool implemented; evidence ladder required |
| Pitcher props | PITCHER_BB | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | RESET (RNG_IDENTITY_QUOTE_SIDE_REMOVED) | false | BLOCKED | shared prior-start joint pool implemented; evidence ladder required |
| Pitcher props | PITCHER_HITS_WALKS_ER | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | exact combined marginal from same prior-start rows; evidence ladder required |
| Pitcher props | EITHER_PITCHER_HITS_ALLOWED | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | Grok #2156: 2025 PASS_RESEARCH, small; retrospective probable-pitcher identity; settlement UNVERIFIED_DK_RULES |
| Pitcher props | EITHER_PITCHER_BB | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | same as above |
| Pitcher props | EITHER_PITCHER_ER | UNKNOWN (uninspected) | JOINT_ENGINE_CANDIDATE | UNRUN | false | BLOCKED | PASS_RESEARCH 2025 but 2024 loses; unstable |
| Pitcher props | PITCHER_RECORD_WIN | UNKNOWN (uninspected) | WIN_CREDIT_STATE_CANDIDATE | UNRUN | false | BLOCKED | strictly-prior starter workload is crossed with today's actual-F5 score distribution and t |

## Summary
- 38 markets. 0 eligible, 0 PLAY, 0 inspected events.
- **Main gaps for every family:**
  - paired timestamped DK quotes (market baseline);
  - per-event DK offering reports run through #2143;
  - PIT holdouts and calibration;
  - settlement-rule capture;
  - production parity.
- **To move a family off UNKNOWN:** feed a captured DK event report (schema `DK_EVENT_COVERAGE_RECONCILIATION_V1`) through `audit_provider_book_evidence`. Do not hand-edit this table.
