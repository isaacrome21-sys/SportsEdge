"""Offline guards for the CBB_TORVIK_EFFICIENCY_V1 forward runner
BUILD (sportsedge/cbb_efficiency_forward.py).

The family is NOT FROZEN: these tests pin the build's contract —
every counted entry point refuses CBB_EFFICIENCY_FORWARD_NOT_FROZEN,
every record is NON_COUNTED with the G-1/G-2/G-3 gap stamps, the
Illinois exclusion and identity rules refuse fail-closed, and the
create-only writer never overwrites. Synthetic vintage under
tmp_path; the real crosswalk and package pins are read from the
repo (the runner verifies them at construction).
"""

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sportsedge import cbb_torvik_efficiency_v1 as core
from sportsedge.cbb_efficiency_forward import (
    CbbEfficiencyForwardRunner,
    games_from_board,
)
from sportsedge.cbb_torvik_efficiency_v1 import (
    CbbForwardError,
    CbbSlateGame,
    PairedQuote,
    load_vintage,
    write_entry_records,
)

SLATE = "2026-11-02"
TIP = "2026-11-02T18:30:00Z"
NOW = datetime(2026, 11, 2, 17, 30, tzinfo=timezone.utc)
CAP = "2026-11-02T17:29:00Z"

TEAMS = [("Duke", 118.0, 92.0, 68.0), ("Kansas", 116.0, 94.0, 67.0),
         ("Illinois", 112.0, 95.0, 66.0), ("Purdue", 117.0, 93.0, 65.5)]


def _store(tmp_path, teams=None):
    rows = (TEAMS if teams is None else teams) + [
        (f"Filler {i:03d}", 100.0, 100.0, 68.0) for i in range(320)]
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
    quotes = {"SPREAD": _quote(-4.5), "TOTAL": _quote(145.5)}
    quotes.update(kw.pop("quotes", {}))
    return CbbSlateGame(espn_event_id=event, slate_date=SLATE,
                        away_espn_id=away, home_espn_id=home,
                        neutral_site=kw.pop("neutral_site", False),
                        tip_utc=TIP, entry_quotes=quotes, **kw)


@pytest.fixture()
def runner(tmp_path):
    return CbbEfficiencyForwardRunner()


@pytest.fixture()
def vintage(tmp_path):
    return load_vintage(SLATE, _store(tmp_path))


def test_happy_path_records_are_non_counted_and_gap_stamped(
        runner, vintage):
    out = runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW)
    assert out["counted"] is False and out["refusals"] == []
    assert len(out["records"]) == 2
    by_market = {r["market"]: r for r in out["records"]}
    spread = by_market["SPREAD"]
    assert spread["counted"] is False
    assert spread["freeze_state"] == "DRAFT_NOT_IN_FORCE"
    assert spread["verified_play"] is False
    # G-1: no pick is designated, ever, in this build.
    assert spread["classification"] == "PICK_RULE_UNDEFINED"
    assert spread["pick"] is None and spread["pick_rule"] == \
        "PICK_RULE_UNDEFINED"
    assert spread["interval_construction"] == \
        "INTERVAL_CONSTRUCTION_UNDEFINED_GAP_G2"
    assert spread["close_rule"] == "CLOSE_RULE_UNDEFINED_GAP_G3"
    # Identity resolved through the crosswalk, not display names.
    assert spread["away_team"] == "duke"
    assert spread["home_team"] == "kansas"
    # Pins: construction of record + package + vintage are committed.
    assert spread["construction_of_record_sha256"] == \
        "75479ea14b2ab4ef954bd4cde629a2d00e24efea173ac61c695482890dd4c45e"
    assert spread["crosswalk_sha256"].startswith("6cf6b033")
    assert spread["torvik_vintage_sha256"] == vintage.sha256
    # Model outputs equal the shared core's, computed independently.
    expected = core.model_outputs(
        core.TeamRatings(116.0, 94.0, 67.0),
        core.TeamRatings(118.0, 92.0, 68.0),
        vintage.league_mean_eff, vintage.league_mean_tempo, False)
    total = by_market["TOTAL"]
    assert total["model_total_candidate"] == \
        expected["model_total_candidate"]
    assert spread["model_margin_home_candidate"] == \
        expected["model_margin_home_candidate"]
    assert spread["no_vig_prob_side_a"] + spread[
        "no_vig_prob_side_b"] == pytest.approx(1.0)


def test_counted_entry_points_refuse_not_frozen(runner, vintage):
    with pytest.raises(CbbForwardError) as exc:
        runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW,
                           counted=True)
    assert exc.value.reason == "CBB_EFFICIENCY_FORWARD_NOT_FROZEN"
    with pytest.raises(CbbForwardError) as exc:
        runner.price_counted_slate(SLATE, [], vintage=vintage, now=NOW)
    assert exc.value.reason == "CBB_EFFICIENCY_FORWARD_NOT_FROZEN"
    with pytest.raises(CbbForwardError) as exc:
        runner.run_forward_test([])
    assert exc.value.reason == "CBB_EFFICIENCY_FORWARD_NOT_FROZEN"


