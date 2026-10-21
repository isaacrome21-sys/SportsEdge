"""Synthetic-only regression probes for the operator-pinned RUN IT annex."""
from datetime import datetime, timezone

from sportsedge.research.nfl_nba_engine_card_annex import (
    build_annex, content_hash,
)


AT = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)
STAMP = "2026-10-20T19:59:00Z"
START = "2026-10-21T00:00:00Z"


def _quotes(sport, market, player_id="", team=None):
    return [
        {"sport": sport, "market": market, "player_id": player_id,
         "team": team, "event_id": "synthetic-event-1",
         "line": 5.5, "selection": side, "book": "DraftKings",
         "odds_american": -110, "quote_captured_at": STAMP}
        for side in ("OVER", "UNDER")
    ]


def _nfl_history():
    out = {2026: {}}
    for pid in ("p1", "p2"):
        out[2026][pid] = [
            (week, "WR", {
                "targets": 8.0, "receptions": 5.0,
                "rushing_yards": 3.0, "receiving_yards": 60.0,
                "carries": 1.0, "rushing_tds": 0.0,
                "receiving_tds": 0.0,
            }) for week in range(1, 7)
        ]
    return out


def _fixtures(sport):
    return {"synthetic-event-1": {
        "event_id": "synthetic-event-1", "sport": sport,
        "start_time": START, "venue_state": "IL",
        "home": "NYK" if sport == "NBA" else "CHI",
        "away": "BOS" if sport == "NBA" else "GB",
        "season": 2026, "week": 7,
        "player_id_map": {"p1": "p1", "p2": "p2"},
        "target_date": "2026-10-20",
    }}


def _kwargs(sport, games):
    fixtures = _fixtures(sport)
    history = {sport: games}
    return dict(at=AT, fixtures=fixtures, history=history,
                pins={"fixtures_sha256": content_hash(fixtures),
                      sport.lower() + "_history_sha256": content_hash(games)})


def test_nfl_targets_real_engine_priced_without_gate_lift():
    rows = _quotes("NFL", "TARGETS", player_id="p1")
    result = build_annex(rows, [{"status": "BLOCKED"}] * 2,
                         **_kwargs("NFL", _nfl_history()))
    assert len(result["readouts"]) == 2
    for readout in result["readouts"]:
        assert readout["status"] == "RESEARCH_ESTIMATE_UNVALIDATED"
        assert readout["eligible"] is False
        assert readout["play_authority"] is False
        assert 0 <= readout["projection"]["p_over"] <= 1


def test_history_pin_mismatch_fail_closed():
    rows = _quotes("NFL", "TARGETS", player_id="p1")
    kw = _kwargs("NFL", _nfl_history())
    kw["pins"]["nfl_history_sha256"] = "0" * 64
    result = build_annex(rows, [{}, {}], **kw)
    assert all(r["reason"] == "OPERATOR_HISTORY_PIN_MISSING_OR_MISMATCH"
               for r in result["readouts"])


def test_missing_pair_stale_and_untrusted_book_refuse():
    rows = _quotes("NFL", "TARGETS", player_id="p1")
    kw = _kwargs("NFL", _nfl_history())
    one = build_annex(rows[:1], [{}], **kw)
    assert one["readouts"][0]["reason"] == "DK_PAIR_MISSING_OR_STALE"
    old = [dict(r, quote_captured_at="2026-10-20T19:45:00Z")
           for r in rows]
    stale = build_annex(old, [{}, {}], **kw)
    assert stale["readouts"][0]["reason"] == "DK_PAIR_MISSING_OR_STALE"
    fake = [dict(r, book="OtherBook") for r in rows]
    untrusted = build_annex(fake, [{}, {}], **kw)
    assert untrusted["readouts"][0]["reason"] == "DRAFTKINGS_QUOTE_REQUIRED"


