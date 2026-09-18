from sportsedge.ev_suspension_v3 import provider_outage


def a(event, slot, at="2026-09-17T01:00:00Z"):
    return {"event_id": event, "credential_slot": slot, "error_code": "ODDS_API_UNAUTHORIZED", "attempted_at": at}


def test_one_event_is_not_provider_wide_outage():
    assert not provider_outage([a("a", "1"), a("a", "2")], configured_slots=2)


def test_missing_configured_slot_is_not_provider_wide_outage():
    assert not provider_outage([a("a", "1"), a("b", "1")], configured_slots=2)


def test_outside_bounded_window_is_not_outage():
    rows = [a("a", "1", "2026-09-17T01:00:00Z"), a("a", "2", "2026-09-17T01:00:00Z"),
            a("b", "1", "2026-09-17T02:00:00Z"), a("b", "2", "2026-09-17T02:00:00Z")]
    assert not provider_outage(rows, configured_slots=2, bounded_window_minutes=30)
