"""Offline guards for the CBB team-totals forward runner BUILD
(sportsedge/cbb_team_total_forward.py).

The readout family is NOT FROZEN: counted entry points refuse
CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN, records are NON_COUNTED and
carry their Amendment 2 section 1 designation at the TEAM_TOTAL
threshold 2.1, the forward accuracy leg names the SIMPLE
baseline only (package answer A-1 — no naive value is recorded),
and model team points are exactly the parent construction's
expected team points.
"""

import csv
import hashlib
import io
import json
from datetime import datetime, timezone

import pytest

from sportsedge import cbb_amendment2_machinery as amendment2
from sportsedge import cbb_torvik_efficiency_v1 as core
from sportsedge.cbb_team_total_forward import (
    CbbTeamTotalForwardRunner,
    games_from_board,
)
from sportsedge.cbb_torvik_efficiency_v1 import (
    CbbForwardError,
    CbbSlateGame,
    PairedQuote,
    load_vintage,
)

SLATE = "2026-11-02"
TIP = "2026-11-02T18:30:00Z"
NOW = datetime(2026, 11, 2, 17, 30, tzinfo=timezone.utc)
CAP = "2026-11-02T17:29:00Z"

TEAMS = [("Duke", 118.0, 92.0, 68.0), ("Kansas", 116.0, 94.0, 67.0),
         ("Illinois", 112.0, 95.0, 66.0)]


def _store(tmp_path):
    rows = TEAMS + [(f"Filler {i:03d}", 100.0, 100.0, 68.0)
                    for i in range(320)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "team", "conf", "record", "adjoe", "oe Rank",
                "adjde", "de Rank", "barthag", "adjt"])
    for i, (team, o, d, t) in enumerate(rows, 1):
        w.writerow([i, team, "X", "0-0", o, 1, d, 1, 0.5, t])
    raw = buf.getvalue().encode("utf-8")
    store = tmp_path / "torvik_morning"
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{SLATE}.csv").write_bytes(raw)
    (store / f"{SLATE}.json").write_text(json.dumps({
        "season_year": 2027, "as_of_local_date": SLATE,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "team_rows": len(rows),
        "evidence_state": "verified-by-pull"}))
    return store


def _quote(line, pa=-110, pb=-110, cap=CAP):
    return PairedQuote(line=line, side_a_price=pa, side_b_price=pb,
                       side_a_captured_at=cap, side_b_captured_at=cap)


def _game(away="150", home="2305", event="401900001", **kw):
    quotes = {"TEAM_TOTAL_AWAY": _quote(74.5),
              "TEAM_TOTAL_HOME": _quote(71.5)}
    quotes.update(kw.pop("quotes", {}))
    return CbbSlateGame(espn_event_id=event, slate_date=SLATE,
                        away_espn_id=away, home_espn_id=home,
                        neutral_site=kw.pop("neutral_site", False),
                        tip_utc=TIP, entry_quotes=quotes, **kw)


@pytest.fixture()
def runner():
    return CbbTeamTotalForwardRunner()


@pytest.fixture()
def vintage(tmp_path):
    return load_vintage(SLATE, _store(tmp_path))


def test_happy_path_two_team_records_readout_of_parent(runner,
                                                       vintage):
    out = runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW)
    assert out["counted"] is False and out["refusals"] == []
    assert len(out["records"]) == 2
    by_team = {r["team"]: r for r in out["records"]}
    expected = core.model_outputs(
        core.TeamRatings(116.0, 94.0, 67.0),
        core.TeamRatings(118.0, 92.0, 68.0),
        vintage.league_mean_eff, vintage.league_mean_tempo, False)
    duke = by_team["duke"]
    assert duke["venue"] == "AWAY" and duke["market"] == "TEAM_TOTAL"
    assert duke["model_team_points_candidate"] == \
        expected["expected_points_away_candidate"]
    assert duke["model_team_points_baseline_simple"] == \
        expected["expected_points_away_baseline_simple"]
    assert by_team["kansas"]["model_team_points_candidate"] == \
        expected["expected_points_home_candidate"]
    for rec in out["records"]:
        assert rec["counted"] is False
        # Amendment 2 section 1 designation, TEAM_TOTAL threshold.
        expected = amendment2.designate_pick(
            "TEAM_TOTAL", rec["model_team_points_candidate"],
            rec["line"])
        assert rec["gap"] == expected["gap"]
        assert rec["designated_side"] == expected["designated_side"]
        assert rec["classification"] == expected["classification"]
        assert rec["pick"] == (
            expected["designated_side"]
            if expected["classification"] == "PICKED" else None)
        assert rec["pick_threshold"] == 2.1
        assert rec["pick_rule"] == "AMENDMENT_2_S1_PICK_RULE"
        assert rec["close_rule"] == "AMENDMENT_2_S3_CLOSE_VALIDITY"
        assert rec["amendment_2_sha256"] == \
            "25be46029ca1933e1a2eb7d7aa6a858928f3879a254285e90a0b9bf1270d926a"
        # A-1: simple baseline ONLY forward — no naive field exists.
        assert rec["forward_baselines"] == ["SIMPLE_RATINGS"]
        assert not any("naive" in k for k in rec)
        assert rec["construction_of_record_sha256"] == \
            "ac01327a4ed3bb9a37f03e7a9391d2a0918d4f022c86de42bb841a9f15044989"


