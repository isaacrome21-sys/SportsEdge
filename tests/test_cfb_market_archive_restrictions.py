"""Adversarial contract, write-provenance, and architectural regression matrix."""
import ast
import gzip
import json
from pathlib import Path

import pytest

from scripts.materialize_cfb_historical_market_archive import _load_contract
from sportsedge.sports.cfb import history_cache as hc
from sportsedge.sports.cfb.market_archive import iter_market_archive
from sportsedge.sports.cfb.market_archive_contract import (
    ArchiveUse, ArchiveContractError, digest, require_use, load_contract,
)
from tests.test_cfb_history_cache import FakeArchiveOpener, write_archive_contract

ROOT = Path(__file__).resolve().parents[1]
DENIED = [use.value for use in ArchiveUse if use.disposition == 'DENY']
COVERAGE = ArchiveUse.COVERAGE.value


@pytest.fixture
def archive(tmp_path):
    raw = gzip.compress(b'game_id,season,market_type,book\n1,2024,spread,Book\n', mtime=0)
    contract = write_archive_contract(tmp_path, raw)
    opener = FakeArchiveOpener(raw)
    return contract, opener, tmp_path / 'cache'


def cache(archive, **kwargs):
    contract, opener, root = archive
    return hc.cache_market_archive(contract_path=contract, cache_root=root, opener=opener,
                                   allow_benchmark=True, use=kwargs.get('use', COVERAGE))


@pytest.mark.parametrize('use', DENIED, ids=DENIED)
def test_each_forbidden_use_rejected_at_cache_and_public_iterator(archive, use):
    contract, opener, root = archive
    with pytest.raises(ArchiveContractError, match='FORBIDDEN_USE'):
        cache(archive, use=use)
    with pytest.raises(ArchiveContractError, match='FORBIDDEN_USE'):
        iter_market_archive(contract_path=contract, cache_file=root/'absent', use=use)
    assert opener.calls == 0


@pytest.mark.parametrize('use', DENIED, ids=DENIED)
def test_each_forbidden_disposition_cannot_be_changed(archive, use):
    contract, _, _ = archive
    payload = json.loads(contract.read_text())
    payload['restrictions']['uses'][use] = 'ALLOW'
    payload['restriction_sha256'] = digest(payload['restrictions'])
    payload['allowed_uses'].append(use)
    payload['forbidden_uses'].remove(use)
    contract.write_text(json.dumps(payload))
    for validator in (_load_contract, hc._load_market_archive_contract):
        with pytest.raises(ArchiveContractError, match='RESTRICTIONS_INVALID'):
            validator(contract)


@pytest.mark.parametrize('use', DENIED, ids=DENIED)
def test_each_forbidden_use_cannot_overlap_compatibility_lists(archive, use):
    contract, _, _ = archive
    payload = json.loads(contract.read_text())
    payload['allowed_uses'].append(use)
    contract.write_text(json.dumps(payload))
    with pytest.raises(ArchiveContractError, match='USE_PROJECTION_INVALID'):
        _load_contract(contract)


@pytest.mark.parametrize('mutation', ['feature_authority', 'empty_forbidden', 'paired_certification'])
@pytest.mark.parametrize('entry', ['cache', 'iterator'])
def test_each_original_cache_acceptance_now_rejected_individually(archive, mutation, entry):
    contract, opener, root = archive
    payload = json.loads(contract.read_text())
    if mutation == 'feature_authority':
        payload['authority']['feature_authority'] = True
    elif mutation == 'empty_forbidden':
        payload['forbidden_uses'] = []
    else:
        payload['evidence_limitations']['paired_two_sided_quote_certified'] = True
    contract.write_text(json.dumps(payload))
    with pytest.raises(ArchiveContractError):
        if entry == 'cache':
            cache(archive)
        else:
            iter_market_archive(contract_path=contract, cache_file=root/'absent', use=COVERAGE)
    assert opener.calls == 0


@pytest.mark.parametrize('use', ['new_unknown_use', '', 'model_research_and_benchmarking', 'PREDICTIVE_MODEL_FEATURES', None])
def test_unknown_requested_use_is_denied(archive, use):
    with pytest.raises(ArchiveContractError, match='UNKNOWN_USE'):
        cache(archive, use=use)
    contract, _, root = archive
    with pytest.raises(ArchiveContractError, match='UNKNOWN_USE'):
        iter_market_archive(contract_path=contract, cache_file=root/'absent', use=use)


@pytest.mark.parametrize('field', ['allowed_uses', 'forbidden_uses', 'restrictions'])
def test_unknown_policy_use_is_denied(archive, field):
    contract, _, _ = archive
    payload = json.loads(contract.read_text())
    if field == 'restrictions':
        payload[field]['uses']['new_unknown_use'] = 'ALLOW'
        payload['restriction_sha256'] = digest(payload[field])
    else:
        payload[field].append('new_unknown_use')
    contract.write_text(json.dumps(payload))
    with pytest.raises(ArchiveContractError):
        load_contract(contract)


