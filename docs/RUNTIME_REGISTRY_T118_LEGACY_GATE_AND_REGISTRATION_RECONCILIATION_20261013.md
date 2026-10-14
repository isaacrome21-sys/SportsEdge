# t118 — Legacy-runner registry gate + governance registration reconciliation (2026-10-13)

Branch `grok/t118-legacy-runner-gate-20261013`, stacked on #2205 head 9e204aee.
Research-only. No activation, no holdout, no real quotes; tests are synthetic.
Code completion is NOT validation; zero families are validated.

## 1. Shared gate
`sportsedge/registry_gate.py` is the single implementation. `artifacts/run_it_full._registry_blocked_row`
now delegates to it (the `registry_lane_internals` marker in `tests/conftest.py` still patches that
name, so its behaviour is unchanged).

## 2. Behaviour change — fail-closed UNREGISTERED
* MLB/NFL (registered sports): a market none of whose names resolve -> blocked row,
  `blocker=UNREGISTERED`, `registry_state=UNKNOWN`.
* Sports with no registry (CFB, NBA, CBB, ...): every market blocked UNREGISTERED **except** core
  game markets (ML/MONEYLINE/H2H, SPREAD/RUN_LINE, TOTAL/TOTALS), which pass labelled
  `registry_status=SPORT_NOT_IN_REGISTRY`. **Interim exception / residual** — remove once ChatGPT
  registers CFB/NBA/CBB. Empty/unknown sport: always blocked.
* In run_it_full the UNREGISTERED check runs post-evaluation and only on rows that came back
  PRICED, so a lane's more specific fail-closed reason (e.g. ILLINOIS_COLLEGE_EXCLUDED) is kept.
  CFB player props can no longer carry a price on the canonical card.
* Legacy runners: rows already unpriced are untouched; priced rows on blocked/unregistered markets
  are replaced by the blocker row (pricing keys dropped). Each card gets a `registry_gate` stamp.
* New real bypass closed: `sportsedge/unified_card.py` accepted generic MLB markets the registry
  blocks (STOLEN_BASES, PITCHER_HITS_WALKS_ER, F5_*, TRIPLES, RUNS_RBIS, *_STOLEN_BASES,
  EITHER_PITCHER_*, EXTRA_BASE_HITS, FIRST_HOME_RUN, PITCHER_RECORD_WIN); now BLOCKED before the
  generic pipeline.

## 3. Runner dispositions (all WRAPPED; none refused, since all are referenced)
| Runner | Prices | Callers | Disposition |
|---|---|---|---|
| scripts/run_auto_dk_cards.py | NFL/CFB/MLB cards via sub-runners | sportsedge-auto-dk-four-sports.yml | wrapped (summary.json) |
| scripts/run_auto_mlb.py | MLB game board | auto-mlb, live-full-model-expansion, mlb-pit-observation-contract, mlb-fixture-full-pipeline, mlb-v8-evidence, mlb-same-fetch-pit-source-contract; auto_runner, auto_native_odds, auto_espn_odds, run_mlb_v8_forward_lane_v2 | wrapped |
| scripts/run_auto_mlb_resilient.py | MLB game board | auto-mlb, mlb-pit-observation-contract, mlb-same-fetch-pit-source-contract, mlb-v8-evidence; v8 forward lanes, run_auto_cfb_resilient | wrapped |
| scripts/run_auto_nfl_resilient.py | NFL spread/total | auto-nfl.yml | wrapped (both write paths; full_board from gated payload) |
| scripts/run_nfl_lines_card.py | NFL lines + phone board | nfl-lines-issue.yml; unified lines, auto_dk, render_nfl_myspari_card | wrapped |
| scripts/run_nfl_unified_lines_card.py | NFL lines + props | run_auto_dk_cards | wrapped |
| scripts/run_cfb_sdv_card_v2.py | CFB ML/SPREAD/TOTAL | cfb-market-anchored-spread-fit, cfb-lines-issue, cfb-sdv-card, cfb-saturday-full-fbs-board; import_cfb_public_odds_page, auto_dk | wrapped (core only -> unaffected, labelled) |
| scripts/run_manual_mlb_snapshot.py | MLB snapshot props/games | manual-mlb-snapshot, manual-mlb-fast-lines, mlb-lines-issue; auto_dk | wrapped |
| sportsedge/live_run_it.py | live ML/SPREAD/TOTAL | live-full-model-expansion; run_it_live, free_models, live_reprice, run_live_run_it | wrapped (card return) |
| sportsedge/unified_card.py | MLB generic markets | mlb-fixture-full-pipeline, mlb-validation-audit, mlb-run-machine-contract; auto_runner, auto_joint_runner, manual_hybrid_joint_runner | per-quote gate before pipeline |

