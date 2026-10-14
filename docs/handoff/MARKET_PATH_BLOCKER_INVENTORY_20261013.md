# Market path / blocker inventory (2026-10-13)

Shared-lane inventory by Grok under owner directive t113u.
- Source: `sportsedge/canonical_coverage.MARKET_RESOLUTIONS` on main `655715907d101052bfc7cb3357f1442db82d8d8b`, crossed with `handoff/dk_catalog_registry_audit_20261013.csv`.
- "CODE PATH ONLY" means a pricing route exists in code. **It is not validation and not eligibility.** Zero families are validated. Every DK offering is UNKNOWN (uninspected).
- Owner rules: rest_adj=0. F5 eligible=false stays. MLB stolen bases (standalone and combos) are NOT_OFFERED.

## Canonical RUN IT, source truth, distribution integrity, forward evidence
| Concern | Path | Status / blocker |
|---|---|---|
| Canonical RUN IT | `artifacts/run_it_full.py` → free_models.calculate (Lane A) → phone_display (#2176) | Research-only cards. No authority. |
| MLB source truth | StatsAPI + trusted clock receipts (#2166 hardening; #2190 starter stack) | EVIDENCE HOLD until the external anchor/host decision (owner, proposal §7) |
| NFL source truth | Byte-frozen nflverse release (G1 contract) | G2 contract file missing (see the NFL G2 handoff) |
| CFB source truth | ESPN injury feed + Form2 bundle | QB identity UNVERIFIED (TEAM_NOT_IN_INJURY_FEED); owner §8/§10 |
| DK quote truth | Paired two-sided quotes, ≤120s skew (main) | No #2143 DK_EVENT_COVERAGE_RECONCILIATION_V1 report stored, so offering is UNKNOWN; DK board captures need an owner decision |
| Distribution integrity | MLB joint distribution / H+BB+ER checks (separate executor) | Pending. PITCHER_HITS_WALKS_ER surface contradiction is open. |
| Forward evidence | Prospective capture only after separate activation | **No activation authorized.** The 2026-27 NBA/CBB preregs wait for forward seasons. |

## Registry markets (89)
| # | Sport | Market | Canonical state | Path status | Precise blocker / next gate | Flags |
|---|---|---|---|---|---|---|
| 1 | MLB | BATTER_BB | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 2 | MLB | BATTER_K | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 3 | MLB | DOUBLES | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 4 | MLB | EITHER_PITCHER_BB | BLOCKED | BLOCKED | NO_ENGINE: No engine for this market is reachable from the canonical intake; a pricer exists only behind the manual-snapshot intake contract (run_canon | SURFACE_UNAVAILABLE_REGISTERED |
| 5 | MLB | EITHER_PITCHER_ER | BLOCKED | BLOCKED | NO_ENGINE: No engine for this market is reachable from the canonical intake; a pricer exists only behind the manual-snapshot intake contract (run_canon | SURFACE_UNAVAILABLE_REGISTERED |
| 6 | MLB | EITHER_PITCHER_HITS_ALLOWED | BLOCKED | BLOCKED | NO_ENGINE: No engine for this market is reachable from the canonical intake; a pricer exists only behind the manual-snapshot intake contract (run_canon | SURFACE_UNAVAILABLE_REGISTERED |
| 7 | MLB | EXTRA_BASE_HITS | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market; a pricer exists only behind the manual-snapshot intake contract (run_canonic | SURFACE_UNAVAILABLE_REGISTERED |
| 8 | MLB | F5_MONEYLINE | BLOCKED | BLOCKED | NO_QUOTE: F5 quotes now bind on the canonical path through sportsedge.mlb_f5_quote_binding (sportsbook + book event ID + verified gamePk fixture + exp; F5 eligible=false stays |  |
| 9 | MLB | F5_RUN_LINE | BLOCKED | BLOCKED | NO_QUOTE: F5 quotes now bind on the canonical path through sportsedge.mlb_f5_quote_binding (sportsbook + book event ID + verified gamePk fixture + exp; F5 eligible=false stays |  |
| 10 | MLB | F5_TEAM_TOTALS | BLOCKED | BLOCKED | NO_QUOTE: F5 quotes now bind on the canonical path through sportsedge.mlb_f5_quote_binding (sportsbook + book event ID + verified gamePk fixture + exp; F5 eligible=false stays | SURFACE_UNAVAILABLE_REGISTERED |
| 11 | MLB | F5_TOTALS | BLOCKED | BLOCKED | NO_QUOTE: F5 quotes now bind on the canonical path through sportsedge.mlb_f5_quote_binding (sportsbook + book event ID + verified gamePk fixture + exp; F5 eligible=false stays |  |
| 12 | MLB | FIRST_HOME_RUN | BLOCKED | BLOCKED | NO_ENGINE: No engine for this market is reachable from the canonical intake; a pricer exists only behind the manual-snapshot intake contract (run_canon |  |
| 13 | MLB | HITS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 14 | MLB | HITS_RUNS_RBIS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 15 | MLB | HITS_RUNS_STOLEN_BASES | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market; a pricer exists only behind the manual-snapshot intake contract (run_canonic | SURFACE_UNAVAILABLE_REGISTERED; SB_COMBO_SURFACE_UNAVAILABLE |
| 16 | MLB | HITS_STOLEN_BASES | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market; a pricer exists only behind the manual-snapshot intake contract (run_canonic | SURFACE_UNAVAILABLE_REGISTERED; SB_COMBO_SURFACE_UNAVAILABLE |
| 17 | MLB | HITS_WALKS_STOLEN_BASES | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market; a pricer exists only behind the manual-snapshot intake contract (run_canonic | SURFACE_UNAVAILABLE_REGISTERED; SB_COMBO_SURFACE_UNAVAILABLE |
| 18 | MLB | HOME_RUNS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 19 | MLB | MONEYLINE | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 20 | MLB | NRFI | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 21 | MLB | PITCHER_BB | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 22 | MLB | PITCHER_ER | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 23 | MLB | PITCHER_HITS_ALLOWED | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 24 | MLB | PITCHER_HITS_WALKS_ER | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false | PHANTOM_OR_CONTRADICTION: PRICED while surface UNAVAILABLE |
| 25 | MLB | PITCHER_K | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 26 | MLB | PITCHER_OUTS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 27 | MLB | PITCHER_RECORD_WIN | BLOCKED | BLOCKED | NO_ENGINE: No engine for this market is reachable from the canonical intake; a pricer exists only behind the manual-snapshot intake contract (run_canon |  |
| 28 | MLB | RBI | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 29 | MLB | RUNS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 30 | MLB | RUNS_RBIS | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market; a pricer exists only behind the manual-snapshot intake contract (run_canonic | SURFACE_UNAVAILABLE_REGISTERED |
| 31 | MLB | RUN_LINE | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 32 | MLB | SINGLES | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 33 | MLB | STOLEN_BASES | PRICED_PATH | NOT_OFFERED (owner rule) | Owner rule: MLB stolen bases NOT_OFFERED; registry still says PRICED_PATH -> registry correction needed (ChatGPT) | WATCH_PHANTOM: owner-flagged; surface claims AVAILABLE via odds_api batter_stolen_bases; DK event still UNKNOWN |
| 34 | MLB | TEAM_TOTALS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 35 | MLB | TOTALS | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 36 | MLB | TOTAL_BASES | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 37 | MLB | TRIPLES | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market; a pricer exists only behind the manual-snapshot intake contract (run_canonic |  |
| 38 | MLB | YRFI | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); deployment eligible=false |  |
| 39 | NFL | alternate_spread | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 40 | NFL | alternate_total | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 41 | NFL | anytime_td | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 42 | NFL | attempts | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 43 | NFL | both_teams_to_score_n | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 44 | NFL | completions | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 45 | NFL | defensive_special_teams_td | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 46 | NFL | fg_made | BLOCKED | BLOCKED | NO_ENGINE: Kicker derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the gov |  |
| 47 | NFL | first_half_moneyline | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 48 | NFL | first_half_spread | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 49 | NFL | first_half_total | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 50 | NFL | first_score | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 51 | NFL | first_td | BLOCKED | BLOCKED | NO_DATA: NO_VERIFIED_FIRST_SCORING_ATTRIBUTION: opening possession is a game-time coin toss recorded only post-game, and no free pre-kickoff source a |  |
| 52 | NFL | interceptions | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 53 | NFL | kicking_points | BLOCKED | BLOCKED | NO_ENGINE: Kicker derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the gov |  |
| 54 | NFL | largest_lead | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 55 | NFL | longest_completion | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market and no other pricer exists for it. |  |
| 56 | NFL | longest_fg_made | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 57 | NFL | longest_reception | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market and no other pricer exists for it. |  |
| 58 | NFL | longest_rush | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market and no other pricer exists for it. |  |
| 59 | NFL | moneyline | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion |  |
| 60 | NFL | pass_plus_rush_yards | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 61 | NFL | passing_tds | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 62 | NFL | passing_yards | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 63 | NFL | player_interceptions | BLOCKED | BLOCKED | NO_ENGINE: Defensive derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the  |  |
| 64 | NFL | player_sacks | BLOCKED | BLOCKED | NO_ENGINE: Defensive derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the  |  |
| 65 | NFL | quarter_moneyline | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 66 | NFL | quarter_spread | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 67 | NFL | quarter_total | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 68 | NFL | race_to_n_points | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 69 | NFL | receiving_yards | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 70 | NFL | receptions | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 71 | NFL | rush_attempts | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 72 | NFL | rush_plus_rec_yards | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE |
| 73 | NFL | rush_yards | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE; NEAR_DUPLICATE_PAIR: rush_yards (QB family) vs rushing_yards (skill family) |
| 74 | NFL | rushing_yards | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion | GOVERNANCE_CONTRADICTION: matrix PRICED vs surface/prop NO_ENGINE; NEAR_DUPLICATE_PAIR: rush_yards (QB family) vs rushing_yards (skill family) |
| 75 | NFL | safety | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 76 | NFL | second_half_moneyline | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 77 | NFL | second_half_spread | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 78 | NFL | second_half_total | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 79 | NFL | spread | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion |  |
| 80 | NFL | tackles_assists | BLOCKED | BLOCKED | NO_ENGINE: Defensive derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the  |  |
| 81 | NFL | targets | BLOCKED | BLOCKED | NO_ENGINE: The empirical gamelog engine's market set excludes this market and no other pricer exists for it. |  |
| 82 | NFL | team_sacks | BLOCKED | BLOCKED | NO_ENGINE: Defensive derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the  |  |
| 83 | NFL | team_total | BLOCKED | BLOCKED | NO_ENGINE: the derivative pricer is wired into the canonical path, but it prices only from an independent joint score distribution (simulation paths);  |  |
| 84 | NFL | team_turnovers | BLOCKED | BLOCKED | NO_ENGINE: Defensive derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the  |  |
| 85 | NFL | total | PRICED_PATH | CODE PATH ONLY (unvalidated) | validation NOT_RUN; DK offering UNKNOWN (uninspected, no #2143 event report); no promotion |  |
| 86 | NFL | total_touchdowns | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 87 | NFL | two_plus_td | BLOCKED | BLOCKED | NO_ENGINE: The anytime-TD engine prices P(at least one TD) only; no P(two or more TDs) pricer exists and the >=2 case is not derived by extending the > |  |
| 88 | NFL | winning_margin_band | BLOCKED | BLOCKED | NO_ENGINE: No pricing engine for this market exists anywhere in the repository; it is a catalog declaration only. |  |
| 89 | NFL | xp_made | BLOCKED | BLOCKED | NO_ENGINE: Kicker derivative pricers exist only over attributed simulation paths (core/simulate); no such paths exist on the canonical path and the gov |  |

| Sport | Markets | State | Blocker |
|---|---|---|---|
| CFB | 51 football surface markets | NOT IN REGISTRY | Surface-only; 0 MARKET_RESOLUTIONS rows; QB identity BLOCKED (TEAM_NOT_IN_INJURY_FEED / Form2 AVAILABILITY_UNVERIFIED); owner §8/§10 decisions; #2192 draft |
| NBA | game/quarter/player | NOT IN REGISTRY | No registry seat; quarter calibration PASS_RESEARCH (refit on examined holdout), OT fix FAILED; 2026-27 preregs pending forward data; pregame player-layer prereg a55c0084 needs registration |
| CBB | ML/spread/total | NOT IN REGISTRY | No registry seat; 2025-26 PASS_RESEARCH (examined); shrunk-HCA prereg registered 40fa4f4, awaits 2026-27 forward season |
| NHL/PGA/UFC | all | NOT IN REGISTRY | RUN IT surface lists PGA/UFC; no engine/registry seat -> NO_ENGINE |

Note: the SB combo rows (15–17) are already BLOCKED NO_ENGINE. Per owner rule they are also NOT_OFFERED. New file: flag for ChatGPT registration.

## t114 update (2026-10-13 ~19:20 CT)

### Registry fix proposal (not on main)
Branch `grok/t114-registry-fix-proposal-20261013` edits `sportsedge/canonical_coverage.py` + its test. If accepted, the counts move from 39 priced / 50 blocked to **24 priced / 65 blocked** (NO_ENGINE 58, NO_QUOTE 2, NO_VALIDATION 4, NO_DATA 1):
- MLB `STOLEN_BASES` → BLOCKED NO_QUOTE, reason `NOT_OFFERED` (owner rule).
- MLB `PITCHER_HITS_WALKS_ER` → BLOCKED NO_QUOTE, reason `PROVIDER_UNAVAILABLE` (mlb_market_surface UNAVAILABLE, provider_expected=false).
- 13 NFL props (passing_yards, completions, attempts, passing_tds, interceptions, rush_yards, pass_plus_rush_yards, rushing_yards, receiving_yards, receptions, rush_attempts, rush_plus_rec_yards, anytime_td) → BLOCKED NO_ENGINE, reason `GOVERNANCE_NO_ENGINE` (prop-engine surface).
- 4 F5 markets → blocker NO_QUOTE → NO_VALIDATION with leading reason `F5_DEPLOYMENT_NOT_ELIGIBLE` (eligible=false stays).
Caveat for review: `artifacts/run_it_full.py` uses the registry only as a fallback for markets it does not route to an engine, so the runtime router still sends NFL props / SB / H+BB+ER to their engines. The proposal fixes the matrix truth only; making runtime match is a separate change for ChatGPT.

### RUN IT / source truth
- Canonical RUN IT: unchanged on main `655715907`; #2176 phone cards post-merge CI green. #2097 / #2103–#2105 (older canonical-run-it stack) are stale: #2103–#2105 fail collection on head.
- MLB source truth: #2190 CODE GREEN / EVIDENCE HOLD; new drafts #2195 (unsafe receipt raw files) and #2196 (malformed intent journals) stacked on it, CI pending at snapshot. External anchor/host decision still the blocker.
- NFL source truth: G2 Amendment 2 / source contract / code still absent (see NFL G2 handoff §6, issue #2161).
- CFB: unchanged (#2182/#2184 on main; QB identity UNVERIFIED; owner §8/§10).
