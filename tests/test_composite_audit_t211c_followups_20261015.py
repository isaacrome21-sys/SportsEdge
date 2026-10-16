"""RED follow-ups for the t211 re-audit @ 2714013a (#2359, research only)."""
import pytest

from sportsedge import composite_card as cc
from sportsedge import promotion_screen as ps


def test_pricing_provenance_key_allowlist():
    ok = {"evaluation": {"pricing_provenance": {"lane": "INDEPENDENT", "mechanism": None,
                                                "source": "FREE_MODELS_LANE_A_INDEPENDENT",
                                                "engine_lane": "LANE_A_INDEPENDENT",
                                                "play_eligible": False}}}
    assert cc.authority_violation(ok) is None
    bad = {"evaluation": {"pricing_provenance": {"lane": "X", "mystery": None}}}
    assert cc.authority_violation(bad) is not None


def test_play_eligible_true_still_refused_pending_owner_ruling():
    assert cc.authority_violation({"evaluation": {"pricing_provenance": {"play_eligible": True}}})


@pytest.mark.parametrize("obj", [{"foo": True}, {"evaluation": {"schema": {"armed": True}}}])
def test_truthy_boolean_on_unlisted_key_refused(obj):
    assert cc.authority_violation(obj) is not None


@pytest.mark.parametrize("v", ["bet the over", "HAMMER", "smash it", "wager it", "Ｌｏｃｋ", "b e t"])
def test_betting_verbs_and_obfuscation(v):
    assert ps.promotes(v)


@pytest.mark.parametrize("v", ["NOT_A_PLAY_x", "O 8.5", "PRICED_RESEARCH", "no verified context"])
def test_single_letter_join_does_not_overreach(v):
    assert ps.promotes(v) == (v == "NOT_A_PLAY_x")


def test_vocabulary_marked_owner_curatable():
    assert ps.VOCABULARY_STATE == "OWNER_CURATABLE_PENDING_REVIEW"
    assert {"HAMMER", "SMASH", "BET", "WAGER", "LOCK", "PLAY"} <= ps.PROMOTION_TOKENS
    # t211d owner ruling: TAIL/TAKE/FADE dropped (legit codes such as *_TAIL_ERROR).
    assert not {"TAKE", "FADE", "TAIL"} & ps.PROMOTION_TOKENS


@pytest.mark.parametrize("key", ["playEligible", "is_official", "approved", "actionable",
                                 "ok_to_bet", "stake_units", "bet_size", "units_risked", "evPerDollar"])
def test_key_names_screened(key):
    assert cc.authority_violation({key: 1}) is not None
