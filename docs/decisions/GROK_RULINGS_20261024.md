# Grok rulings — 2026-10-24

## 2026-10-24a — label renderers require a pick-passing engine status
Scope: `scripts/render_sportsedge_png.py`, `scripts/render_auto_dk_phone_summary.py`.

A row may be displayed as BET / LEAN / ACTIONABLE (rendered BEST/LEAN) **only if** its underlying engine status (`engine_status`) passes `sportsedge.phone_display.is_pick_status`. If the engine status is missing, unknown or non-pick (any `WATCH_*`, incl. `WATCH_CFB_MARKET_ONLY_NO_VALIDATED_WEIGHT`, `WATCH_UNVALIDATED_INJURY_WEATHER_ADJ`, `BELOW_THRESHOLD`, or a producer label such as `BET`), the row is shown as WATCH (not drawn as a pick), never as BET/LEAN/ACTIONABLE.

Rationale: producer labels are not evidence; the single fail-closed allowlist (`is_pick_status`) decides pick eligibility everywhere. Enforced by `tests/test_grok_ruling_20261024a_renderers.py` and the source guard in `tests/test_t278_cfb_review_followups.py`.

Invariants unchanged: research-only, SCREEN/NOT_VALIDATED, `play_allowed=false`, CFB research-only with 0 PLAYs.

## 2026-10-24b — resolving the 13 renderer-test conflicts
Freeze check (2026-10-24): `tests/test_auto_dk_phone_summary.py`, `tests/test_sportsedge_png.py` and `tests/test_render_sportsedge_png_unverified_scores.py` appear in no freeze manifest (`config/*freeze*.json`, `config/freeze_reconciliation_registry_v1.json` test prefixes, `config/active_evidence_windows_v1.json`), no CODEOWNERS file exists, and no protected-test list names them; they are only run by `.github/workflows/sportsedge-auto-dk-four-sports.yml`. Not frozen.

Resolution:
- Producers write the engine's real status as `engine_status`, verbatim, never upgraded: `sportsedge/generic_card_pipeline.py` copies `bet_status`; `scripts/run_nfl_lines_card.py` market-anchored residual leans carry `RESEARCH_ONLY_MARKET_ANCHORED_RESIDUAL`. Neither passes `is_pick_status`, so those rows render WATCH in production today.
- Test sample rows gained only an `engine_status` field (`RESEARCH_CANDIDATE_NOT_VALIDATED`); no assertion was removed or weakened. New tests assert a BET/LEAN row without `engine_status` renders WATCH.
