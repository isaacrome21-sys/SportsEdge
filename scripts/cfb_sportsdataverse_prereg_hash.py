#!/usr/bin/env python3
"""Compute, verify, or emit the exact SportsDataverse CFB prereg hash bundle."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from sportsedge.sports.cfb.sportsdataverse_prereg_hash import CODE_PATHS,CONFIG_PATHS,code_manifest_sha256,config_bundle_sha256,verify

def _read(root:Path):
 paths=CODE_PATHS+CONFIG_PATHS
 return {p:(root/p).read_text(encoding="utf-8") for p in paths}

def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--root",default=".")
 ap.add_argument("--verify-code")
 ap.add_argument("--verify-config")
 ap.add_argument("--prereg")
 ap.add_argument("--emit-frozen-prereg")
 a=ap.parse_args()
 files=_read(Path(a.root))
 code=code_manifest_sha256(files); config=config_bundle_sha256(files)
 if a.emit_frozen_prereg:
  if not a.prereg: raise SystemExit("CFB_SDV_PREREG_PATH_REQUIRED")
  prereg_path=Path(a.prereg); prereg=json.loads(prereg_path.read_text(encoding="utf-8"))
  gov=prereg.get("governance") or {}
  if gov.get("attempts_consumed")!=0 or gov.get("evaluation_performed") is not False:
   raise SystemExit("CFB_SDV_PREREG_ALREADY_EVALUATED")
  prereg["hash_binding"]={"code_manifest_sha256":code,"config_bundle_sha256":config}
  print(json.dumps(prereg,indent=2,sort_keys=True))
  return 0
 if a.verify_code or a.verify_config:
  if not (a.verify_code and a.verify_config): raise SystemExit("CFB_SDV_BOTH_HASHES_REQUIRED_FOR_VERIFY")
  verify(a.verify_code,a.verify_config,files)
 print(json.dumps({"schema":"CFB_SPORTSDATAVERSE_PREREG_HASH_BUNDLE_V1","code_manifest_sha256":code,"config_bundle_sha256":config,
 "code_paths":list(CODE_PATHS),"config_paths":list(CONFIG_PATHS)},indent=2,sort_keys=True))
 return 0
if __name__=="__main__": raise SystemExit(main())
