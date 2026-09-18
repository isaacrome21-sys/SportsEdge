from __future__ import annotations

import json
from pathlib import Path

EXPECTED = [
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

def test_reconciliation_catchup_is_first_parent_complete_through_pr815() -> None:
    registry = json.loads(Path('config/freeze_reconciliation_registry_v1.json').read_text())
    assert registry['reconciled_through_sha'] == EXPECTED[-1][1]
    tail = registry['deltas'][-len(EXPECTED):]
    assert [(row['pr'], row['merge_sha']) for row in tail] == EXPECTED

def test_candidate_prereg_bundle_is_machine_verified_refrozen_at_attempt_zero() -> None:
    registry = json.loads(Path('config/freeze_reconciliation_registry_v1.json').read_text())
    bundle = next(row for row in registry['bundles'] if row['bundle_id'] == 'CFB_CANDIDATE_PREREG_FREEZE_V1')
    disposition = bundle['disposition']
    assert disposition['state'] == 'REFROZEN'
    assert disposition['verification_schema'] == 'CFB_CANDIDATE_PREREG_REFREEZE_V1'
    assert disposition['row_admissibility_semantics'] == 'PREREGISTRATION_ONLY_NO_EVALUATION_ROWS_V1'
    assert disposition['selection_scope_only'] is True
    assert not any(disposition['authority'].values())
    prereg = json.loads(Path('config/cfb_model_candidate_prereg_v1.json').read_text())
    governance = prereg['governance']
    assert governance['attempts_consumed'] == 0
    assert governance['evaluation_performed'] is False
    assert governance['model_p_created'] is False
    assert governance['promotion_authority'] is False
    assert governance['official_authority'] is False
