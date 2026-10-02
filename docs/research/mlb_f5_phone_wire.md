# MLB F5 phone wire (current main)

Cards are NOT Truth Gate / NOT OFFICIAL. Research map only. Does not promote starter v2 or edit the F5 engine.

Unpriceable rows stay `NO_MODEL`. Missing history, features, or engine session stay `BLOCKED` / `NO_MODEL`. Do not invent p.

## Path already on main

| Layer | Symbol |
|---|---|
| Phone parse | `sportsedge.mlb_lines_intake.parse_lines` → `FIRST_FIVE_{MONEYLINE,RUN_LINE,TOTAL,TEAM_TOTAL}` |
| Market map | `engine_registry.resolve_manual_market_type` → `F5_MONEYLINE` / `F5_RUN_LINE` / `F5_TOTALS` / `F5_TEAM_TOTALS` |
| Session | `build_shared_f5_engine_session`; all four F5 markets share that registry entry |
| Card input | `generic_card_pipeline._model_input` requires an F5 `features` mapping |
| Phone tier | `mlb_scored_card` includes `F5_MONEYLINE` and `F5_RUN_LINE` in team-outcome markets |

## Still not the finish line

`docs/research/finish_line.md` still marks F5 fail-closed. This PR does not score a window and does not move CONTEXT → MODEL.

Open stale map: #1268 (`grok/mlb/f5-card`, base `64be4ba`). Not merged: no owner approval. Do not force-push that branch.
