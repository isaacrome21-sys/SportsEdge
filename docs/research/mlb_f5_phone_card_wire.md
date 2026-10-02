# MLB F5 phone card (grok/mlb/f5-card)

ONE step. No production engine rewrite. Full-game dispersion freeze untouched.
Starter v2 stays unpromoted (bootstrap CI straddled 0).

## Can the existing F5 engine price phone F5 rows?

Yes. No missing function.

| Layer | Function |
|---|---|
| Phone parse | `sportsedge.mlb_lines_intake.parse_lines` → `FIRST_FIVE_{MONEYLINE,RUN_LINE,TOTAL,TEAM_TOTAL}` |
| Market map | `engine_registry.resolve_manual_market_type` → `F5_*` |
| Features | `MLBGenericHistorySource._team_f5_history` + `MLBAllMarketHistorySource.feature_row` wraps `features` |
| Price | `build_shared_f5_engine_session` / `read_f5_probability` |
| Card | `generic_card_pipeline._model_input` (F5 `features` + `feature_source_hash`/`source_subset_hash`) → `myspari_rows` |

Fail closed: missing history / features / engine → `BLOCKED` / `NO_MODEL`. Do not invent p.