def test_fixture_bound_and_tennessee_blocked():
    rows = _quotes("NFL", "TARGETS", player_id="p1")
    kw = _kwargs("NFL", _nfl_history())
    kw["fixtures"]["synthetic-event-1"]["venue_state"] = "TN"
    kw["pins"]["fixtures_sha256"] = content_hash(kw["fixtures"])
    out = build_annex(rows, [{}, {}], **kw)
    assert all(r["reason"] == "TENNESSEE_FIXTURE_BLOCKED"
               for r in out["readouts"])


def test_qb_interceptions_cannot_route_to_defensive_engine():
    rows = _quotes("NFL", "PLAYER_INTERCEPTIONS", player_id="p1")
    assert build_annex(rows, [{}, {}],
                       **_kwargs("NFL", _nfl_history())) is None


def test_nba_engine_outputs_points_not_probabilities():
    # Synthetic in-season history exceeds the incumbent engine warm-up.
    games = [{"date": f"2026-09-{(i % 28) + 1:02d}",
              "season": 2026, "home": "NYK" if i % 2 else "BOS",
              "away": "BOS" if i % 2 else "NYK",
              "home_pts": 112.0, "away_pts": 108.0}
             for i in range(110)]
    rows = _quotes("NBA", "TEAM_TOTAL", team="NYK")
    original = [{"status": "BLOCKED", "eligible": False},
                {"status": "BLOCKED", "eligible": False}]
    before = [dict(x) for x in original]
    result = build_annex(rows, original, **_kwargs("NBA", games))
    assert original == before
    for readout in result["readouts"]:
        assert readout["status"] == "RESEARCH_ESTIMATE_UNVALIDATED"
        assert readout["projection"]["team_totals"]
        assert "p_over" not in readout["projection"]
        assert readout["projection"]["market_test"] == "NONE"


def test_nba_period_without_frozen_fit_refuses():
    games = [{"date": f"2026-09-{(i % 28) + 1:02d}",
              "season": 2026, "home": "NYK", "away": "BOS",
              "home_pts": 110.0, "away_pts": 108.0} for i in range(110)]
    rows = _quotes("NBA", "TEAM_QUARTER_TOTAL", team="NYK")
    result = build_annex(rows, [{}, {}], **_kwargs("NBA", games))
    assert all(r["status"] == "REFUSED" for r in result["readouts"])
    assert all(r["reason"].startswith("NBA_PERIOD_") for r in result["readouts"])


def test_no_engine_data_in_issue_intake():
    rows = _quotes("NFL", "TARGETS", player_id="p1")
    for row in rows:
        row["nfl_data_by_season"] = _nfl_history()
        row["fixture_binding_verified"] = True
    result = build_annex(rows, [{}, {}], at=AT)
    assert all(r["reason"] == "OPERATOR_FIXTURE_PIN_MISSING_OR_MISMATCH"
               for r in result["readouts"])


def test_run_full_annex_does_not_mutate_existing_card_surfaces():
    from artifacts.run_it_full import run_full
    # All rows are registry-blocked; comparison stays on the *exact* original
    # input/evaluated surfaces, not on a reconstructed approximation.
    rows = _quotes("NFL", "TARGETS", player_id="p1")
    payload = {"lines": rows}
    plain = run_full(payload, now=AT, as_of=AT, auto_context=False)
    with_annex = run_full(payload, now=AT, as_of=AT, auto_context=False,
                          annex_history={"NFL": _nfl_history()},
                          annex_fixtures=_fixtures("NFL"),
                          annex_pins=_kwargs("NFL", _nfl_history())["pins"])
    baseline_annex = plain.pop("nfl_nba_engine_research_annex")
    # The new annex intentionally exists even without operator evidence:
    # it fails closed on each family. Strip the annex from BOTH cards
    # before comparing their pre-existing canonical surfaces.
    assert baseline_annex["readouts"]
    assert all(r["status"] == "REFUSED"
               and r["reason"] == "OPERATOR_FIXTURE_PIN_MISSING_OR_MISMATCH"
               for r in baseline_annex["readouts"])
    annex = with_annex.pop("nfl_nba_engine_research_annex")
    assert annex["readouts"]
    assert all(r["status"] == "RESEARCH_ESTIMATE_UNVALIDATED"
               for r in annex["readouts"])
    assert with_annex == plain
