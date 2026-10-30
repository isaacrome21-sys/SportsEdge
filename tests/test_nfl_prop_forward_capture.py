from sportsedge.sports.nfl.prop_forward_capture import apply_snapshot


def _quote(*, event="e1", player="p", market="RECEPTIONS", side="OVER", line=5.5, price=-110):
    return {
        "provider_event_id": event,
        "entity_name_normalized": player,
        "entity_name": "Player One",
        "market": market,
        "book_key": "draftkings_direct",
        "side": side,
        "line": line,
        "american_odds": price,
        "provider": "DRAFTKINGS_WEB_RESEARCH",
    }


def test_decision_only_inside_frozen_window_and_is_non_promoting():
    result = apply_snapshot(
        [_quote()],
        captured_at="2026-09-13T16:30:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
    )
    assert len(result.decisions) == 1
    row = result.decisions[0]
    assert row["phase"] == "DECISION"
    assert row["promotion_authority"] is False
    assert row["model_p_created"] is False
    assert row["reconstructed"] is False
    assert row["backfilled"] is False
    assert result.closes == ()


def test_close_requires_exact_existing_decision_identity():
    q = _quote()
    decision = apply_snapshot(
        [q],
        captured_at="2026-09-13T16:30:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
    ).decisions[0]
    close = apply_snapshot(
        [{**q, "american_odds": -125}],
        captured_at="2026-09-13T17:45:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
        existing_decisions=[decision],
    )
    assert len(close.closes) == 1
    assert close.closes[0]["phase"] == "CLOSE"
    assert close.closes[0]["american_odds"] == -125


def test_changed_threshold_cannot_close_prior_decision():
    q = _quote(line=5.5)
    decision = apply_snapshot(
        [q],
        captured_at="2026-09-13T16:30:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
    ).decisions[0]
    result = apply_snapshot(
        [_quote(line=6.5)],
        captured_at="2026-09-13T17:45:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
        existing_decisions=[decision],
    )
    assert result.closes == ()
    assert result.missed_or_blocked[0]["reason"] == "MISSED_DECISION_WINDOW_NO_BACKFILL"


def test_missed_decision_is_not_backfilled():
    result = apply_snapshot(
        [_quote()],
        captured_at="2026-09-13T17:30:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
    )
    assert result.decisions == ()
    assert result.closes == ()
    assert result.missed_or_blocked[0]["reason"] == "MISSED_DECISION_WINDOW_NO_BACKFILL"


def test_missing_kickoff_blocks_capture():
    result = apply_snapshot([_quote()], captured_at="2026-09-13T16:30:00+00:00", event_starts={})
    assert result.decisions == ()
    assert result.missed_or_blocked[0]["reason"] == "EVENT_START_MISSING"


def test_anytime_td_line_none_identity_is_supported():
    q = _quote(market="ANYTIME_TD", side="YES", line=None, price=135)
    result = apply_snapshot(
        [q],
        captured_at="2026-09-13T16:30:00+00:00",
        event_starts={"e1": "2026-09-13T18:00:00+00:00"},
    )
    assert result.decisions[0]["line"] is None
    assert result.decisions[0]["side"] == "YES"
