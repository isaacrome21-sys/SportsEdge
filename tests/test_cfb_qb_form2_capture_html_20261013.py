#!/usr/bin/env python3
"""Form 2 capture: live OurLads HTML table normalization (Oct 13, 2026).

The capture helper's own fetch returns the live OurLads chart page,
which publishes the depth chart as an HTML table. parse_qb_order
seals only the numbered text serialization, so the Oct 13 FIU/JSU
captures failed closed with QB_DEPTH_EVIDENCE_MISSING:
NO_QB_ORDER_CAPTURED on pages that fetched fine (diagnosis:
run_it_20261013_cfb2_fix/FIX_REPORT.md).

These tests pin the capture-side normalizer
(``normalize_ourlads_depth_html``) and its integration into
``capture_form2_bundle``:

  * The HTML fixtures below are trimmed VERBATIM from the two real
    pages the helper fetched on 2026-10-13 (preserved as
    DIAGNOSTIC_ourlads_fiu_live.html / DIAGNOSTIC_ourlads_jsu_live.html
    in the run folder): the verbatim update-stamp div and the verbatim
    QB table row, inside minimal table markup. Only irrelevant page
    chrome was removed; no cell text was altered.
  * The extracted orders must equal the published ones, and a bundle
    built through the full capture path on fixture data must evaluate
    SATISFIED with the recorded ESPN athlete IDs.
  * Hostile shapes (two QB rows, a hole in the published order, a
    missing stamp, a name-less row, a jersey-less row, a duplicate
    name) each refuse with a named detail.

Roster fixtures mirror the recorded ?limit=1000 pulls used by the
Form 2 battery (QB rooms verbatim; athlete IDs are the recorded ESPN
IDs, incl. 4870883 JJ Kohl and 5122157 Caden Creel).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.prepricing import qb_identity_evidence as qe  # noqa: E402

KICKOFF_ISO = "2026-10-14T00:00:00Z"
KICKOFF = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
CAPTURED_ISO = "2026-10-13T23:12:00Z"
CAPTURED_DT = datetime(2026, 10, 13, 23, 12, tzinfo=timezone.utc)

STAMP_DIV = ('<div id="ctl00_phContent_DateUpd" class="dc-upd" '
             'style="margin-top: 8px;">Updated: 10/10/2026 9:08AM ET</div>')

# Verbatim QB rows from the live pages (see module docstring).
FIU_QB_ROW = (
    "<tr class='row-dc-grey'><td class='row-dc-grey'>QB</td><td>17</td><td><a href='https://www.ourl"
    "ads.com/ncaa-football-depth-charts/player/jj-kohl/160507' class='lc_gold'>Kohl, JJ RS JR/TR</a>"
    "</td><td>11</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/zach-mar"
    "ker/177143' class='lc_gold'>Marker, Zach GR/TR</a></td><td></td><td><a href='https://www.ourlad"
    "s.com/ncaa-football-depth-charts/player//0' class=''></a></td><td></td><td><a href='https://www"
    ".ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td><td></td><td><a href='http"
    "s://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td></tr>")
JSU_QB_ROW = (
    "<tr class='row-dc-grey'><td class='row-dc-grey'>QB</td><td>12</td><td><a href='https://www.ourl"
    "ads.com/ncaa-football-depth-charts/player/caden-creel/164955' class=''>Creel, Caden RS JR</a></"
    "td><td>15</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/jack-moran"
    "/177926' class=''>Moran, Jack RS FR</a></td><td>2</td><td><a href='https://www.ourlads.com/ncaa"
    "-football-depth-charts/player/kadyn-palmer/183762' class=''>Palmer, Kadyn RS FR</a></td><td></t"
    "d><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td>"
    "<td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></"
    "a></td></tr>")

FIU_HTML = ("<html><body>" + STAMP_DIV + "<table>" + FIU_QB_ROW
            + "</table></body></html>")
JSU_HTML = ("<html><body>" + STAMP_DIV + "<table>" + JSU_QB_ROW
            + "</table></body></html>")

FIU_URL = ("https://www.ourlads.com/ncaa-football-depth-charts/"
           "depth-chart/florida-international/90475")
JSU_URL = ("https://www.ourlads.com/ncaa-football-depth-charts/"
           "depth-chart/jacksonville-state/93028/")
PREV = {"2229": "2026-10-08T00:04:00Z", "55": "2026-10-07T23:00:00Z"}

QB_ROOMS = {
    "2229": [("4870883", "JJ Kohl", "17"), ("5153845", "Zach Marker", "11"),
             ("5220127", "Trey Whirley", "23")],
    "55": [("5122157", "Caden Creel", "12"), ("5222557", "Jack Moran", "15"),
           ("5296090", "Kadyn Palmer", "2")],
}
EXPECTED_ORDER = {
    "2229": [{"rank": 1, "name": "Kohl, JJ", "jersey": "17"},
             {"rank": 2, "name": "Marker, Zach", "jersey": "11"}],
    "55": [{"rank": 1, "name": "Creel, Caden", "jersey": "12"},
           {"rank": 2, "name": "Moran, Jack", "jersey": "15"},
           {"rank": 3, "name": "Palmer, Kadyn", "jersey": "2"}],
}
EXPECTED_QB1_ID = {"2229": "4870883", "55": "5122157"}


def _roster_obj(team_id):
    athletes = [{"id": i, "displayName": n, "fullName": n, "jersey": j,
                 "position": {"id": "8", "name": "Quarterback",
                              "abbreviation": "QB"},
                 "status": {"id": "1", "name": "Active", "type": "active"},
                 "injuries": []} for (i, n, j) in QB_ROOMS[team_id]]
    return {"timestamp": CAPTURED_ISO, "team": {"id": team_id},
            "athletes": [{"position": "offense", "items": athletes}]}


def _refusal(fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("expected a ValueError refusal")


# ---------------------------------------------------------------------------
# Normalizer: the published orders, exactly.
# ---------------------------------------------------------------------------
def test_normalizer_extracts_fiu_published_order():
    serialization = qe.normalize_ourlads_depth_html(FIU_HTML)
    assert serialization.splitlines()[0] == "Updated: 10/10/2026 9:08AM ET"
    assert qe.parse_qb_order(serialization) == EXPECTED_ORDER["2229"]


def test_normalizer_extracts_jsu_published_order():
    serialization = qe.normalize_ourlads_depth_html(JSU_HTML)
    assert qe.parse_qb_order(serialization) == EXPECTED_ORDER["55"]


def test_normalizer_ignores_non_qb_rows():
    html = ("<html><body>" + STAMP_DIV + "<table>"
            "<tr><td>RB</td><td>4</td><td>Runner, Some RB</td></tr>"
            + FIU_QB_ROW + "</table></body></html>")
    assert qe.parse_qb_order(qe.normalize_ourlads_depth_html(html)) \
        == EXPECTED_ORDER["2229"]


# ---------------------------------------------------------------------------
# End-to-end: capture path (injected fetchers) -> bundle -> evaluator.
# ---------------------------------------------------------------------------
def _capture(team_id, html, url):
    roster = _roster_obj(team_id)
    opponent = "55" if team_id == "2229" else "2229"
    return qe.capture_form2_bundle(
        team_id=team_id, team_name=f"Team {team_id}",
        event_id="401871053", opponent_id=opponent,
        kickoff_utc=KICKOFF_ISO, previous_game_kickoff_utc=PREV[team_id],
        depth_url=url,
        fetch_text=lambda _url: html,
        fetch_json=lambda _url: json.loads(json.dumps(roster)),
        clock=lambda: CAPTURED_DT)


def test_capture_and_evaluate_end_to_end():
    for team_id, html, url in (("2229", FIU_HTML, FIU_URL),
                               ("55", JSU_HTML, JSU_URL)):
        bundle = _capture(team_id, html, url)
        assert bundle["depth_snapshot"]["qb_order"] == EXPECTED_ORDER[team_id]
        result = qe.evaluate_form2_bundle(
            bundle, team_id=team_id, kickoff=KICKOFF,
            previous_game_kickoff=None, now=CAPTURED_DT,
            event_id="401871053", home_team_id="55", away_team_id="2229")
        assert result["ok"], result
        assert result["resolved_athlete_id"] == EXPECTED_QB1_ID[team_id]
        assert result["availability_status"] == qe.AVAILABILITY_UNVERIFIED
        assert result["injury_points"] == 0.0


def test_text_serialization_captures_unchanged():
    """A page already in the numbered serialization passes through the
    capture path byte-identical (the normalizer never engages)."""
    text = ("Updated: 10/10/2026 9:08AM ET\n"
            "1. Kohl, JJ — RS JR/TR, #17 · 2. Marker, Zach — GR/TR, #11")
    bundle = _capture("2229", text, FIU_URL)
    assert bundle["depth_snapshot"]["content"] == text


# ---------------------------------------------------------------------------
# Hostile shapes: each refuses, named.
# ---------------------------------------------------------------------------
def test_two_qb_tables_refused():
    html = ("<html><body>" + STAMP_DIV + "<table>" + FIU_QB_ROW
            + JSU_QB_ROW + "</table></body></html>")
    assert "CAPTURE_MULTIPLE_QB_ROWS" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_missing_stamp_refused():
    html = "<html><body><table>" + FIU_QB_ROW + "</table></body></html>"
    assert "UPDATE_STAMP_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_no_qb_row_refused():
    html = ("<html><body>" + STAMP_DIV + "<table>"
            "<tr><td>RB</td><td>4</td><td>Runner, Some RB</td></tr>"
            "</table></body></html>")
    assert "NO_QB_ORDER_CAPTURED" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_hole_in_published_order_refused():
    row = ("<tr><td>QB</td><td>17</td><td>Kohl, JJ RS JR/TR</td>"
           "<td></td><td></td>"
           "<td>11</td><td>Marker, Zach GR/TR</td></tr>")
    html = "<html><body>" + STAMP_DIV + "<table>" + row + "</table></body></html>"
    assert "CAPTURE_QB_ROW_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_nameless_row_refused():
    row = ("<tr><td>QB</td><td>17</td><td></td>"
           "<td>11</td><td>Marker, Zach GR/TR</td></tr>")
    html = "<html><body>" + STAMP_DIV + "<table>" + row + "</table></body></html>"
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_unparseable_name_refused():
    row = ("<tr><td>QB</td><td>17</td><td>Kohl (no comma here)</td></tr>")
    html = "<html><body>" + STAMP_DIV + "<table>" + row + "</table></body></html>"
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_jerseyless_row_refused():
    row = ("<tr><td>QB</td><td></td><td>Kohl, JJ RS JR/TR</td></tr>")
    html = "<html><body>" + STAMP_DIV + "<table>" + row + "</table></body></html>"
    assert "CAPTURE_QB_JERSEY_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_duplicate_name_refused():
    row = ("<tr><td>QB</td><td>17</td><td>Kohl, JJ RS JR/TR</td>"
           "<td>9</td><td>Kohl, JJ RS SO</td></tr>")
    html = "<html><body>" + STAMP_DIV + "<table>" + row + "</table></body></html>"
    assert "CAPTURE_DUPLICATE_QB_NAME" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_capture_refuses_hostile_page_end_to_end():
    html = ("<html><body>" + STAMP_DIV + "<table>" + FIU_QB_ROW
            + JSU_QB_ROW + "</table></body></html>")
    assert "CAPTURE_MULTIPLE_QB_ROWS" in _refusal(
        _capture, "2229", html, FIU_URL)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(dict(globals()).items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc!r}")
    sys.exit(1 if failures else 0)
