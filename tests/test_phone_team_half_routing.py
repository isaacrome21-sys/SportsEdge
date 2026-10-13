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


def test_phone_aliases_blocked_no_engine_owner_ruling_20261013():
    # Owner ruling (Isaac, Oct 13, 2026) -- supersedes the #2111 routing
    # expectation this test previously asserted: NFL full-game team
    # totals and NFL first-half markets must NOT route to the team/half
    # pricer. They reach the canonical derivative stage and block
    # NO_ENGINE until compliant engines exist, on distinct grounds:
    # team totals -- no verified team-score distribution
    # (NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY); first-half markets --
    # no compliant period distribution (SIMULATION_ROWS_EMPTY).
    # CI verifies this implementation; it does not decide model policy.
    inp = [
        row("FIRST_HALF_TOTAL", "OVER"),
        row("FIRST_HALF_TOTAL", "UNDER"),
        row("ML_1H", "HOME"),
        row("TEAM_TOTALS", "OVER", team="HOME", line=23.5),
        row("TEAM_TOTALS", "UNDER", team="HOME", line=23.5),
    ]

    with patch.object(runner, "price_team_half_rows",
                      return_value=([], [])) as half:
        c = runner.run_full({"sport": "NFL", "lines": inp}, now=NOW, auto_context=False)

    # The team/half pricer receives none of these NFL rows.
    assert half.call_args.args[0] == []
    assert c["summary"]["rows"] == len(inp)
    assert [r["input_index"] for r in c["evaluated_rows"]] == list(range(len(inp)))
    assert len(c["prop_unpriced"]) == len(inp)
    assert c["prop_watchlist"] == []
    evaluated = c["evaluated_rows"]
    assert all(r["status"] == "NO_MODEL_OR_MARKET" for r in evaluated)
    assert all(r["blocker"] == "NO_ENGINE" for r in evaluated)
    # Distinct reasons, asserted -- not just the blocker code.
    assert [r["reason"] for r in evaluated[:3]] == ["SIMULATION_ROWS_EMPTY"] * 3
    assert [r["reason"] for r in evaluated[3:]] == [
        "NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY"] * 2
    # Intake market labels are preserved; the derivative stage's
    # canonical market name is recorded alongside for audit.
    assert evaluated[0]["market"] == "TOTAL_1H"
    assert evaluated[0]["derivative_market"] == "FIRST_HALF_TOTAL"
    assert evaluated[2]["market"] == "ML_1H"
    assert evaluated[2]["derivative_market"] == "FIRST_HALF_MONEYLINE"
    assert evaluated[3]["market"] == "TEAM_TOTAL"
    assert c["prop_model_status"]["team_half_period_fitted"] is False


def test_owner_ruling_first_half_aliases_blocked_period_reason():
    # Every first-half alias the runner accepts resolves to the same
    # period-distribution block (owner ruling, Oct 13, 2026).
    inp = [
        row("FIRST_HALF_SPREAD", "HOME", line=-3.5),
        row("SPREAD_1H", "HOME", line=-3.5),
        row("FIRST_HALF_TEAM_TOTAL", "OVER", team="HOME", line=10.5),
        row("TEAM_TOTAL_1H", "OVER", team="HOME", line=10.5),
        row("FIRST_HALF_MONEYLINE", "HOME"),
    ]
    with patch.object(runner, "price_team_half_rows",
                      return_value=([], [])) as half:
        c = runner.run_full({"sport": "NFL", "lines": inp}, now=NOW, auto_context=False)
    assert half.call_args.args[0] == []
    assert all(r["blocker"] == "NO_ENGINE" for r in c["evaluated_rows"])
    assert all(r["reason"] == "SIMULATION_ROWS_EMPTY"
               for r in c["evaluated_rows"])


def test_owner_ruling_is_nfl_only_cfb_still_routes_team_half():
    # The ruling is NFL-scoped: CFB team totals / first-half totals keep
    # the team/half lane exactly as before (owner ruling, Oct 13, 2026).
    def cfb_row(market, side, **extra):
        return {
            "sport": "CFB", "away": "Delaware Blue Hens",
            "home": "Middle Tennessee Blue Raiders",
            "kickoff": KICKOFF, "market": market, "side": side,
            "line": 21.5, "odds": -110, "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:29:00Z", **extra,
        }

    inp = [
        row("TEAM_TOTALS", "OVER", team="HOME", line=23.5),
        row("TOTAL_1H", "OVER"),
        cfb_row("TEAM_TOTALS", "OVER", team="HOME", line=23.5),
        cfb_row("TOTAL_1H", "OVER"),
    ]

    def fake_team(rows, **kwargs):
        return [
            {"status": "NO_MODEL_OR_MARKET", "reason": "CFB_TEAMHALF_SENTINEL",
             "market": r["market"], "sport": r["sport"],
             "selection": r["side"], "line": r["line"]}
            for r in rows
        ], []

    with patch.object(runner, "price_team_half_rows",
                      side_effect=fake_team) as half:
        c = runner.run_full({"lines": inp}, now=NOW, auto_context=False)

    received = half.call_args.args[0]
    assert [(r["sport"], r["market"]) for r in received] == [
        ("CFB", "TEAM_TOTAL"), ("CFB", "TOTAL_1H")]
    evaluated = {r["input_index"]: r for r in c["evaluated_rows"]}
    assert evaluated[0]["blocker"] == "NO_ENGINE"
    assert evaluated[0]["reason"] == "NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY"
    assert evaluated[1]["blocker"] == "NO_ENGINE"
    assert evaluated[1]["reason"] == "SIMULATION_ROWS_EMPTY"
    assert evaluated[2]["reason"] == "CFB_TEAMHALF_SENTINEL"
    assert evaluated[3]["reason"] == "CFB_TEAMHALF_SENTINEL"


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
    # The outcome is unchanged, but since the owner ruling (Oct 13,
    # 2026) it is produced by the canonical derivative stage's
    # team-score-distribution guard, not the team/half pricer.
    inp = [row("TEAM_TOTAL", "OVER", team="HOME", line=23.5),
           row("TEAM_TOTAL", "UNDER", team="HOME", line=23.5)]
    c = runner.run_full({"sport": "NFL", "lines": inp},
                        now=NOW, auto_context=False,
                        getter=lambda url: None)
    assert c["summary"]["rows"] == 2
    assert len(c["prop_unpriced"]) == 2
    assert all(r["status"] == "NO_MODEL_OR_MARKET" for r in c["evaluated_rows"])
    assert all(r["official_authority"] is False for r in c["evaluated_rows"])
    assert all(r["blocker"] == "NO_ENGINE" for r in c["evaluated_rows"])
    assert all(r["reason"] == "NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY"
               for r in c["evaluated_rows"])
