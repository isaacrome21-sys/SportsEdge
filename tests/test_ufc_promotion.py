from sportsedge.ufc_promotion import is_dwcs_event, promotion_for_event


def test_dwcs_event_requires_separate_promotion_even_if_generic_ufc_is_promoted():
    generic = {
        "promoted": True,
        "status": "PROMOTED",
        "blockers": [],
        "dwcs_specific_validation": {
            "promoted": False,
            "status": "UNVERIFIED",
        },
    }
    effective = promotion_for_event(
        generic, "Dana White's Contender Series: Season 10, Week 3"
    )
    assert not effective["promoted"]
    assert effective["status"] == "UNVERIFIED"
    assert "DWCS_VALIDATION_UNPROMOTED" in effective["blockers"]


def test_dwcs_can_promote_only_with_generic_and_dwcs_promotion():
    evidence = {
        "promoted": True,
        "status": "PROMOTED",
        "blockers": [],
        "dwcs_specific_validation": {
            "promoted": True,
            "status": "PROMOTED",
        },
    }
    effective = promotion_for_event(evidence, "DWCS Week 3")
    assert effective["promoted"]
    assert effective["status"] == "PROMOTED"
    assert effective["blockers"] == []


def test_normal_ufc_event_uses_generic_promotion_without_dwcs_gate():
    evidence = {"promoted": True, "status": "PROMOTED", "blockers": []}
    effective = promotion_for_event(evidence, "UFC 330: Makhachev vs. Machado Garry")
    assert effective["promoted"]
    assert effective["status"] == "PROMOTED"
    assert "DWCS_VALIDATION_UNPROMOTED" not in effective["blockers"]


def test_dwcs_detection_is_explicit():
    assert is_dwcs_event("Dana White's Contender Series Week 3")
    assert is_dwcs_event("DWCS Week 3")
    assert not is_dwcs_event("UFC Fight Night")
