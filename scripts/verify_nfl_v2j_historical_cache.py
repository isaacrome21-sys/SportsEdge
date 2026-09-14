"""Compare frozen and cached readouts on first/last historical folds only.

Accepts the same arguments as run_nfl_v2j_first_readout. Does not calculate
calibration, predictive performance, key gates, or a first-readout verdict.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_nfl_v2j_first_readout as runner
from sportsedge.core.walkforward.season import season_walk_forward
from sportsedge.sports.nfl.m2_v2j_candidate import fit_nfl_m2_v2j_candidate
from sportsedge.sports.nfl.m2_v2j_validation import _market_readout
from sportsedge.sports.nfl.m2_v2j_runtime_cache import market_readout_exact_cached
from sportsedge.sports.nfl.source_manifest import manifest_sha256
import numpy as np

class VerificationComplete(Exception):
    pass

def verify_code():
    expected = {
        'm2_v2j_candidate.py': '4e09b22bef3b197a493ad1dcde7e98a78506f896',
        'm2_v2j_validation.py': '3a122a2bf01964a62b9552343bc509caec0edb05',
        'm2_v2j_runtime_cache.py': '6c41d25e1b32999d26b0e63858c4fc5d0c4565ae',
    }
    for name, digest in expected.items():
        raw = (ROOT/'sportsedge/sports/nfl'/name).read_bytes()
        actual = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if actual != digest:
            raise ValueError('CACHE_CHECK_CODE_IDENTITY_MISMATCH:'+name)
    return expected

def verify_sources():
    def argument(name):
        return Path(sys.argv[sys.argv.index(name) + 1])
    manifest = json.loads(argument('--source-manifest').read_text())
    base = dict(manifest)
    expected = base.pop('manifest_sha256')
    base.pop('participation_attribution', None)
    if manifest_sha256(base) != expected:
        raise ValueError('CACHE_CHECK_SOURCE_MANIFEST_HASH_MISMATCH')
    for row in manifest['sources']:
        name = row['name']
        if name == 'schedule':
            path = argument('--schedule-file')
        elif name == 'stadiums':
            path = argument('--stadium-file')
        elif name == 'starter_overrides':
            path = argument('--starter-override-file') if '--starter-override-file' in sys.argv else ROOT/'config/nfl_historical_starter_overrides.json'
        else:
            prefix = name.split('_')[0]
            directory = argument({'pbp': '--pbp-dir', 'participation': '--participation-dir', 'depth': '--depth-dir'}[prefix])
            path = directory/row['uri'].split('/')[-1]
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != row['sha256']:
            raise ValueError('CACHE_CHECK_SOURCE_BYTES_MISMATCH:'+name)
    return len(manifest['sources'])

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def verify(events, rows, *, source_manifest_sha256, **kwargs):
    print(json.dumps({'stage': 'historical_inputs_built', 'history_rows': len(rows), 'events': len(events)}), flush=True)
    folds = list(season_walk_forward(rows, min_train_seasons=2))
    if len(folds) < 2:
        raise ValueError('HISTORICAL_EARLY_LATE_FOLDS_REQUIRED')
    results = []
    for fold in (folds[0], folds[-1]):
        seasons = {int(r['season']) for r in fold.train_rows}
        ids = {str(r.get('game_id') or '') for r in rows}
        train_events = [r for r in events if int(r['season']) in seasons and str(r.get('game_id') or '') in ids]
        model = fit_nfl_m2_v2j_candidate(train_events, fold.train_rows)
        row = dict(fold.test_rows[0])
        identity = {'game_id': row['game_id'], 'season': row['season'], 'training_rows': len(fold.train_rows), 'environment_points': len(model.shared_environment), 'regime_rows': len(model.base_drive_model.possession_regime)}
        print(json.dumps(dict(identity, stage='comparing')), flush=True)
        start = time.perf_counter()
        reference = canonical(_market_readout(model, row))
        reference_seconds = time.perf_counter() - start
        start = time.perf_counter()
        cached = canonical(market_readout_exact_cached(model, row))
        cached_seconds = time.perf_counter() - start
        result = dict(identity, byte_equal=reference == cached, reference_sha256=hashlib.sha256(reference).hexdigest(), cached_sha256=hashlib.sha256(cached).hexdigest(), reference_seconds=reference_seconds, cached_seconds=cached_seconds)
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        if reference != cached:
            break
    output = Path(sys.argv[sys.argv.index('--out') + 1])
    payload = {'status': 'PASS' if len(results)==2 and all(r['byte_equal'] for r in results) else 'FAIL', 'scope': 'EARLY_LATE_REAL_ROW_EQUIVALENCE_ONLY', 'source_manifest_sha256': source_manifest_sha256, 'python': platform.python_version(), 'numpy': np.__version__, 'cases': results, 'full_readout_performed': False, 'promotion_authority': False, 'source_bytes_reverified': False, 'code_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), ROOT/'sportsedge/sports/nfl/m2_v2j_validation.py', ROOT/'sportsedge/sports/nfl/m2_v2j_runtime_cache.py', ROOT/'sportsedge/sports/nfl/m2_v2j_candidate.py']}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True)+'\n')
    if payload['status'] != 'PASS':
        raise ValueError('HISTORICAL_CACHE_BYTE_EQUIVALENCE_FAILED')
    raise VerificationComplete()

if __name__ == '__main__':
    verify_code()
    print(json.dumps({'verified_source_count': verify_sources()}), flush=True)
    with patch.object(runner, 'build_nfl_m2_v2j_candidate_evidence', side_effect=verify):
        try:
            runner.main()
        except VerificationComplete:
            pass
