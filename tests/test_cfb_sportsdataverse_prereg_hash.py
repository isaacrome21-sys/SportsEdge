import pytest
from sportsedge.sports.cfb.sportsdataverse_prereg_hash import (
 CODE_PATHS,CONFIG_PATHS,SDVPreregHashError,code_manifest_sha256,config_bundle_sha256,verify,
)

def files():
    return {p:"content:"+p for p in CODE_PATHS+CONFIG_PATHS}

def test_hashes_are_deterministic_and_path_bound():
    f=files()
    assert code_manifest_sha256(f)==code_manifest_sha256(dict(reversed(list(f.items()))))
    assert config_bundle_sha256(f)==config_bundle_sha256(f)

def test_missing_or_changed_input_fails_closed():
    f=files(); code=code_manifest_sha256(f); cfg=config_bundle_sha256(f)
    verify(code,cfg,f)
    f[CODE_PATHS[0]]+="tamper"
    with pytest.raises(SDVPreregHashError,match="CODE_MANIFEST_HASH_MISMATCH"):
        verify(code,cfg,f)
    f=files(); del f[CONFIG_PATHS[0]]
    with pytest.raises(SDVPreregHashError,match="HASH_INPUT_MISSING"):
        config_bundle_sha256(f)

def test_evaluated_code_is_inside_code_manifest():
    assert "sportsedge/sports/cfb/sportsdataverse_candidate_model.py" in CODE_PATHS
    assert "sportsedge/sports/cfb/sportsdataverse_bakeoff.py" in CODE_PATHS
