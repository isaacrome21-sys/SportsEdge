"""The authenticated V2 freeze recognizes exactly two owner states.

These synthetic future-pinning tests are contract checks, not a freeze act.
No counted row is authorized by them.
"""

from dataclasses import replace
from hashlib import sha256

import pytest

from sportsedge.forward_validation import ForwardValidationRefusal
from sportsedge.forward_validation import nba_props as nb


CURRENT_STATUS = "**Status: FINAL-CANDIDATE — NOT FROZEN.**"


def _synthetic_repin(tmp_path, monkeypatch, status: str):
    source = nb._REPO_ROOT / nb.PREREG_PATH_V2
    original = source.read_text(encoding="utf-8")
    assert original.count(CURRENT_STATUS) == 1
    revised = original.replace(CURRENT_STATUS, f"**Status: {status}**", 1)
    target = tmp_path / nb.PREREG_PATH_V2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(revised, encoding="utf-8")
    monkeypatch.setattr(nb, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(nb, "PREREG_SHA256_V2", sha256(revised.encode()).hexdigest())
    return target


@pytest.mark.parametrize("status", [
    "UNFROZEN.",
    "NOT REALLY FROZEN.",
    "SOMETHING FROZEN UNAUTH.",
    "FROZEN -- UNKNOWN.",
    "NOT FROZEN.",
    "FINAL-CANDIDATE — NOT FROZEN-ish.",
    "FROZEN?",
    "PENDING.",
])
def test_unknown_re_pinned_document_states_fail_closed(tmp_path, monkeypatch, status):
    _synthetic_repin(tmp_path, monkeypatch, status)
    with pytest.raises(ForwardValidationRefusal) as refusal:
        nb._v2_document_freeze_state()
    assert refusal.value.reason == "CONFIG_INVALID"


def test_unique_exact_held_and_frozen_headers_are_recognized(tmp_path, monkeypatch):
    assert nb._v2_document_freeze_state() == "NOT_FROZEN"
    _synthetic_repin(tmp_path, monkeypatch, "FROZEN.")
    # This proves future exact-state parsing only, NOT a real freeze.
    assert nb._v2_document_freeze_state() == "FROZEN"


def test_second_status_header_is_ambiguous_even_with_matching_pin(tmp_path, monkeypatch):
    target = _synthetic_repin(tmp_path, monkeypatch, "FROZEN.")
    content = target.read_text(encoding="utf-8")
    content = "**Status: UNFROZEN.**\n" + content
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(nb, "PREREG_SHA256_V2", sha256(content.encode()).hexdigest())
    with pytest.raises(ForwardValidationRefusal) as refusal:
        nb._v2_document_freeze_state()
    assert refusal.value.reason == "CONFIG_INVALID"


@pytest.mark.parametrize("status", [
    "UNFROZEN", "NOT REALLY FROZEN", "SOMETHING FROZEN UNAUTH",
    "FROZEN -- UNKNOWN", "NOT FROZEN", "", None,
])
def test_on_disk_config_unknown_status_is_not_frozen(monkeypatch, status):
    authenticated = nb.load_nba_config("player_points", "V2")
    assert nb._v2_config_freeze_state(status) == "INVALID"
    monkeypatch.setattr(nb, "load_config",
                        lambda _: replace(authenticated, status=status))
    with pytest.raises(ForwardValidationRefusal) as refusal:
        nb.load_nba_config("player_points", "V2")
    assert refusal.value.reason == "CONFIG_INVALID"


def test_config_contract_recognizes_only_exact_future_frozen_token():
    assert nb._v2_config_freeze_state(nb.V2_HELD_CONFIG_STATUS) == "NOT_FROZEN"
    assert nb._v2_config_freeze_state(nb.V2_FROZEN_CONFIG_STATUS) == "FROZEN"
    assert nb.verify_prereg_document("V1")["sha256"] == nb.PREREG_SHA256