def test_duplicate_json_disposition_is_rejected(archive):
    contract, _, _ = archive
    text = contract.read_text().replace('"uses": {', '"uses": {"predictive_model_features": "ALLOW",')
    contract.write_text(text)
    with pytest.raises(ArchiveContractError, match='DUPLICATE_KEY'):
        load_contract(contract)


def test_legacy_bytes_unreachable_and_never_blessed_in_place(archive):
    contract, opener, root = archive
    legacy = root/'betting_archive'/'cfb_line_odds.csv.gz'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(opener.raw)
    with pytest.raises(hc.CFBHistoryCacheError, match='NAMESPACE_MISMATCH'):
        list(iter_market_archive(contract_path=contract, cache_file=legacy, use=COVERAGE))
    result = cache(archive)
    assert opener.calls == 1
    assert result['cache_file'] != str(legacy)
    assert not result['cache_reused']
    assert legacy.read_bytes() == opener.raw
    assert not (legacy.parent/'manifest.json').exists()


@pytest.mark.parametrize('mutation', ['restriction_hash', 'missing_manifest', 'old_version', 'source_contract_hash'])
def test_cache_read_requires_write_time_matching_manifest(archive, mutation):
    contract, opener, _ = archive
    result = cache(archive)
    path = Path(result['manifest_file'])
    manifest = json.loads(path.read_text())
    if mutation == 'missing_manifest':
        path.unlink()
    else:
        if mutation == 'restriction_hash':
            manifest['restriction_sha256'] = '0'*64
        elif mutation == 'old_version':
            manifest['contract'] = 'CFB_HISTORICAL_MARKET_ARCHIVE_CACHE_V1'
        else:
            manifest['source_contract_sha256'] = '0'*64
        # Even an internally rehashed manifest cannot disagree with the source.
        manifest.pop('manifest_sha256')
        manifest['manifest_sha256'] = digest(manifest)
        path.write_text(json.dumps(manifest))
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(hc.CFBHistoryCacheError):
        list(iter_market_archive(contract_path=contract, cache_file=result['cache_file'], use=COVERAGE))
    with pytest.raises(hc.CFBHistoryCacheError):
        cache(archive)
    assert opener.calls == 1
    assert (path.read_bytes() if path.exists() else None) == before


def test_reuse_does_not_rewrite_write_time_manifest(archive):
    first = cache(archive)
    path = Path(first['manifest_file'])
    original = path.read_bytes()
    second = cache(archive)
    assert second['cache_reused']
    assert path.read_bytes() == original


def architecture_violations(source):
    """All raw-reader access (including aliases/getattr) stays in the facade.

Consumers may import market_archive.iter_market_archive: that function itself
validates, so consumers cannot forget a separate validation call.
"""
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == '_iter_market_archive':
            bad.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == '_iter_market_archive':
            bad.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == '_iter_market_archive':
            bad.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == '_iter_market_archive' or (alias.name == '*' and (node.module or '').endswith('history_cache')):
                    bad.append(node.lineno)
    return bad


@pytest.mark.parametrize('source', [
    'from sportsedge.sports.cfb.history_cache import _iter_market_archive as rows',
    'import sportsedge.sports.cfb.history_cache as hc\nhc._iter_market_archive()',
    'from sportsedge.sports.cfb.history_cache import *',
    'getattr(hc, "_iter_market_archive")()',
])
def test_architecture_guard_rejects_new_raw_consumers(source):
    assert architecture_violations(source)


def test_non_test_consumers_cannot_bypass_public_validated_facade():
    owners = {'sportsedge/sports/cfb/history_cache.py', 'sportsedge/sports/cfb/market_archive.py'}
    violations = []
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        if 'tests' in relative.parts or any(p.startswith('.') for p in relative.parts) or str(relative) in owners:
            continue
        lines = architecture_violations(path.read_text())
        if lines:
            violations.append((str(relative), lines))
    assert not violations
    # Both the public facade and internal reader must remain directly guarded.
    facade = ast.parse((ROOT/'sportsedge/sports/cfb/market_archive.py').read_text())
    fn = next(n for n in facade.body if isinstance(n, ast.FunctionDef) and n.name == 'iter_market_archive')
    assert ast.unparse(fn.body[0]) == 'require_use(load_contract(contract_path), use)'
    assert isinstance(fn.body[1], ast.Return)
    assert fn.body[1].value.func.id == '_iter_market_archive'
    assert _load_contract is load_contract
    assert 'payload = load_contract(path)' in (ROOT/'sportsedge/sports/cfb/history_cache.py').read_text()


def test_architecture_guard_runs_for_any_python_change():
    workflow = (ROOT/'.github/workflows/cfb-historical-market-source-freeze.yml').read_text()
    assert "- '**/*.py'" in workflow
    assert 'tests/test_cfb_market_archive_restrictions.py' in workflow
    assert 'python -m scripts.materialize_cfb_historical_market_archive' in workflow
