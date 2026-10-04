import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_nfl_v2k_attempt2.py"
CONTRACT = ROOT / "sportsedge" / "sports" / "nfl" / "NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V2.json"
SOURCE_FREEZE = ROOT / "config" / "nfl_promotion_source_freeze_v1.json"


def _module():
    spec = importlib.util.spec_from_file_location("run_nfl_v2k_attempt2", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_attempt2_runner_derives_legacy_pbp_hash_map_from_canonical_freeze():
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    source = json.loads(SOURCE_FREEZE.read_text(encoding="utf-8"))

    assert "pbp_sha256_by_season" not in contract["source_binding"]
    adapted = module._verification_contract(contract)

    seasons = [str(x) for x in contract["source_binding"]["pbp_seasons"]]
    expected = source["seasonal_sources"]["pbp"]["expected_sha256_by_season"]
    assert adapted["source_binding"]["pbp_sha256_by_season"] == {
        season: expected[season] for season in seasons
    }
    assert adapted["source_binding"]["source_manifest_sha256"] == contract["source_binding"]["source_manifest_sha256"]
    assert "pbp_sha256_by_season" not in contract["source_binding"]


def test_attempt2_source_adapter_keeps_frozen_contract_identity_unchanged():
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    before = json.dumps(contract, sort_keys=True)
    module._verification_contract(contract)
    assert json.dumps(contract, sort_keys=True) == before