def test_designated_pick_lands_on_the_record(runner, vintage):
    game = _game(quotes={"TEAM_TOTAL_AWAY": _quote(70.0)})
    out = runner.price_slate(SLATE, [game], vintage=vintage, now=NOW)
    duke = [r for r in out["records"] if r["team"] == "duke"][0]
    # Duke's expected points (~75.5) against a 70.0 line clear the
    # 2.1 threshold: a PICKED OVER row, designated before tip.
    assert duke["classification"] == "PICKED"
    assert duke["designated_side"] == "OVER" and duke["pick"] == "OVER"
    assert duke["gap"] == duke["model_team_points_candidate"] - 70.0


def test_counted_entry_points_refuse_not_frozen(runner, vintage):
    with pytest.raises(CbbForwardError) as exc:
        runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW,
                           counted=True)
    assert exc.value.reason == "CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN"
    with pytest.raises(CbbForwardError) as exc:
        runner.price_counted_slate(SLATE, [], vintage=vintage, now=NOW)
    assert exc.value.reason == "CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN"
    with pytest.raises(CbbForwardError) as exc:
        runner.run_forward_test([])
    assert exc.value.reason == "CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN"


def test_illinois_and_missing_section_refuse(runner, vintage):
    out = runner.price_slate(SLATE, [_game(home="356")],
                             vintage=vintage, now=NOW)
    assert out["records"] == []
    assert out["refusals"][0]["reason"] == "ILLINOIS_COLLEGE_EXCLUDED"
    game = _game(event="401900002", quotes={"TEAM_TOTAL_HOME": None})
    out2 = runner.price_slate(SLATE, [game], vintage=vintage, now=NOW)
    assert [r["team"] for r in out2["records"]] == ["duke"]
    assert out2["refusals"][0]["reason"] == "ENTRY_CAPTURE_MISSING"
    assert out2["refusals"][0]["team"] == "kansas"


def test_settlement_team_points(runner, vintage):
    out = runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW)
    finals = {"401900001": {"home_points": 80, "away_points": 70}}
    settled = runner.settle_records(out["records"], finals)
    by_team = {s["team"]: s for s in settled}
    assert by_team["duke"]["actual_team_points"] == 70
    assert by_team["kansas"]["actual_team_points"] == 80
    rec = [r for r in out["records"] if r["team"] == "duke"][0]
    assert by_team["duke"]["abs_error_candidate"] == abs(
        rec["model_team_points_candidate"] - 70)
    assert all(s["counted"] is False for s in settled)


def test_games_from_board_maps_subject_teams_to_sections():
    board = {"sport": "CBB", "board_captured_at": CAP, "games": [{
        "away": "Duke", "home": "Kansas", "header": "Duke @ Kansas",
        "captured_at": CAP,
        "markets": [
            {"market": "TEAM_TOTAL", "family": "team_total",
             "line": 74.5, "side_a": "OVER", "price_a": -110,
             "side_b": "UNDER", "price_b": -110, "raw": "",
             "subject": "team", "team": "Duke"},
            {"market": "TEAM_TOTAL", "family": "team_total",
             "line": 71.5, "side_a": "OVER", "price_a": -115,
             "side_b": "UNDER", "price_b": -105, "raw": "",
             "subject": "team", "team": "Kansas"}]}]}
    fixtures = {"Duke@Kansas": {
        "espn_event_id": "401900001", "away_espn_id": "150",
        "home_espn_id": "2305", "neutral_site": False,
        "tip_utc": TIP, "slate_date": SLATE}}
    games = games_from_board(board, fixtures)
    assert len(games) == 1
    quotes = games[0].entry_quotes
    assert quotes["TEAM_TOTAL_AWAY"].line == 74.5
    assert quotes["TEAM_TOTAL_HOME"].side_a_price == -115
