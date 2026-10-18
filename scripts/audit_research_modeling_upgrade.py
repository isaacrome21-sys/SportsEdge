#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel):
    return json.loads((ROOT / rel).read_text())


def require(cond, msg):
    if not cond:
        raise SystemExit(msg)


method = load('config/research/model_research_methodology_v1.json')
nfl = load('config/research/nfl_play_level_feature_contract_v1.json')
freeze = load('config/nfl_m2_freeze.json')
props = load('config/football_prop_engine_surface.json')

hard = method['hard_governance']
require(method['status'] == 'RESEARCH_ONLY_ADOPTED', 'methodology must remain research-only')
require(hard['research_only'] is True, 'research_only must be true')
require(hard['promotion_changed'] is False, 'research methodology may not change promotion')
require(hard['truth_gate_changed'] is False, 'research methodology may not change Truth Gate')
require(hard['edge_floor_changed'] is False, 'research methodology may not change edge floors')
require(hard['eligible_changed'] is False, 'research methodology may not change eligibility')
require(hard['model_p_created'] is False, 'research methodology may not create Model_P')
require(hard['capture_backfill_allowed'] is False, 'capture backfill must remain forbidden')
require(hard['market_price_may_substitute_for_model_p'] is False, 'market price may not substitute for Model_P')

require(nfl['status'] == 'RESEARCH_ONLY_ADOPTED', 'NFL play-level contract must remain research-only')
require(nfl['pit_rules']['pregame_only'] is True, 'NFL play-level features must be pregame-only')
require(nfl['pit_rules']['target_game_plays_forbidden'] is True, 'target-game plays must be forbidden')
require(nfl['pit_rules']['rolling_windows_must_shift_one_game'] is True, 'rolling windows must be shifted')
require(nfl['pit_rules']['market_spread_or_total_as_model_feature'] is False, 'market lines cannot enter independent Model_P features')
require(nfl['pit_rules']['closing_line_as_model_feature'] is False, 'closing line cannot enter independent Model_P features')
require(nfl['research_window']['2025_status'] == 'EXPOSED_BY_PRIOR_GENERATIONS_NOT_FRESH_FINAL_HOLDOUT', '2025 must not be relabeled untouched')

# Adoption of research practices must not unlock production while current evidence is blocked.
require(freeze['status'] == 'UNFROZEN', 'research-only upgrade must not freeze NFL M2')
require(freeze.get('artifact_sha256') is None, 'research-only upgrade must not bind a production NFL artifact')
require(props['sports']['NFL']['engine_state'] == 'NO_ENGINE', 'NFL props must remain NO_ENGINE')
require(props['sports']['CFB']['engine_state'] == 'NO_ENGINE', 'CFB props must remain NO_ENGINE')
require(props['governance']['market_prices_can_create_model_p'] is False, 'prop market prices cannot create Model_P')

print(json.dumps({
    'status': 'PASS',
    'scope': 'RESEARCH_ONLY',
    'nfl_m2_status': freeze['status'],
    'nfl_props': props['sports']['NFL']['engine_state'],
    'cfb_props': props['sports']['CFB']['engine_state'],
    'fresh_nfl_final_holdout_available_now': method['sport_specific']['NFL']['fresh_final_holdout_available_now'],
}, sort_keys=True))
