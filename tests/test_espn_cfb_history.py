"""Offline tests for the ESPN CFB history acquisition (no network)."""
from sportsedge import espn_cfb_history as ec


def test_completed_events_and_summary_completeness():
    sb = {"events": [{"id": "1", "status": {"type": {"completed": True}}},
                     {"id": "2", "status": {"type": {"completed": False}}}]}
    ev = ec.completed_events([sb])
    assert ev == {"1"}
    assert ec.completeness(ev, {"1"}, [], 134)["status"] == "COMPLETE"
    c = ec.completeness(ev, set(), [], 134)
    assert c["status"] == "INCOMPLETE" and c["events_missing_summary"] == ["1"]
    assert ec.completeness(ev, {"1"}, [{"url": "x"}], 134)["status"] == "INCOMPLETE"
    assert ec.completeness(ev, {"1"}, [], 0)["status"] == "INCOMPLETE"


def test_fbs_ids_from_core_refs_and_passers():
    body = {"items": [{"$ref": "http://x/seasons/2024/teams/333?lang=en"},
                      {"$ref": "http://x/seasons/2024/teams/2?lang=en"}]}
    assert ec.fbs_team_ids(body) == ["2", "333"]
    summ = {"boxscore": {"players": [{"statistics": [
        {"name": "passing", "athletes": [{"athlete": {"id": "77"}}]},
        {"name": "rushing", "athletes": [{"athlete": {"id": "88"}}]}]}]}}
    assert ec.passer_ids([summ]) == [77]


def test_urls_and_labels():
    assert len(ec.scoreboard_urls(2024)) == 17
    assert "groups=80" in ec.scoreboard_url(2024, 2, 1)
    assert ec.summary_url("401").endswith("summary?event=401")
    m = ec.manifest(2024, {}, {}, {"status": "COMPLETE"}, [], {})
    assert m["provenance_label"] == "ACQUIRED_POSTHOC_FROM_PUBLIC_ESPN"
    assert "ISSUE_2344_RECOVERED_ORIGINAL" in m["is_not"]
