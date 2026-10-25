"""Append-only line snapshot store + MLB CLV from snapshots of one edited issue."""
import csv
import json
from pathlib import Path

import pytest

from scripts.grade_mlb_card import CardRow, grade_issue
from scripts.mlb_card_clv import compute_clv, fair_probability
from scripts.record_line_snapshot import main as record_main
from sportsedge.line_snapshots import (
    SnapshotError,
    append_snapshot,
    build_snapshot,
    close_snapshot,
    entry_and_close,
    load_snapshots,
    snapshot_path,
)
from tests.test_mlb_card_clv import _feed, card

TITLE = "[MLB LINES] TB Rays @ MIL Brewers WS G2"
START = "2026-10-25T00:00:00Z"


def body(captured, ml):
    return "\n".join(["TB Rays @ MIL Brewers", f"Captured: {captured}", f"ML {ml}", "Total 6.5 -108 -111"])


def snap(captured, ml, picks, root):
    rec = build_snapshot(sport="mlb", issue_number=100, body=body(captured, ml), title=TITLE,
                         game={"game_pk": 1}, board=[], picks=picks, recorded_at="x")
    return append_snapshot(rec, root)


ML = {"pick": "Moneyline Home", "price": -120, "status": "ACTIONABLE"}


def test_append_only_and_idempotent(tmp_path):
    assert snap("2026-10-24T21:00:00-05:00", "+100 -120", [ML], tmp_path)
    path = snapshot_path("mlb", 100, tmp_path)
    first = path.read_text()
    assert not snap("2026-10-24T21:00:00-05:00", "+100 -120", [ML], tmp_path)  # rerun skipped
    assert snap("2026-10-24T18:50:00-05:00", "+110 -130", [], tmp_path)
    assert path.read_text().startswith(first)  # earlier bytes never rewritten
    assert len(load_snapshots("mlb", 100, tmp_path)) == 2


def test_missing_or_naive_captured_refused(tmp_path):
    with pytest.raises(SnapshotError):
        build_snapshot(sport="mlb", issue_number=1, body="A @ B\nML +100 -120", title=None,
                       game={}, board=[], picks=[], recorded_at="x")
    with pytest.raises(SnapshotError):
        build_snapshot(sport="mlb", issue_number=1, body="A @ B\nCaptured: 2026-10-24T17:00:00",
                       title=None, game={}, board=[], picks=[], recorded_at="x")
    with pytest.raises(SnapshotError):
        snapshot_path("xfl", 1, tmp_path)


def test_entry_first_appearance_close_last_prestart(tmp_path):
    snap("2026-10-24T16:00:00-05:00", "+105 -125", [], tmp_path)          # pick absent
    snap("2026-10-24T17:20:00-05:00", "+100 -120", [ML], tmp_path)        # entry
    snap("2026-10-24T18:50:00-05:00", "+110 -130", [dict(ML, price=-130)], tmp_path)  # close
    snap("2026-10-24T19:10:00-05:00", "+300 -400", [ML], tmp_path)        # after start
    snaps = load_snapshots("mlb", 100, tmp_path)
    got = entry_and_close(snaps, "moneyline  home", START)
    assert got.status == "OK"
    assert got.entry_pick["price"] == -120 and got.entry["captured_at"].startswith("2026-10-24T17:20")
    assert got.close["captured_at"].startswith("2026-10-24T18:50")
    assert close_snapshot(snaps, None) is None
    assert entry_and_close(snaps, "Moneyline Home", "2026-10-24T20:00:00Z").status == "NO_PRESTART_SNAPSHOT"
    assert entry_and_close(snaps, "Totals Over 6.5", START).status == "PICK_NOT_IN_PRESTART_SNAPSHOT"


def test_mlb_clv_from_snapshots(tmp_path):
    snap("2026-10-24T17:20:00-05:00", "+100 -120", [ML], tmp_path)
    snap("2026-10-24T18:50:00-05:00", "+110 -130", [], tmp_path)
    snap("2026-10-24T19:10:00-05:00", "+300 -400", [], tmp_path)
    snaps = load_snapshots("mlb", 100, tmp_path)
    out = compute_clv(issue_number=100, picks=[CardRow(1, "Moneyline Home", -120, "ACTIONABLE")],
                      feed=_feed(), entry_issue={}, snapshots=snaps)[0]
    assert out["clv_status"] == "CLV_TRACKED" and out["close_price"] == "-130"
    expect = fair_probability(-130, 110) - fair_probability(-120, 100)
    assert abs(float(out["clv_prob"]) - expect) < 1e-6


def test_mlb_clv_fails_closed_without_prestart(tmp_path):
    snap("2026-10-24T19:10:00-05:00", "+100 -120", [ML], tmp_path)
    out = compute_clv(issue_number=100, picks=[CardRow(1, "Moneyline Home", -120, "ACTIONABLE")],
                      feed=_feed(), entry_issue={}, snapshots=load_snapshots("mlb", 100, tmp_path))[0]
    assert out["clv_status"] == "NO_PRESTART_SNAPSHOT" and out["clv_prob"] == ""


def test_grade_issue_prefers_snapshots(tmp_path):
    snap("2026-10-24T17:20:00-05:00", "+100 -120", [ML], tmp_path)
    snap("2026-10-24T18:50:00-05:00", "+110 -130", [], tmp_path)
    clv = tmp_path / "clv.csv"
    rendered = grade_issue(100, comments=[{"body": card(1, [("Moneyline Home", -120, "ACTIONABLE")])}],
                           feed=_feed(), ledger_path=tmp_path / "l.csv", post_comment=False,
                           clv_ledger_path=clv, snapshot_root=tmp_path)
    assert "CLV_TRACKED" in rendered
    rows = list(csv.DictReader(clv.open()))
    assert rows[0]["close_captured_at"].startswith("2026-10-24T18:50")


def test_record_cli(tmp_path):
    bf = tmp_path / "b.txt"
    bf.write_text(body("2026-10-24T17:20:00-05:00", "+100 -120"))
    cm = tmp_path / "card.md"
    cm.write_text(card(1, [("Moneyline Home", -120, "ACTIONABLE")]))
    args = ["--sport", "mlb", "--issue", "100", "--body-file", str(bf), "--title", TITLE,
            "--card-md", str(cm), "--root", str(tmp_path / "s")]
    assert record_main(args) == 0 and record_main(args) == 0
    snaps = load_snapshots("mlb", 100, tmp_path / "s")
    assert len(snaps) == 1 and snaps[0]["picks"][0]["price"] == -120
    assert any(r["market_type"] == "MONEYLINE" for r in snaps[0]["board"])
    nf = tmp_path / "n.txt"
    nf.write_text("A @ B\nML +100 -120")
    assert record_main(["--sport", "nfl", "--issue", "5", "--body-file", str(nf),
                        "--root", str(tmp_path / "s")]) == 2
    pj = tmp_path / "p.json"
    pj.write_text(json.dumps([{"pick": "KC -3", "price": -110}]))
    nf.write_text("KC @ BUF\nCaptured: 2026-10-26T19:00:00-04:00\nSpread KC -3 -110 / BUF +3 -110")
    assert record_main(["--sport", "nfl", "--issue", "5", "--body-file", str(nf),
                        "--picks-json", str(pj), "--root", str(tmp_path / "s")]) == 0
