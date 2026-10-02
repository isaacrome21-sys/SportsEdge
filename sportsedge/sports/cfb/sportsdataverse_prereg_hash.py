"""Hash binding for the SportsDataverse CFB prereg before evaluation attempt 1."""
from __future__ import annotations
import hashlib,json
from typing import Mapping

CODE_PATHS=(
 ".github/workflows/cfb-sdv-materialize-training.yml",
 "scripts/cfb_sportsdataverse_prereg_hash.py",
 "scripts/acquire_cfb_sportsdataverse_training_inputs.py",
 "scripts/materialize_cfb_sportsdataverse_training.py",
 "scripts/run_cfb_sportsdataverse_bakeoff.py",
 "sportsedge/sports/cfb/sportsdataverse_acquisition.py",
 "sportsedge/sports/cfb/sportsdataverse_receipts.py",
 "sportsedge/sports/cfb/sportsdataverse_converted.py",
 "sportsedge/sports/cfb/sportsdataverse_csv.py",
 "sportsedge/sports/cfb/sportsdataverse_candidate_families.py",
 "sportsedge/sports/cfb/sportsdataverse_candidate_model.py",
 "sportsedge/sports/cfb/sportsdataverse_bakeoff.py",
 "sportsedge/sports/cfb/sportsdataverse_weather.py",
 "sportsedge/sports/cfb/sportsdataverse_weather_receipts.py",
 "sportsedge/sports/cfb/sportsdataverse_weather_transport.py",
 "sportsedge/sports/cfb/sportsdataverse_history.py",
 "sportsedge/sports/cfb/sportsdataverse_manifest.py",
 "sportsedge/sports/cfb/sportsdataverse_materializer.py",
 "sportsedge/sports/cfb/sportsdataverse_pipeline.py",
 "sportsedge/sports/cfb/sportsdataverse_training_rows.py",
)
CONFIG_PATHS=(
 "config/cfb_sportsdataverse_source_contract_v1.json",
 "config/cfb_sportsdataverse_historical_weather_contract_v1.json",
)
class SDVPreregHashError(ValueError): pass

def sha256_text(value:str)->str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def bundle_sha256(files:Mapping[str,str], paths:tuple[str,...])->str:
    missing=[p for p in paths if p not in files]
    if missing: raise SDVPreregHashError("CFB_SDV_PREREG_HASH_INPUT_MISSING:"+",".join(missing))
    payload=[{"path":p,"sha256":sha256_text(files[p])} for p in sorted(paths)]
    return sha256_text(json.dumps(payload,sort_keys=True,separators=(",",":")))

def code_manifest_sha256(files:Mapping[str,str])->str:
    return bundle_sha256(files,CODE_PATHS)

def config_bundle_sha256(files:Mapping[str,str])->str:
    # Hash only external immutable config; the prereg stores this digest and cannot hash itself.
    return bundle_sha256(files,CONFIG_PATHS)

def verify(expected_code:str, expected_config:str, files:Mapping[str,str])->None:
    if code_manifest_sha256(files)!=expected_code:
        raise SDVPreregHashError("CFB_SDV_CODE_MANIFEST_HASH_MISMATCH")
    if config_bundle_sha256(files)!=expected_config:
        raise SDVPreregHashError("CFB_SDV_CONFIG_BUNDLE_HASH_MISMATCH")
