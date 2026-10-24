"""Lane 5 (CFB automation), work order #2447 comment 6390303271.

* OurLads index slugs may contain a space ("utah state"); Utah State must
  resolve (was OURLADS_TEAM_NOT_FOUND) and the URL must be fetchable.
* Auto DK h2h rows carry the paired opposite price from the SAME captured
  DK market object, so CFB moneylines can reach the Lane B blend.
* The auto pipeline builds Form 2 capture lines straight from the paid DK
  capture (no manual [CFB FORM2] issue), but pricing admission still needs
  the EXTERNAL pin: nothing here derives a pin from the archive/runtime.
"""
from datetime import datetime, timedelta, timezone

import pytest

from scripts import capture_cfb_form2_slate as slate
from sportsedge.auto_dk_canonical_intake import bind_capture
from scripts.run_auto_dk_live_value_card import run_capture_directory

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)

INDEX = (
    "<div class='nfl-dc-mm-team-name'>Utah </div></div>"
    "<a href='depth-chart.aspx?s=utah&id=92292'>Depth Chart</a>"
    "<div class='nfl-dc-mm-team-name'>Utah State </div></div>"
    "<a href='depth-chart.aspx?s=utah state&id=92315'>Depth Chart</a>"
    "<a href='depth-chart.aspx?s=texas-state&id=92821'>Depth Chart</a>")

USU = {"location": "Utah State", "displayName": "Utah State Aggies",
       "abbreviation": "USU", "shortDisplayName": "Utah St"}


def links(monkeypatch):
    monkeypatch.setattr(slate, "get", lambda url: INDEX)
    return slate.ourlads_index()


def test_utah_state_space_slug_resolves_to_encoded_url(monkeypatch):
    url = slate.ourlads_url(links(monkeypatch), "Utah State", USU)
    assert url.endswith("depth-chart.aspx?s=utah%20state&id=92315")
    assert " " not in url


def test_utah_does_not_steal_utah_state_and_vice_versa(monkeypatch):
    found = links(monkeypatch)
    assert slate.ourlads_url(found, "Utah", {"location": "Utah"}).endswith(
        "s=utah&id=92292")


def test_unknown_team_still_fails_closed(monkeypatch):
    with pytest.raises(ValueError, match="OURLADS_TEAM_NOT_FOUND"):
        slate.ourlads_url(links(monkeypatch), "Nowhere Tech",
                          {"location": "Nowhere Tech"})


def snapshot(sport="CFB", away_ml=135, home_ml=-150):
    observed = (NOW - timedelta(seconds=30)).isoformat()
    return {
        "sport": sport, "source": "THE_ODDS_API_V4", "status": "READY",
        "captured_at_utc": NOW.isoformat(),
        "games": [{
            "provider_event_id": "evt-usu", "away": "Utah State Aggies",
            "home": "Boise State Broncos",
            "commence_time": (NOW + timedelta(hours=3)).isoformat(),
            "markets": {
                "h2h": {"book": "draftkings", "observed_at": observed,
                        "line": None, "away": away_ml, "home": home_ml},
                "spreads": {"book": "draftkings", "observed_at": observed,
                            "line": 3.5, "away": -110, "home": -110},
                "totals": {"book": "draftkings", "observed_at": observed,
                           "line": 55.5, "over": -110, "under": -110},
            }}]}


def test_h2h_rows_carry_same_capture_opposite_price():
    rows, refused = bind_capture(snapshot(), now=NOW)
    assert refused == []
    ml = {r["side"]: r for r in rows if r["market"] == "ML"}
    assert ml["AWAY"]["opposite_odds"] == -150
    assert ml["HOME"]["opposite_odds"] == 135
    # The pair is the same DK object: identical capture time and event.
    assert ml["AWAY"]["quote_captured_at"] == ml["HOME"]["quote_captured_at"]
    # Spreads/totals are paired by their partner row, not an asserted field.
    assert all("opposite_odds" not in r for r in rows if r["market"] != "ML")


def test_invalid_ml_pair_still_refused_no_opposite_invented():
    rows, refused = bind_capture(snapshot(home_ml=50), now=NOW)
    assert not [r for r in rows if r["market"] == "ML"]
    assert any(r["market"] == "h2h" for r in refused)


def test_form2_lines_built_from_auto_capture_without_manual_issue():
    out = slate.lines_from_auto_capture(snapshot())
    assert out["sport"] == "CFB"
    assert [(r["away"], r["home"]) for r in out["lines"]] == [
        ("Utah State Aggies", "Boise State Broncos")]
    assert out["lines"][0]["commence_time"] == (NOW + timedelta(hours=3)).isoformat()


def test_form2_lines_refuse_non_cfb_or_unready_capture():
    with pytest.raises(ValueError):
        slate.lines_from_auto_capture(snapshot(sport="NFL"))
    bad = snapshot()
    bad["status"] = "QUOTA_RESERVE_BLOCKED"
    with pytest.raises(ValueError):
        slate.lines_from_auto_capture(bad)


def test_auto_runner_never_derives_a_pin_from_the_archive(tmp_path):
    import json
    (tmp_path / "cfb_odds.json").write_text(json.dumps(snapshot()))
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / ("a" * 64 + ".json")).write_text("{}")
    seen = {}

    def runner(payload, **kw):
        seen.update(kw)
        return {"evaluated_rows": [{} for _ in payload["lines"]]}

    run_capture_directory(tmp_path, now=NOW, runner=runner,
                          render=lambda card, now: "", form2_bundles_dir=archive)
    assert seen["form2_bundles_dir"] == archive
    assert seen["form2_manifest_sha256"] is None  # NO PIN, NO ADMISSION


def test_auto_runner_passes_external_pin_verbatim(tmp_path):
    import json
    (tmp_path / "cfb_odds.json").write_text(json.dumps(snapshot()))
    seen = {}

    def runner(payload, **kw):
        seen.update(kw)
        return {"evaluated_rows": [{} for _ in payload["lines"]]}

    pin = "b" * 64
    run_capture_directory(tmp_path, now=NOW, runner=runner,
                          render=lambda card, now: "",
                          form2_bundles_dir=tmp_path, form2_manifest_sha256=pin)
    assert seen["form2_manifest_sha256"] == pin


def test_auto_runner_without_form2_keeps_legacy_call(tmp_path):
    import json
    (tmp_path / "cfb_odds.json").write_text(json.dumps(snapshot()))
    seen = {}

    def runner(payload, **kw):
        seen.update(kw)
        return {"evaluated_rows": [{} for _ in payload["lines"]]}

    run_capture_directory(tmp_path, now=NOW, runner=runner,
                          render=lambda card, now: "")
    assert "form2_bundles_dir" not in seen and "form2_manifest_sha256" not in seen
