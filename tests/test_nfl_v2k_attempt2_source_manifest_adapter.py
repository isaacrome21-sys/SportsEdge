import importlib.util
from pathlib import Path

RUNNER=Path("scripts/run_nfl_v2k_attempt2.py")

def _module():
    spec=importlib.util.spec_from_file_location("run_nfl_v2k_attempt2",RUNNER)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_attempt2_source_manifest_adapter_supplies_only_frozen_pbp_hashes():
    mod=_module()
    contract=mod.v.a1._load_json(mod.v.CONTRACT_PATH)
    adapted=mod._source_verifier_contract(contract)
    binding=adapted["source_binding"]
    assert set(binding["pbp_sha256_by_season"])=={str(y) for y in range(2018,2026)}
    freeze=mod.v.a1._load_json(mod.v.ROOT / binding["source_freeze_path"])
    expected=freeze["seasonal_sources"]["pbp"]["expected_sha256_by_season"]
    assert binding["pbp_sha256_by_season"]=={str(y):expected[str(y)] for y in range(2018,2026)}
    assert "pbp_sha256_by_season" not in contract["source_binding"]

def test_attempt2_source_manifest_adapter_does_not_touch_frozen_model_identity():
    mod=_module()
    contract=mod.v.a1._load_json(mod.v.CONTRACT_PATH)
    before=contract["implementation_identity"].copy()
    mod._source_verifier_contract(contract)
    assert contract["implementation_identity"]==before
    assert contract["simulation"]["root_seed"]==13631901020752177054
