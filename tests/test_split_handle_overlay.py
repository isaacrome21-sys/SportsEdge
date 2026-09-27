from sportsedge.split_handle_overlay import classify_split_overlay


def test_rlm_tags_against_public_and_cannot_write_model_p() -> None:
    out = classify_split_overlay(
        {
            "ticket_pct": 74,
            "money_pct": 48,
            "line_move_points": -1.0,
            "public_side": "home",
            "line_moved_toward": "away",
        }
    )
    assert "RLM_TICKETS_VS_LINE" in out["tags"]
    assert "MONEY_TICKET_DIVERGENCE" in out["tags"]
    assert out["action"] == "CONTEXT_LEAN_AGAINST_PUBLIC"
    assert out["model_p_authority"] is False
    assert out["official_authority"] is False
    assert out["may_rewrite_model_p"] is False


def test_ordinary_60_40_is_not_a_signal() -> None:
    out = classify_split_overlay({"ticket_pct": 61, "money_pct": 55, "line_move_points": 0.0})
    assert out["action"] == "NO_OVERLAY"
    assert out["tags"] == []