def test_illinois_game_is_excluded(runner, vintage):
    game = _game(home="356")  # Illinois, ESPN id in the denylist
    out = runner.price_slate(SLATE, [game], vintage=vintage, now=NOW)
    assert out["records"] == []
    assert [r["reason"] for r in out["refusals"]] == [
        "ILLINOIS_COLLEGE_EXCLUDED"]


def test_unverified_identity_refuses(runner, vintage):
    out = runner.price_slate(SLATE, [_game(away="999999999")],
                             vintage=vintage, now=NOW)
    assert out["records"] == []
    assert out["refusals"][0]["reason"] == "IDENTITY_UNVERIFIED"


def test_team_not_in_vintage_refuses(runner, tmp_path):
    teams = [t for t in TEAMS if t[0] != "Purdue"]
    thin_vintage = load_vintage(SLATE, _store(tmp_path, teams=teams))
    assert "Purdue" not in thin_vintage.by_team
    game = _game(away="2509")  # Purdue resolves in the crosswalk...
    out = runner.price_slate(SLATE, [game], vintage=thin_vintage,
                             now=NOW)
    assert out["records"] == []  # ...but is not carried by the vintage
    assert out["refusals"][0]["reason"] == "TORVIK_TEAM_NOT_CARRIED"


def test_missing_and_single_sided_markets_refuse_per_market(
        runner, vintage):
    game = _game(quotes={"TOTAL": None})
    out = runner.price_slate(SLATE, [game], vintage=vintage, now=NOW)
    assert [r["market"] for r in out["records"]] == ["SPREAD"]
    assert out["refusals"] == [{
        "espn_event_id": game.espn_event_id, "market": "TOTAL",
        "reason": "ENTRY_CAPTURE_MISSING"}]
    game2 = _game(event="401900002",
                  quotes={"SPREAD": _quote(-4.5, pb=None)})
    out2 = runner.price_slate(SLATE, [game2], vintage=vintage, now=NOW)
    reasons = {(r["market"], r["reason"]) for r in out2["refusals"]}
    assert ("SPREAD", "ENTRY_SINGLE_SIDED") in reasons


def test_post_tip_capture_and_duplicate_game_refuse(runner, vintage):
    late = _game(quotes={"SPREAD": _quote(-4.5, cap=TIP)})
    out = runner.price_slate(SLATE, [late], vintage=vintage, now=NOW)
    assert all(r["reason"] == "ENTRY_NOT_PRE_EVENT"
               for r in out["refusals"])
    out2 = runner.price_slate(SLATE, [_game(), _game()],
                              vintage=vintage, now=NOW)
    assert any(r["reason"] == "DUPLICATE_GAME" for r in out2["refusals"])


def test_settlement_grades_accuracy_and_stamps_g3(runner, vintage):
    out = runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW)
    finals = {"401900001": {"home_points": 80, "away_points": 70}}
    closes = {r["row_id"]: {"line": 146.5, "note": "as captured"}
              for r in out["records"]}
    settled = runner.settle_records(out["records"], finals, closes)
    by_market = {s["market"]: s for s in settled}
    total = by_market["TOTAL"]
    assert total["settlement"] == "GRADED" and total["counted"] is False
    assert total["actual_total"] == 150
    rec_total = [r for r in out["records"] if r["market"] == "TOTAL"][0]
    assert total["abs_error_candidate"] == abs(
        rec_total["model_total_candidate"] - 150)
    # G-3: the close is recorded as reported; nothing is excluded.
    assert total["close_supplied"] is True
    assert total["close"]["line"] == 146.5
    assert total["close_rule"] == "CLOSE_RULE_UNDEFINED_GAP_G3"
    missing = runner.settle_records(out["records"], {})
    assert all(s["settlement"] == "RESULT_UNAVAILABLE" for s in missing)


def test_write_entry_records_is_create_only(runner, vintage, tmp_path):
    out = runner.price_slate(SLATE, [_game()], vintage=vintage, now=NOW)
    path = tmp_path / "records.jsonl"
    write_entry_records(out["records"], path)
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert all(json.loads(x)["counted"] is False for x in lines)
    with pytest.raises(CbbForwardError) as exc:
        write_entry_records(out["records"], path)
    assert exc.value.reason == "RECORD_FILE_EXISTS"


def test_games_from_board_consumes_parser_output_shape():
    board = {"sport": "CBB", "board_captured_at": CAP, "games": [{
        "away": "Duke", "home": "Kansas", "header": "Duke @ Kansas",
        "captured_at": CAP,
        "markets": [
            {"market": "SPREAD", "family": "spread", "line": -4.5,
             "side_a": "AWAY", "price_a": -110, "side_b": "HOME",
             "price_b": -110, "raw": "", "subject": None,
             "team": None},
            {"market": "TOTAL", "family": "total", "line": 145.5,
             "side_a": "OVER", "price_a": -110, "side_b": "UNDER",
             "price_b": -110, "raw": "", "subject": None,
             "team": None}]}]}
    fixtures = {"Duke@Kansas": {
        "espn_event_id": "401900001", "away_espn_id": "150",
        "home_espn_id": "2305", "neutral_site": False,
        "tip_utc": TIP, "slate_date": SLATE}}
    games = games_from_board(board, fixtures)
    assert len(games) == 1
    assert games[0].entry_quotes["SPREAD"].line == -4.5
    assert games_from_board(board, {}) == []
