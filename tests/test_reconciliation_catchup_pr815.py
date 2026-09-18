from __future__ import annotations

import json
from pathlib import Path

HISTORICAL_THROUGH_815 = [
    (807, '6256c6125c35b6034697577c470a287290204769'),
    (808, '6e1c566f68b5383656bb10697b37358abd5903c3'),
    (810, '9a095800829a18b09e986cc3fa2cc4c9dfcdae61'),
    (812, 'f8ea5dc02beb7cec606fa26c348fd4d4cf1fe212'),
    (814, '39a7dc3d5b962ca571e64e8d1757b51fb9ec36bd'),
    (817, '23fcdbcc9531181540960d30fdef82c6b61d8244'),
    (813, '2e4410c99630d72664956ead8e3cad0beb4d81d5'),
    (818, 'f23d08bcc48c24368a78447c230a4f626afe1178'),
    (819, 'f397573c06ede6310ae9d1ba932ed67dbedb38ad'),
    (800, '53dd9334441e5da1538ed016cc8123141d27806e'),
    (815, '2b4011058429bd6a689e7a69e0286a7e341629bb'),
]

POST_815 = [
    (822, 'd17a66fe43cb7a6db7955c4e529bc59fd23a2a9f'),
    (823, '852b759b146beba64457a398b3b293eec8a17750'),
    (826, '374ffc70c7bfc2fae968ae4d506b2d325ec1ee5d'),
    (830, 'fc5fc8a7baa4daf2e82699972ee877bce3d869c6'),
]


def _pairs(registry):
    return [(row['pr'], row['merge_sha']) for row in registry['deltas']]


def test_pr815_catchup_sequence_remains_history_stable() -> None:
    registry = json.loads(Path('config/freeze_reconciliation_registry_v1.json').read_text())
    pairs = _pairs(registry)
    start = pairs.index(HISTORICAL_THROUGH_815[0])
    assert pairs[start:start + len(HISTORICAL_THROUGH_815)] == HISTORICAL_THROUGH_815


def test_reconciliation_advances_through_pr830_in_first_parent_order() -> None:
    registry = json.loads(Path('config/freeze_reconciliation_registry_v1.json').read_text())
    assert registry['reconciled_through_sha'] == POST_815[-1][1]
    assert _pairs(registry)[-len(POST_815):] == POST_815


def test_candidate_prereg_bundle_remains_attempt_zero_and_zero_authority() -> None:
    registry = json.loads(Path('config/freeze_reconciliation_registry_v1.json').read_text())
    bundle = next(row for row in registry['bundles'] if row['bundle_id'] == 'CFB_CANDIDATE_PREREG_FREEZE_V1')
    disposition = bundle['disposition']
    assert disposition['state'] in {'REVOKED', 'REFROZEN'}
    if disposition['state'] == 'REFROZEN':
        assert disposition['verification_schema'] == 'CFB_CANDIDATE_PREREG_REFREEZE_V1'
        assert disposition['selection_scope_only'] is True
        assert all(value is False for value in disposition['authority'].values())
    else:
        assert disposition['prior_forward_clock_invalidated'] is True

    prereg = json.loads(Path('config/cfb_model_candidate_prereg_v1.json').read_text())
    governance = prereg['governance']
    assert governance['attempts_consumed'] == 0
    assert governance['evaluation_performed'] is False
    assert governance['model_p_created'] is False
    assert governance['promotion_authority'] is False
    assert governance['official_authority'] is False
