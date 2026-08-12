"""Manifest-bound loading for SportsEdge Statcast V5 artifacts.

The runtime trusts neither filenames nor metadata alone.  Every serialized object
must match an exact SHA-256 from the build manifest, the two predictive artifacts
must embed the exact contact-transformer SHA, and their actual model feature
contracts must pass SPORTSEDGE_STATCAST_V1.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import joblib

from .statcast_contract import require_statcast_artifact
from .statcast_v5_data import V5State

GAME_VERSION="GAME_SCORE_V5_STATCAST"
NRFI_VERSION="NRFI_V5_STATCAST"
TRANSFORMER_NAME="sportsedge_contact_transformer_v1.joblib"
GAME_NAME="sportsedge_game_score_v5_statcast.joblib"
NRFI_NAME="sportsedge_nrfi_v5_statcast.joblib"
STATE_NAME="sportsedge_statcast_state_end_2025.joblib"

class StatcastV5ArtifactError(ValueError):
    pass


def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def _manifest_rows(manifest_path:Path)->dict[str,Mapping[str,Any]]:
    try: doc=json.loads(manifest_path.read_text())
    except Exception as exc: raise StatcastV5ArtifactError("STATCAST_V5_MANIFEST_INVALID") from exc
    if doc.get('schema_version')!=1 or not isinstance(doc.get('files'),list):
        raise StatcastV5ArtifactError("STATCAST_V5_MANIFEST_SCHEMA_INVALID")
    out={}
    for row in doc['files']:
        if not isinstance(row,Mapping): raise StatcastV5ArtifactError("STATCAST_V5_MANIFEST_ROW_INVALID")
        name=Path(str(row.get('path') or '')).name
        sha=str(row.get('sha256') or '')
        if not name or len(sha)!=64: raise StatcastV5ArtifactError("STATCAST_V5_MANIFEST_IDENTITY_INVALID")
        if name in out: raise StatcastV5ArtifactError(f"STATCAST_V5_MANIFEST_DUPLICATE:{name}")
        out[name]=row
    return out


def _verified_file(root:Path,rows:Mapping[str,Mapping[str,Any]],name:str)->Path:
    row=rows.get(name)
    if row is None: raise StatcastV5ArtifactError(f"STATCAST_V5_MANIFEST_FILE_MISSING:{name}")
    p=root/name
    if not p.is_file(): raise StatcastV5ArtifactError(f"STATCAST_V5_FILE_MISSING:{name}")
    got=_sha(p); expected=str(row['sha256'])
    if got!=expected: raise StatcastV5ArtifactError(f"STATCAST_V5_SHA_MISMATCH:{name}:{got}")
    size=row.get('bytes')
    if size is not None and int(size)!=p.stat().st_size: raise StatcastV5ArtifactError(f"STATCAST_V5_SIZE_MISMATCH:{name}")
    return p


def load_statcast_v5_bundle(root:str|Path,*,require_base_state:bool=True)->dict[str,Any]:
    root=Path(root); manifest=root/'manifest.json'
    if not manifest.is_file(): raise StatcastV5ArtifactError("STATCAST_V5_MANIFEST_MISSING")
    rows=_manifest_rows(manifest)
    tp=_verified_file(root,rows,TRANSFORMER_NAME); gp=_verified_file(root,rows,GAME_NAME); np=_verified_file(root,rows,NRFI_NAME)
    sp=_verified_file(root,rows,STATE_NAME) if require_base_state else None
    try:
        transformer=joblib.load(tp); game=joblib.load(gp); nrfi=joblib.load(np); state=joblib.load(sp) if sp else None
    except Exception as exc: raise StatcastV5ArtifactError(f"STATCAST_V5_LOAD_FAILED:{type(exc).__name__}") from exc
    if not isinstance(game,Mapping) or not isinstance(nrfi,Mapping): raise StatcastV5ArtifactError("STATCAST_V5_MODEL_NOT_MAPPING")
    if str(game.get('version') or '')!=GAME_VERSION: raise StatcastV5ArtifactError("STATCAST_V5_GAME_VERSION_MISMATCH")
    if str(nrfi.get('version') or '')!=NRFI_VERSION: raise StatcastV5ArtifactError("STATCAST_V5_NRFI_VERSION_MISMATCH")
    transformer_sha=_sha(tp)
    if str(game.get('contact_transformer_sha256') or '')!=transformer_sha: raise StatcastV5ArtifactError("STATCAST_V5_GAME_TRANSFORMER_SHA_MISMATCH")
    if str(nrfi.get('contact_transformer_sha256') or '')!=transformer_sha: raise StatcastV5ArtifactError("STATCAST_V5_NRFI_TRANSFORMER_SHA_MISMATCH")
    require_statcast_artifact(game,kind='game'); require_statcast_artifact(nrfi,kind='nrfi')
    if state is not None and not isinstance(state,V5State): raise StatcastV5ArtifactError("STATCAST_V5_BASE_STATE_TYPE_INVALID")
    return {
        'transformer':transformer,'transformer_sha256':transformer_sha,
        'game':game,'game_sha256':_sha(gp),'nrfi':nrfi,'nrfi_sha256':_sha(np),
        'base_state':state,'base_state_sha256':_sha(sp) if sp else None,
        'manifest_sha256':_sha(manifest),
    }
