#!/usr/bin/env python3
"""Form 2 capture: name-charset extension for the sealing grammar
(Oct 13, 2026).

The Saturday Oct 17 capture prep (cfb_saturday_capture_prep_20261017/
REPORT.md, Finding 2) found four live charts refused wholesale with
QB_DEPTH_EVIDENCE_MISSING:CAPTURE_QB_NAME_UNPARSEABLE even though each
QB1 cell parses cleanly: a BACKUP's surname carries a shape the sealing
grammar did not admit, and the complete-rank-sequence seal refuses the
whole capture over one backup:

  * Ohio State QB2  "St. Clair, Tavien"  -- period inside a two-token
    surname ("St." is part of the family name, not a suffix);
  * Florida QB2     "Jones Jr., Tramell" -- generational suffix WITH
    period, as a second surname token;
  * Texas QB2       "Lacey Jr., Karle"   -- same class;
  * Texas Tech QB4  "Jones III, Lloyd"   -- roman-numeral suffix
    WITHOUT a period.

Root cause, two places: the capture normalizer validated the whole
pre-comma surname as ONE token (any multi-token surname refused), and
parse_qb_order's surname grammar admitted one token plus an optional
suffix that REQUIRED a trailing period. The fix widens both to a
surname TOKEN SEQUENCE over the same per-token charset
[A-Za-z][A-Za-z.'-]* -- periods inside tokens, suffixes with or
without periods, roman suffixes II/III/IV/V all ride the generic
token rule. The gate stays fail-closed: digits, symbols outside the
charset, and empty tokens still refuse with the same
CAPTURE_QB_NAME_UNPARSEABLE code (pinned below).

Fixtures: the QB rows and update-stamp divs below are trimmed
VERBATIM from the four live OurLads pages the capture helper fetches
(programmatic extraction, 2026-10-14 ~00:2xZ; pages preserved in the
prep run's raw extraction). Roster fixtures are the live ESPN
?limit=1000 QB rooms from the same sweep (athlete IDs, displayName
spellings and jerseys verbatim -- including ESPN's own suffix
spellings: "Tramell Jones Jr.", "Karle Lacey Jr.", "Lloyd Jones III",
"Tavien St. Clair").
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.prepricing import qb_identity_evidence as qe  # noqa: E402

OHIO_STATE_STAMP_DIV = '<div id="ctl00_phContent_DateUpd" class="dc-upd" style="margin-top: 8px;">Updated: 10/10/2026 9:08AM ET</div>'
OHIO_STATE_QB_ROW = "<tr class='row-dc-grey'><td class='row-dc-grey'>QB</td><td>10</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/julian-sayin/167700' class=''>Sayin, Julian RS SO</a></td><td>9</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/tavien-st.-clair/173925' class=''>St. Clair, Tavien RS FR</a></td><td>13</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/luke-fahey/178924' class='lc_purple'>Fahey, Luke FR</a></td><td>16</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/justyn-martin/153569' class='lc_gold'>Martin, Justyn RS SR/TR</a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td></tr>"
OHIO_STATE_HTML = ("<html><body>" + OHIO_STATE_STAMP_DIV + "<table>" + OHIO_STATE_QB_ROW + "</table></body></html>")
OHIO_STATE_QB_ROOM = [('5214646', 'Luke Fahey', '13'), ('5300483', 'Brady Geibel', '19'), ('4685435', 'Justyn Martin', '16'), ('5079712', 'Julian Sayin', '10'), ('5146824', 'Tavien St. Clair', '9'), ('5297799', 'Kolton Stover', '18')]

FLORIDA_STAMP_DIV = '<div id="ctl00_phContent_DateUpd" class="dc-upd" style="margin-top: 8px;">Updated: 10/10/2026 9:07AM ET</div>'
FLORIDA_QB_ROW = "<tr class='row-dc-grey'><td class='row-dc-grey'>QB</td><td>12</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/aaron-philo/168734' class='lc_gold'>Philo, Aaron RS SO/TR</a></td><td>9</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/tramell-jones-jr./175838' class=''>Jones Jr., Tramell RS FR</a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td></tr>"
FLORIDA_HTML = ("<html><body>" + FLORIDA_STAMP_DIV + "<table>" + FLORIDA_QB_ROW + "</table></body></html>")
FLORIDA_QB_ROOM = [('5159000', 'Will Griffin', '11'), ('5295814', 'Tramell Jones Jr.', '9'), ('5132812', 'Aaron Philo', '12'), ('5155039', 'Aidan Warner', '16'), ('5232555', 'Aaron Williams', '10')]

TEXAS_STAMP_DIV = '<div id="ctl00_phContent_DateUpd" class="dc-upd" style="margin-top: 8px;">Updated: 10/10/2026 9:09AM ET</div>'
TEXAS_QB_ROW = "<tr class='row-dc-grey'><td class='row-dc-grey'>QB</td><td>16</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/arch-manning/160427' class=''>Manning, Arch RS JR</a></td><td>9</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/karle-lacey-jr./174119' class=''>Lacey Jr., Karle RS FR</a></td><td>6</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/dia-bell/179052' class='lc_purple'>Bell, Dia FR</a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td></tr>"
TEXAS_HTML = ("<html><body>" + TEXAS_STAMP_DIV + "<table>" + TEXAS_QB_ROW + "</table></body></html>")
TEXAS_QB_ROOM = [('5159112', 'Dia Bell', '6'), ('5293822', 'Luke Dunham', '25'), ('5141509', 'Karle Lacey Jr.', '9'), ('4870906', 'Arch Manning', '16'), ('4685488', 'MJ Morris', '19')]

TEXAS_TECH_STAMP_DIV = '<div id="ctl00_phContent_DateUpd" class="dc-upd" style="margin-top: 8px;">Updated: 10/10/2026 9:09AM ET</div>'
TEXAS_TECH_QB_ROW = "<tr class='row-dc-grey'><td class='row-dc-grey'>QB</td><td>15</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/will-hammond/168799' class=''>Hammond, Will RS SO</a></td><td>4</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/thomas-castellanos/163453' class='lc_gold'>Castellanos, Thomas SR/TR</a></td><td>18</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/kirk-francis/163992' class='lc_gold'>Francis, Kirk RS JR/TR</a></td><td>10</td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player/lloyd-jones-iii/174718' class=''>Jones III, Lloyd RS FR</a></td><td></td><td><a href='https://www.ourlads.com/ncaa-football-depth-charts/player//0' class=''></a></td></tr>"
TEXAS_TECH_HTML = ("<html><body>" + TEXAS_TECH_STAMP_DIV + "<table>" + TEXAS_TECH_QB_ROW + "</table></body></html>")
TEXAS_TECH_QB_ROOM = [('5276590', 'Stephen Cannon', '12'), ('4773919', 'Thomas Castellanos', '4'), ('5151618', 'Kirk Francis', '18'), ('5126468', 'Will Hammond', '15'), ('5141535', 'Lloyd Jones III', '10'), ('5294079', 'Holden Phillips', '16')]


KICKOFF = {
    "194": datetime(2026, 10, 17, 16, 0, tzinfo=timezone.utc),
    "57": datetime(2026, 10, 17, 16, 0, tzinfo=timezone.utc),
    "251": datetime(2026, 10, 17, 16, 0, tzinfo=timezone.utc),
    "2641": datetime(2026, 10, 17, 19, 30, tzinfo=timezone.utc),
}
CAPTURED_DT = datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc)

TEAMS = {
    "194": {"html": OHIO_STATE_HTML, "room": OHIO_STATE_QB_ROOM,
            "stamp_line": "Updated: 10/10/2026 9:08AM ET",
            "url": ("https://www.ourlads.com/ncaa-football-depth-charts/"
                    "depth-chart/ohio-state/91533"),
            "event": "401858488", "opponent": "84",
            "home": "84", "away": "194",
            "kickoff_iso": "2026-10-17T16:00:00Z",
            "prev": "2026-10-10T20:15:00Z", "qb1_id": "5079712",
            "stale": True},
    "57": {"html": FLORIDA_HTML, "room": FLORIDA_QB_ROOM,
           "stamp_line": "Updated: 10/10/2026 9:07AM ET",
           "url": ("https://www.ourlads.com/ncaa-football-depth-charts/"
                   "depth-chart/florida/90498"),
           "event": "401856724", "opponent": "251",
           "home": "251", "away": "57",
           "kickoff_iso": "2026-10-17T16:00:00Z",
           "prev": "2026-10-10T16:45:00Z", "qb1_id": "5132812",
           "stale": True},
    "251": {"html": TEXAS_HTML, "room": TEXAS_QB_ROOM,
            "stamp_line": "Updated: 10/10/2026 9:09AM ET",
            "url": ("https://www.ourlads.com/ncaa-football-depth-charts/"
                    "depth-chart/texas/92016"),
            "event": "401856724", "opponent": "57",
            "home": "251", "away": "57",
            "kickoff_iso": "2026-10-17T16:00:00Z",
            "prev": "2026-10-10T19:30:00Z", "qb1_id": "4870906",
            "stale": True},
    "2641": {"html": TEXAS_TECH_HTML, "room": TEXAS_TECH_QB_ROOM,
             "stamp_line": "Updated: 10/10/2026 9:09AM ET",
             "url": ("https://www.ourlads.com/ncaa-football-depth-charts/"
                     "depth-chart/texas-tech/92062"),
             "event": "401856828", "opponent": "9",
             "home": "2641", "away": "9",
             "kickoff_iso": "2026-10-17T19:30:00Z",
             "prev": "2026-10-03T23:30:00Z", "qb1_id": "5126468",
             "stale": False},
}

EXPECTED_ORDER = {
    "194": [{"rank": 1, "name": "Sayin, Julian", "jersey": "10"},
            {"rank": 2, "name": "St. Clair, Tavien", "jersey": "9"},
            {"rank": 3, "name": "Fahey, Luke", "jersey": "13"},
            {"rank": 4, "name": "Martin, Justyn", "jersey": "16"}],
    "57": [{"rank": 1, "name": "Philo, Aaron", "jersey": "12"},
           {"rank": 2, "name": "Jones Jr., Tramell", "jersey": "9"}],
    "251": [{"rank": 1, "name": "Manning, Arch", "jersey": "16"},
            {"rank": 2, "name": "Lacey Jr., Karle", "jersey": "9"},
            {"rank": 3, "name": "Bell, Dia", "jersey": "6"}],
    "2641": [{"rank": 1, "name": "Hammond, Will", "jersey": "15"},
             {"rank": 2, "name": "Castellanos, Thomas", "jersey": "4"},
             {"rank": 3, "name": "Francis, Kirk", "jersey": "18"},
             {"rank": 4, "name": "Jones III, Lloyd", "jersey": "10"}],
}


def _roster_obj(team_id):
    athletes = [{"id": i, "displayName": n, "fullName": n, "jersey": j,
                 "position": {"id": "8", "name": "Quarterback",
                              "abbreviation": "QB"},
                 "status": {"id": "1", "name": "Active", "type": "active"},
                 "injuries": []} for (i, n, j) in TEAMS[team_id]["room"]]
    return {"timestamp": "2026-10-14T00:30:00Z", "team": {"id": team_id},
            "athletes": [{"position": "offense", "items": athletes}]}


def _refusal(fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("expected a ValueError refusal")


def _capture(team_id, content=None):
    meta = TEAMS[team_id]
    roster = _roster_obj(team_id)
    return qe.capture_form2_bundle(
        team_id=team_id, team_name=f"Team {team_id}",
        event_id=meta["event"], opponent_id=meta["opponent"],
        kickoff_utc=meta["kickoff_iso"],
        previous_game_kickoff_utc=meta["prev"],
        depth_url=meta["url"],
        fetch_text=lambda _url: meta["html"] if content is None else content,
        fetch_json=lambda _url: json.loads(json.dumps(roster)),
        clock=lambda: CAPTURED_DT)


def _evaluate(team_id, bundle):
    meta = TEAMS[team_id]
    return qe.evaluate_form2_bundle(
        bundle, team_id=team_id, kickoff=KICKOFF[team_id],
        previous_game_kickoff=None, now=CAPTURED_DT,
        event_id=meta["event"], home_team_id=meta["home"],
        away_team_id=meta["away"])


# ---------------------------------------------------------------------------
# The four real charts: the normalizer now seals the published orders,
# suffixed backups included, verbatim.
# ---------------------------------------------------------------------------
def test_normalizer_extracts_all_four_published_orders():
    for team_id, meta in TEAMS.items():
        serialization = qe.normalize_ourlads_depth_html(meta["html"])
        assert serialization.splitlines()[0] == meta["stamp_line"], team_id
        assert qe.parse_qb_order(serialization) == EXPECTED_ORDER[team_id], \
            team_id


def test_split_qb_name_cell_accepts_attested_shapes():
    assert qe._split_qb_name_cell("St. Clair, Tavien RS FR") == \
        ("St. Clair, Tavien", "RS FR")
    assert qe._split_qb_name_cell("Jones Jr., Tramell RS FR") == \
        ("Jones Jr., Tramell", "RS FR")
    assert qe._split_qb_name_cell("Lacey Jr., Karle RS FR") == \
        ("Lacey Jr., Karle", "RS FR")
    assert qe._split_qb_name_cell("Jones III, Lloyd RS FR") == \
        ("Jones III, Lloyd", "RS FR")


# ---------------------------------------------------------------------------
# Sealing-parser grammar classes (the numbered serialization the
# evaluator derives the order from).
# ---------------------------------------------------------------------------
def test_parse_qb_order_suffix_and_surname_classes():
    text = ("Updated: 10/10/2026 9:09AM ET\n"
            "1. Jones III, Lloyd — RS FR #10\n"
            "2. Jones Jr, Tramell — RS FR #9\n"
            "3. Smith Sr, John — SR #7\n"
            "4. Smith V, John — FR #3\n"
            "5. St. Clair, Tavien — RS FR #9\n"
            "6. Smith-Jones, Jaron-Keawe — FR #5\n"
            "7. O'Brien, Connor — SO #4")
    order = qe.parse_qb_order(text)
    assert [e["name"] for e in order] == [
        "Jones III, Lloyd", "Jones Jr, Tramell", "Smith Sr, John",
        "Smith V, John", "St. Clair, Tavien", "Smith-Jones, Jaron-Keawe",
        "O'Brien, Connor"]
    assert [e["rank"] for e in order] == [1, 2, 3, 4, 5, 6, 7]


def test_text_serialization_capture_with_roman_suffix_unchanged():
    """A page already in the numbered serialization passes through the
    capture path byte-identical, roman suffix included (the evaluator's
    derivation reads the same grammar at gate time)."""
    text = ("Updated: 10/10/2026 9:09AM ET\n"
            "1. Hammond, Will — RS SO #15\n"
            "2. Castellanos, Thomas — SR/TR #4\n"
            "3. Francis, Kirk — RS JR/TR #18\n"
            "4. Jones III, Lloyd — RS FR #10")
    bundle = _capture("2641", content=text)
    assert bundle["depth_snapshot"]["content"] == text
    assert bundle["depth_snapshot"]["qb_order"] == EXPECTED_ORDER["2641"]


# ---------------------------------------------------------------------------
# End-to-end: all four teams SEAL now (the charset refusal is gone).
# Admission then follows the ordinary rules: Texas Tech's stamp
# postdates its previous game, so it SATISFIES with the live QB1 ID;
# the other three charts predate their teams' Oct 10 games and the
# evaluator still refuses them STALE -- the fix widens the name
# grammar, it does not touch the staleness gate.
# ---------------------------------------------------------------------------
def test_capture_seals_all_four_and_evaluation_verdicts():
    for team_id in TEAMS:
        bundle = _capture(team_id)
        assert bundle["depth_snapshot"]["qb_order"] == \
            EXPECTED_ORDER[team_id], team_id
        result = _evaluate(team_id, bundle)
        if TEAMS[team_id]["stale"]:
            assert not result["ok"], (team_id, result)
            assert result["status"] == qe.STATUS_STALE, (team_id, result)
            assert result["detail"] == \
                "STAMP_PREDATES_PREVIOUS_GAME_KICKOFF", (team_id, result)
        else:
            assert result["ok"], (team_id, result)
            assert result["resolved_athlete_id"] == \
                TEAMS[team_id]["qb1_id"], (team_id, result)
            assert result["availability_status"] == \
                qe.AVAILABILITY_UNVERIFIED
            assert result["injury_points"] == 0.0


# ---------------------------------------------------------------------------
# Hostile shapes: the widened grammar still refuses, with the same
# code, everything outside the attested name classes.
# ---------------------------------------------------------------------------
def _html_with_name_cell(name_cell, jersey="10"):
    row = (f"<tr><td>QB</td><td>{jersey}</td><td>{name_cell}</td></tr>")
    return ("<html><body>" + OHIO_STATE_STAMP_DIV + "<table>" + row
            + "</table></body></html>")


def test_digit_in_surname_refused():
    html = _html_with_name_cell("Sm1th, John RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_digit_in_first_name_refused():
    html = _html_with_name_cell("Smith, J0hn RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_symbol_in_surname_refused():
    html = _html_with_name_cell("Sm!th, John RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_punctuation_storm_surname_refused():
    html = _html_with_name_cell("..., John RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_ordinal_suffix_token_refused():
    html = _html_with_name_cell("Jones 3rd, John RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_hash_in_surname_refused():
    html = _html_with_name_cell("Smith#, John RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_empty_surname_refused():
    html = _html_with_name_cell(", John RS FR")
    assert "CAPTURE_QB_NAME_UNPARSEABLE" in _refusal(
        qe.normalize_ourlads_depth_html, html)


def test_suffix_only_distinction_still_duplicate_refused():
    """Two published entries whose canonical name keys collide once
    the generational suffix is accounted for are still the same name
    twice in the published order."""
    row = ("<tr><td>QB</td><td>9</td><td>Jones Jr., Tramell RS FR</td>"
           "<td>8</td><td>Jones, Tramell RS SO</td></tr>")
    html = ("<html><body>" + OHIO_STATE_STAMP_DIV + "<table>" + row
            + "</table></body></html>")
    assert "CAPTURE_DUPLICATE_QB_NAME" in _refusal(
        qe.normalize_ourlads_depth_html, html)


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
