#!/usr/bin/env python3
"""Build the predeclared NRFI/YRFI V6 forward-shadow calibration wrapper."""
from __future__ import annotations

import hashlib, json, math, os
from pathlib import Path
import joblib
import numpy as np

from sportsedge.statcast_contract import NRFI_STATCAST_FEATURES, require_statcast_artifact

BASE_SHA="a12881071bb53a52c6dcfaaacbf6e7c844e329beb7bb2df204124c064d4b21cc"
TRANSFORMER_SHA="bf61487279ac9a506318e9dfa078a866450dd4e363b1d06356e58852954133b2"
OFFSET=0.11867068977686865
BASE=Path(os.getenv("SPORTSEDGE_NRFI_V5_ARTIFACT","phase6_artifacts/sportsedge_nrfi_v5_statcast.joblib"))
PROTOCOL=Path("audit/NRFI_V6_FORWARD_SHADOW_PROTOCOL_2026-08-13.md")
FORM=Path("audit/NRFI_V6_FUNCTIONAL_FORM_LOCK_2026-08-13.md")
OUT=Path(os.getenv("SPORTSEDGE_NRFI_V6_OUT","artifacts/nrfi-v6-shadow"))


def sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()

def logit(p):
    p=np.clip(np.asarray(p,float),1e-6,1-1e-6)
    return np.log(p/(1-p))

def expit(x):
    x=np.asarray(x,float)
    return 1/(1+np.exp(-x))

def calibrate(base_p):
    return np.clip(expit(logit(base_p)+OFFSET),.001,.999)


def main()->int:
    for p in (BASE,PROTOCOL,FORM):
        if not p.is_file(): raise RuntimeError("NRFI_V6_REQUIRED_FILE_MISSING:"+str(p))
    if sha(BASE)!=BASE_SHA: raise RuntimeError("NRFI_V5_BASE_SHA_MISMATCH")
    base=joblib.load(BASE)
    require_statcast_artifact(base,kind="nrfi")
    features=tuple(base.get("features") or ())
    missing=[x for x in NRFI_STATCAST_FEATURES if x not in features]
    if missing: raise RuntimeError("NRFI_V6_INHERITED_STATCAST_CONTRACT_MISSING:"+",".join(missing))
    if str(base.get("contact_transformer_sha256") or "")!=TRANSFORMER_SHA:
        raise RuntimeError("NRFI_V6_BASE_TRANSFORMER_SHA_MISMATCH")

    # Reproduce the locked aggregate development calculation; this is not a
    # holdout score for V6 and never authorizes deployment.
    base_mean=0.4666385824133054; actual=0.49625668449197863
    shifted=float(calibrate([base_mean])[0])
    # For a slope-1 logit offset, evaluating the mean through the nonlinear
    # transform is only a functional-form sanity check, not a claim that the
    # row-level mean equals this value.
    artifact={
        "version":"NRFI_V6_FORWARD_SHADOW",
        "positive_class":"YRFI",
        "base_artifact":base,
        "base_artifact_sha256":BASE_SHA,
        "contact_transformer_sha256":TRANSFORMER_SHA,
        "features":features,
        "statcast_features":tuple(NRFI_STATCAST_FEATURES),
        "calibration_form":"LOGIT_INTERCEPT_SLOPE_FIXED_1",
        "logit_intercept":OFFSET,
        "probability_bounds":[.001,.999],
        "protocol_sha256":sha(PROTOCOL),
        "functional_form_lock_sha256":sha(FORM),
        "development_cutoff":"2026-08-12",
        "forward_shadow_start":"2026-08-13",
        "deployment_eligible":False,
        "deployment_block_reason":"FORWARD_SHADOW_INSUFFICIENT_SAMPLE",
        "model_p_sportsbook_independent":True,
    }
    OUT.mkdir(parents=True,exist_ok=True)
    ap=OUT/"sportsedge_nrfi_v6_shadow.joblib"; joblib.dump(artifact,ap,compress=3)
    report={
        "schema_version":"nrfi_v6_shadow_development_v1",
        "artifact_sha256":sha(ap),"base_artifact_sha256":BASE_SHA,
        "contact_transformer_sha256":TRANSFORMER_SHA,
        "protocol_sha256":sha(PROTOCOL),"functional_form_lock_sha256":sha(FORM),
        "development_cutoff":"2026-08-12","forward_shadow_start":"2026-08-13",
        "v5_2025_rows":1870,"v5_2025_mean_prediction":base_mean,"v5_2025_actual":actual,
        "locked_logit_intercept":OFFSET,"aggregate_transform_sanity_value":shifted,
        "inherited_feature_count":len(features),"required_statcast_features_present":True,
        "deployment_eligible":False,"deployment_block_reason":"FORWARD_SHADOW_INSUFFICIENT_SAMPLE",
        "outcomes_2026_08_13_or_later_used":False,"sportsbook_data_used":False,
    }
    (OUT/"validation.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:report[k] for k in ("artifact_sha256","locked_logit_intercept","inherited_feature_count","deployment_eligible","deployment_block_reason")},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
