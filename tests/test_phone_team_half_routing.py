"""Phone RUN IT team/half routing regressions; no fake bettor probabilities."""
from datetime import datetime, timezone
from unittest.mock import patch

from artifacts import run_it_full as runner

NOW = datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T00:00:00Z"


def row(market, side, **extra):
    return {
        "sport": "NFL", "away": "Buffalo Bills", "home": "Los Angeles Rams",
        "kickoff": KICKOFF, "market": market, "side": side,
        "line": 21.5, "odds": -110, "book": "draftkings",
        "quote_captured_at": "2026-10-11T20:29:00Z", **extra,
    }


def test_phone_aliases_route_team_half_without_losing_unsupported_rows():
    inp = [
        row("FIRST_HALF_TOTAL", "OVER"),
        row("FIRST_HALF_TOTAL", "UNDER"),
        row("ML_1H", "HOME"),
        row("TEAM_TOTALS", "OVER", team="HOME", line=23.5),
        row("TEAM_TOTALS", "UNDER", team="HOME", line=23.5),
    ]

    def fake_team(rows, **kwargs):
        assert len(rows) == 4
        assert [r["market"] for r in rows] == [
            "TOTAL_1H", "TOTAL_1H", "TEAM_TOTAL", "TEAM_TOTAL"]
        return [
            {"status": "WATCH_UNFITTED_PERIOD_SPLIT" if r["market"] == "TOTAL_1H" else "WATCH_BELOW_EV_FLOOR",
             "market": r["market"], "sport": "NFL",
             "selection": r["side"], "source": "FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED",
             "line": r["line"], "ev_per_dollar": -0.01}
            for r in rows
        ], []

    with patch.object(runner, "price_team_half_rows", side_effect=fake_team):
        c = runner.run_full({"sport": "NFL", "lines": inp}, now=NOW, auto_context=False)

    assert c["summary"]["rows"] == len(inp)
    assert [r["input_index"] for r in c["evaluated_rows"]] == list(range(len(inp)))
    assert len(c["prop_unpriced"]) == 1
    assert c["prop_unpriced"][0]["market"] == "ML_1H"
    assert len(c["prop_watchlist"]) == 4
    assert c["evaluated_rows"][0]["market"] == "TOTAL_1H"
    assert c["evaluated_rows"][3]["market"] == "TEAM_TOTAL"
    assert c["prop_model_status"]["team_half_period_fitted"] is False


def test_team_half_never_hijacks_football_player_props():
    x = row("RECEIVING_YARDS", "OVER", player_name="Example Receiver",
            line=50.5)
    with patch.object(runner, "price_team_half_rows", return_value=([], [])) as half:
        with patch.object(runner, "phone_nfl_player_rows", return_value=([
            {"status": "NO_MODEL_OR_MARKET", "reason": "TEST_PLAYER_HISTORY_MISSING",
             "market": "PLAYER_RECEIVING_YARDS", "sport": "NFL"}
        ], [])) as nfl:
            c = runner.run_full({"sport": "NFL", "lines": [x]},
                                now=NOW, auto_context=False)
    assert half.call_args.args[0] == []
    assert nfl.call_args.args[0][0]["market"] == "PLAYER_RECEIVING_YARDS"
    assert c["evaluated_rows"][0]["reason"] == "TEST_PLAYER_HISTORY_MISSING"


def test_no_public_sources_means_no_team_total_probabilities():
    inp = [row("TEAM_TOTAL", "OVER", team="HOME", line=23.5),
           row("TEAM_TOTAL", "UNDER", team="HOME", line=23.5)]
    c = runner.run_full({"sport": "NFL", "lines": inp},
                        now=NOW, auto_context=False,
                        getter=lambda url: None)
    assert c["summary"]["rows"] == 2
    assert len(c["prop_unpriced"]) == 2
    assert all(r["status"] == "NO_MODEL_OR_MARKET" for r in c["evaluated_rows"])
    assert all(r["official_authority"] is False for r in c["evaluated_rows"])
