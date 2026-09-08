from datetime import datetime, timezone
import json
import pytest
from scripts.archive_raw_game_odds import _load_ledger, _known_consumed
from sportsedge.mlb_settlement_evidence import as_int, outs_from_ip, MLBSettlementEvidenceError

@pytest.mark.parametrize('value', [None, '', 'bad', float('nan'), float('inf'), True, -1, 1.5])
def test_unknown_usage_and_settlement_cannot_be_zero(value):
    assert _known_consumed({'credits_consumed_actual': value}) is None
    with pytest.raises(MLBSettlementEvidenceError):
        as_int(value)
    with pytest.raises(MLBSettlementEvidenceError):
        outs_from_ip(value)

@pytest.mark.parametrize('payload', [None, '{bad', '{}', '{"utc_date":"2026-09-08"}'])
def test_missing_or_malformed_ledger_is_unknown(tmp_path, payload):
    path = tmp_path / 'ledger.json'
    if payload is not None:
        path.write_text(payload)
    ledger = _load_ledger(path, cap=100, now=datetime(2026,9,8,tzinfo=timezone.utc))
    assert _known_consumed(ledger) is None

def test_explicit_zero_is_preserved(tmp_path):
    path = tmp_path / 'ledger.json'
    path.write_text(json.dumps({'utc_date':'2026-09-08','credits_consumed_actual':0}))
    assert _known_consumed(_load_ledger(path, cap=100, now=datetime(2026,9,8,tzinfo=timezone.utc))) == 0
    assert as_int(0) == 0
    assert outs_from_ip('0.0') == 0