Scheduled workflows whose output can change (blocked rows instead of prices): every workflow above.
Expected visible change: NFL props/TD/team-total/1H rows and MLB SB/H+BB+ER/F5 rows show blockers;
CFB core cards unchanged except the label.

## 4. Residual bypass
* Gate on scripts keys on dicts with a `market`/`market_key`/`market_type`/`bet_type` name and a
  non-null pricing key (model_p, probability, fair_odds, ev, edge, ...). A runner that emits a price
  under another key name, or renders text/images (e.g. `image_card` PNGs in run_auto_dk_cards,
  render_nfl_myspari_card) from pre-gate data, is not covered.
* Other entry points not in the t118 list (run_auto_cfb_resilient, run_nfl_auto, run_nfl_fair_odds_card,
  run_nfl_coherent_props, run_cfb_sdv_card v1, research runners) are not wrapped.
* Core-game exception for unregistered sports (above).
* Script wiring is proven by AST ordering tests + helper functional tests, not by end-to-end
  workflow runs (those need live sources).

## 5. Governance registration reconciliation
| Path | #2202 | t117 | #2205 | t118 |
|---|---|---|---|---|
| sportsedge/mlb_source_identity.py, mlb_public_{batter,pitcher}_history.py, research/mlb_joint_team_runs.py | x | x | | |
| tests/test_mlb_joint_team_runs_research.py, tests/test_mlb_source_identity.py | x | x | | |
| docs MLB_* (3) + generic-features .patch | x | x | | |
| sportsedge/mlb_generic_features.py, config/mlb_model_surface_v1.json (re-pin), tests/test_mlb_batter_source_identity_wiring.py, docs/MLB_T117_GOVERNANCE_REGISTRATION_LIST | | x | | |
| sportsedge/canonical_coverage.py | | | x | |
| artifacts/run_it_full.py | | | x | x (delegates to shared gate) |
| tests/conftest.py (new) | | | x | unchanged |
| tests/test_runtime_registry_enforcement_20261013.py + 9 marked test files | | | x | unchanged |
| sportsedge/registry_gate.py (new), tests/test_legacy_runner_registry_gate_20261013.py (new), this doc | | | | x |
| 8 runner files (scripts/*, live_run_it.py, unified_card.py) | | | | x |

* No file overlap between the MLB stack (#2202/t117) and the enforcement stack (#2205/t118);
  trial merge of t117 into t118 is clean.
* `artifacts/run_it_full.py` is changed by #2205 and again by t118 — register the t118 version only
  if t118 lands; registering 9e204aee's hash and then landing t118 would require a re-registration.
* `tests/conftest.py` is new in #2205 and global (autouse fixture): it affects every test module,
  including #2202's. Reviewer should confirm it only acts on `registry_lane_internals`.
* t117's `config/mlb_model_surface_v1.json` pin covers `mlb_generic_features.py` only; no t118 file is
  pinned there. If any manifest pins `run_it_full.py`, `live_run_it.py` or `unified_card.py`, it needs
  a re-pin with t118 (none found failing in the full suite).
* Order suggestion: #2205 -> t118 (registrations together), #2202 -> t117 independently.
