"""Source-label regressions for the free SmartStake MLB prop intake.

Source: https://huggingface.co/datasets/SmartStake/mlb-player-props
The published viewer uses market='player bases' for total bases.
These tests make no network calls and do not confer model validation.
"""

import pytest

from scripts.download_mlb_props import keep


@pytest.mark.parametrize(
    "source_label",
    [
        "player bases",           # Published dataset viewer: total bases
        "player total bases",     # Published dataset schema example
        "total bases",            # Conventional total-base label
        "total_bases",            # Normalized total-base label
        "player hits",
        "player strikeouts",
    ],
)
def test_target_market_labels_are_preserved(source_label):
    assert keep({"market": source_label})


@pytest.mark.parametrize(
    "source_label", ["player home runs", "player rbis", "player batting walks", ""]
)
def test_non_target_markets_are_not_silently_bundled(source_label):
    assert not keep({"market": source_label})


def test_legacy_alternate_market_fields_still_work():
    assert keep({"market_name": "total bases"})
    assert keep({"prop": "strikeouts"})


def test_missing_market_fields_fail_closed():
    assert not keep({"book": "draftkings", "odds": 1.9})
