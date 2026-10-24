"""t271: CFB Form 2 slate capture orchestrator (offline, no network)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.prepricing import cfb_form2_slate_capture as sc

INDEX = (
    "<div class='nfl-dc-mm-team-name'>Army </div></div><div class='ncaa-dc-mm-team-links'>"
    "<a href='depth-chart.aspx?s=army&id=90038'>Depth Chart</a>"
    "<div class='nfl-dc-mm-team-name'>Central Florida </div></div><div class='ncaa-dc-mm-team-links'>"
    "<a href='depth-chart.aspx?s=central-florida&id=90200'>Depth Chart</a>"
    "<div class='nfl-dc-mm-team-name'>San Jose State </div></div><div class='ncaa-dc-mm-team-links'>"
    "<a href='depth-chart.aspx?s=san-jose-state&id=91000'>Depth Chart</a>"
    "<div class='nfl-dc-mm-team-name'>Miami </div></div><div class='ncaa-dc-mm-team-links'>"
    "<a href='depth-chart.aspx?s=miami&id=90700'>Depth Chart</a>"
    "<div class='nfl-dc-mm-team-name'>Miami (Ohio) </div></div><div class='ncaa-dc-mm-team-links'>"
    "<a href='depth-chart.aspx?s=miami-ohio&id=90701'>Depth Chart</a>"
)


def test_parse_index():
    idx = sc.parse_ourlads_index(INDEX)
    assert ("Army", "army", "90038") in idx and len(idx) == 5


def test_resolve_exact_location_and_accents():
    idx = sc.parse_ourlads_index(INDEX)
    url = sc.resolve_ourlads_url({"id": "349", "location": "Army"}, idx)
    assert url == "https://www.ourlads.com/ncaa-football-depth-charts/depth-chart.aspx?s=army&id=90038"
    assert "san-jose-state" in sc.resolve_ourlads_url(
        {"id": "23", "location": "San José State"}, idx)


def test_resolve_alias_by_espn_id_only():
    idx = sc.parse_ourlads_index(INDEX)
    assert "central-florida" in sc.resolve_ourlads_url({"id": "2116", "location": "UCF"}, idx)
    assert "miami-ohio" in sc.resolve_ourlads_url({"id": "193", "location": "Miami (OH)"}, idx)
    # Miami (FL) resolves to plain Miami, never Miami (Ohio)
    assert sc.resolve_ourlads_url({"id": "2390", "location": "Miami"}, idx).endswith("s=miami&id=90700")


def test_resolve_unknown_refuses():
    idx = sc.parse_ourlads_index(INDEX)
    with pytest.raises(ValueError, match="OURLADS_TEAM_UNRESOLVED"):
        sc.resolve_ourlads_url({"id": "999", "location": "Nowhere"}, idx)


def test_resolve_ambiguous_refuses():
    idx = sc.parse_ourlads_index(INDEX) + [("Army", "army-2", "1")]
    with pytest.raises(ValueError, match="OURLADS_TEAM_AMBIGUOUS"):
        sc.resolve_ourlads_url({"id": "349", "location": "Army"}, idx)


def _sched(*games):
    return {"events": [{"date": d, "competitions": [{"status": {"type": {"completed": c}}}]}
                       for d, c in games]}


def test_previous_completed_kickoff():
    s = _sched(("2026-10-10T19:30Z", True), ("2026-10-17T16:00Z", True),
               ("2026-10-24T16:00Z", False))
    assert sc.previous_completed_kickoff(s, "2026-10-24T16:00:00Z") == "2026-10-17T16:00:00Z"


def test_previous_ignores_incomplete_and_refuses_none():
    s = _sched(("2026-10-17T16:00Z", False))
    with pytest.raises(ValueError, match="PREVIOUS_GAME_UNKNOWN"):
        sc.previous_completed_kickoff(s, "2026-10-24T16:00:00Z")


def _event(eid="1", kick="2026-10-24T16:00Z"):
    return {"id": eid, "date": kick, "competitions": [{"status": {"type": {"state": "pre"}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "2116", "location": "UCF", "displayName": "UCF Knights"}},
                {"homeAway": "away", "team": {"id": "349", "location": "Army", "displayName": "Army Black Knights"}}]}]}


def test_capture_slate_refusals_never_raise(tmp_path):
    def boom(**kw):
        raise ValueError("QB_DEPTH_EVIDENCE_MISSING:NO_QB_ORDER_CAPTURED")
    rep = sc.capture_slate([_event()], str(tmp_path), ourlads_index_html=INDEX,
                           fetch_json=lambda u: _sched(("2026-10-17T16:00Z", True)),
                           capture=boom,
                           now=datetime(2026, 10, 24, 3, tzinfo=timezone.utc))
    assert rep["manifest_sha256"] is None
    assert len(rep["teams"]) == 2
    assert all(t["status"] == "REFUSED" and "QB_DEPTH_EVIDENCE_MISSING" in t["reason"]
               for t in rep["teams"])
    assert rep["status_label"] == "SCREEN" and rep["play_allowed"] is False


def test_capture_slate_skips_started_games(tmp_path):
    rep = sc.capture_slate([_event(kick="2026-10-24T01:00Z")], str(tmp_path),
                           ourlads_index_html=INDEX, fetch_json=lambda u: {},
                           capture=lambda **k: 1/0,
                           now=datetime(2026, 10, 24, 3, tzinfo=timezone.utc))
    assert all(t["reason"] == "KICKOFF_PASSED_NO_BACKFILL" for t in rep["teams"])


def test_capture_slate_preserves_and_seals(tmp_path, monkeypatch):
    calls = []

    def fake_capture(**kw):
        calls.append(kw)
        return {"team": {"espn_id": kw["team_id"]}, "fake": True}

    def fake_preserve(root, *, bundle_bytes, team_id, **kw):
        return {"candidate_manifest_sha256": ("a" if team_id == "2116" else "b") * 64,
                "bundle_sha256": "c" * 64}

    def fake_seal(root, *, manifest_sha256s):
        assert sorted(manifest_sha256s) == ["a" * 64, "b" * 64]
        return {"candidate_manifest_sha256": "d" * 64, "receipt_count": 2}

    monkeypatch.setattr(sc._archive, "preserve_form2_bundle", fake_preserve)
    monkeypatch.setattr(sc._archive, "seal_form2_archive_manifest", fake_seal)
    rep = sc.capture_slate([_event()], str(tmp_path), ourlads_index_html=INDEX,
                           fetch_json=lambda u: _sched(("2026-10-17T16:00Z", True)),
                           capture=fake_capture,
                           now=datetime(2026, 10, 24, 3, tzinfo=timezone.utc))
    assert rep["manifest_sha256"] == "d" * 64
    assert {c["opponent_id"] for c in calls} == {"2116", "349"}
    assert all(c["previous_game_kickoff_utc"] == "2026-10-17T16:00:00Z" for c in calls)
    assert all(c["kickoff_utc"] == "2026-10-24T16:00:00Z" for c in calls)
    assert all(t["status"] == "PRESERVED" for t in rep["teams"])
